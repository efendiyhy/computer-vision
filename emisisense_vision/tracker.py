"""Pelacak multi-objek bergaya SORT: filter Kalman kecepatan-konstan + asosiasi IoU (Hungarian).

Tiap frame: ``predict()`` memajukan semua jalur; bila ada deteksi baru, ``update(dets)`` mengasosiasikan.
Kelas jalur ditentukan dengan voting berbobot keyakinan sehingga label tidak berkedip.
"""
from __future__ import annotations

import itertools
from collections import Counter, deque

import numpy as np
from scipy.optimize import linear_sum_assignment

from .detector import Detection

_ids = itertools.count(1)


def iou_matrix(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    if len(a) == 0 or len(b) == 0:
        return np.zeros((len(a), len(b)))
    x1 = np.maximum(a[:, None, 0], b[None, :, 0]); y1 = np.maximum(a[:, None, 1], b[None, :, 1])
    x2 = np.minimum(a[:, None, 2], b[None, :, 2]); y2 = np.minimum(a[:, None, 3], b[None, :, 3])
    inter = np.clip(x2 - x1, 0, None) * np.clip(y2 - y1, 0, None)
    aa = (a[:, 2] - a[:, 0]) * (a[:, 3] - a[:, 1]); ab = (b[:, 2] - b[:, 0]) * (b[:, 3] - b[:, 1])
    return inter / (aa[:, None] + ab[None, :] - inter + 1e-9)


class Track:
    def __init__(self, det: Detection, t: float):
        self.id = next(_ids)
        cx, cy = (det.x1 + det.x2) / 2, (det.y1 + det.y2) / 2
        # keadaan: [cx, cy, w, h, vx, vy]
        self.x = np.array([cx, cy, det.w, det.h, 0.0, 0.0])
        self.P = np.diag([25.0, 25.0, 25.0, 25.0, 400.0, 400.0])
        self.votes: Counter = Counter({det.cls: det.conf})
        self.conf = det.conf
        self.hits = 1
        self.age = 1
        self.miss = 0
        self.t0 = t
        self.last_t = t
        self.trail: deque = deque(maxlen=60)       # (t, cx, by) titik kontak tanah
        self.speed_kmh: float | None = None
        self.max_speed = 0.0
        self.side: dict[str, int] = {}              # id garis -> tanda sisi terakhir
        self.counted: set[tuple[str, int]] = set()
        self.in_roi = False
        self.entered_roi_t: float | None = None

    # ---- properti turunan
    @property
    def cls(self) -> str:
        return self.votes.most_common(1)[0][0]

    @property
    def box(self):
        cx, cy, w, h = self.x[:4]
        return cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2

    @property
    def foot(self):
        return float(self.x[0]), float(self.x[1] + self.x[3] / 2)

    @property
    def confirmed(self) -> bool:
        return self.hits >= 3

    # ---- Kalman (dt dalam satuan frame deteksi)
    def predict(self, dt: float = 1.0):
        F = np.eye(6); F[0, 4] = dt; F[1, 5] = dt
        Q = np.diag([1.0, 1.0, 2.0, 2.0, 4.0, 4.0]) * dt
        self.x = F @ self.x
        self.x[2:4] = np.maximum(self.x[2:4], 4.0)
        self.P = F @ self.P @ F.T + Q
        self.age += 1
        self.miss += 1

    def update(self, det: Detection, t: float):
        z = np.array([(det.x1 + det.x2) / 2, (det.y1 + det.y2) / 2, det.w, det.h])
        H = np.zeros((4, 6)); H[:4, :4] = np.eye(4)
        R = np.diag([9.0, 9.0, 25.0, 25.0])
        S = H @ self.P @ H.T + R
        K = self.P @ H.T @ np.linalg.inv(S)
        self.x = self.x + K @ (z - H @ self.x)
        self.P = (np.eye(6) - K @ H) @ self.P
        self.votes[det.cls] += det.conf
        self.conf = 0.7 * self.conf + 0.3 * det.conf
        self.hits += 1
        self.miss = 0


class Tracker:
    def __init__(self, iou_thr: float = 0.18, max_miss: int = 14, max_dist_frac: float = 0.12):
        self.tracks: list[Track] = []
        self.iou_thr = iou_thr
        self.max_miss = max_miss
        self.max_dist_frac = max_dist_frac

    def reset(self):
        self.tracks.clear()

    def step(self, dets: list[Detection] | None, t: float, frame_diag: float, dt_frames: float = 1.0) -> list[Track]:
        """Satu langkah waktu. dets=None berarti frame tanpa deteksi (hanya prediksi)."""
        for tr in self.tracks:
            tr.predict(dt_frames)
        if dets is not None:
            self._associate(dets, t, frame_diag)
        self.tracks = [tr for tr in self.tracks if tr.miss <= self.max_miss and not (tr.hits < 3 and tr.miss > 3)]
        for tr in self.tracks:
            if tr.miss == 0:
                tr.last_t = t
            tr.trail.append((t, tr.foot[0], tr.foot[1]))
        return self.tracks

    def _associate(self, dets: list[Detection], t: float, frame_diag: float):
        if self.tracks and dets:
            tb = np.array([tr.box for tr in self.tracks]); db = np.array([[d.x1, d.y1, d.x2, d.y2] for d in dets])
            iou = iou_matrix(tb, db)
            # biaya: IoU + sedikit bonus kedekatan pusat (membantu objek cepat dengan IoU rendah)
            tc = np.array([[(b[0] + b[2]) / 2, (b[1] + b[3]) / 2] for b in tb])
            dc = np.array([[(b[0] + b[2]) / 2, (b[1] + b[3]) / 2] for b in db])
            dist = np.linalg.norm(tc[:, None] - dc[None], axis=2) / frame_diag
            score = iou + 0.25 * np.clip(1 - dist / self.max_dist_frac, 0, 1)
            score[(iou < 0.02) & (dist > self.max_dist_frac)] = 0
            rows, cols = linear_sum_assignment(-score)
            matched_t, matched_d = set(), set()
            for r, c in zip(rows, cols):
                if score[r, c] >= self.iou_thr:
                    self.tracks[r].update(dets[c], t)
                    matched_t.add(r); matched_d.add(c)
            unmatched = [i for i in range(len(dets)) if i not in matched_d]
        else:
            unmatched = list(range(len(dets)))
        for i in unmatched:
            self.tracks.append(Track(dets[i], t))
