"""Pelacak multi-objek berbasis waktu (Kalman kecepatan-konstan + penugasan Hungarian).

Dirancang untuk sumber dengan frame rate rendah atau tidak rata (CCTV publik): gerbang pencocokan
dihitung dari ukuran kotak dan selang waktu, bukan dari IoU antar-frame berurutan.
"""
from __future__ import annotations

import itertools
import math
from collections import Counter, deque

import numpy as np
from scipy.optimize import linear_sum_assignment

from .detector import Detection

_ids = itertools.count(1)
VEHICLE_FAMILY = {"car": 0, "bus": 0, "truck": 0, "other": 0, "motorbike": 1, "bicycle": 1, "person": 2}


class Track:
    def __init__(self, det: Detection, t: float):
        self.id = next(_ids)
        cx, cy = (det.x1 + det.x2) / 2, (det.y1 + det.y2) / 2
        self.x = np.array([cx, cy, det.w, det.h, 0.0, 0.0])          # cx, cy, w, h, vx, vy (piksel, piksel/detik)
        self.P = np.diag([30.0, 30.0, 40.0, 40.0, 90.0 ** 2, 90.0 ** 2])
        self.votes: Counter = Counter()
        self._vote(det)
        self.conf = det.conf
        self.hits = 1
        self.miss_steps = 0
        self.t0 = t
        self.last_t = t           # waktu terakhir diperbarui oleh deteksi
        self.pred_t = t
        self.trail: deque = deque(maxlen=80)          # (t, x, y_kaki) hanya dari pengukuran nyata
        self.trail.append((t, cx, det.y2))
        self.path_len = 0.0
        self.first_foot = (cx, det.y2)
        self.speed_kmh: float | None = None
        self.max_speed = 0.0
        self.side: dict[str, int] = {}
        self.side0: dict[str, int] = {}      # sisi garis tempat trek pertama kali terlihat (asal)
        self.counted: set[tuple[str, int]] = set()
        self.counted_unique = False
        self.in_roi = False
        self.skip_free = False     # pernah melintasi garis berlawanan panah: bukan kendaraan 'di luar garis'

    def _vote(self, det: Detection):
        w = 0.15 if det.cls == "other" else max(det.conf, 0.05)
        self.votes[det.cls] += w

    # ---- properti
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
    def size(self) -> float:
        return float(max(self.x[2], self.x[3]))

    @property
    def confirmed(self) -> bool:
        return self.hits >= 2

    @property
    def displacement(self) -> float:
        f = self.foot
        return math.hypot(f[0] - self.first_foot[0], f[1] - self.first_foot[1])

    @property
    def direction_vec(self):
        return float(self.x[4]), float(self.x[5])

    # ---- Kalman
    def predict(self, dt: float):
        dt = max(1e-3, min(dt, 3.0))
        F = np.eye(6); F[0, 4] = dt; F[1, 5] = dt
        q = np.diag([4.0, 4.0, 6.0, 6.0, 900.0, 900.0]) * dt
        self.x = F @ self.x
        self.x[2:4] = np.maximum(self.x[2:4], 4.0)
        self.P = F @ self.P @ F.T + q
        self.miss_steps += 1

    def extrapolate(self, now: float):
        """Kotak untuk tampilan pada waktu 'now' (tanpa mengubah keadaan)."""
        dt = max(0.0, min(now - self.pred_t, 1.2))
        cx, cy, w, h = self.x[:4]
        return cx + self.x[4] * dt, cy + self.x[5] * dt, w, h

    def update(self, det: Detection, t: float):
        z = np.array([(det.x1 + det.x2) / 2, (det.y1 + det.y2) / 2, det.w, det.h])
        H = np.zeros((4, 6)); H[:4, :4] = np.eye(4)
        R = np.diag([16.0, 16.0, 49.0, 49.0])
        S = H @ self.P @ H.T + R
        K = self.P @ H.T @ np.linalg.inv(S)
        before = self.foot
        self.x = self.x + K @ (z - H @ self.x)
        self.P = (np.eye(6) - K @ H) @ self.P
        self._vote(det)
        self.conf = 0.6 * self.conf + 0.4 * det.conf
        self.hits += 1
        self.miss_steps = 0
        self.last_t = t
        f = self.foot
        self.path_len += math.hypot(f[0] - before[0], f[1] - before[1])
        self.trail.append((t, f[0], f[1]))


class Tracker:
    def __init__(self, max_age_s: float = 1.6, min_age_steps: int = 2):
        self.tracks: list[Track] = []
        self.dead: list[Track] = []
        self.max_age_s = max_age_s
        self.last_t: float | None = None
        self.steps = 0

    def reset(self):
        self.tracks.clear(); self.dead.clear(); self.last_t = None

    def step(self, dets: list[Detection], t: float) -> list[Track]:
        """Satu siklus deteksi pada waktu t (detik)."""
        dt = 0.1 if self.last_t is None else max(1e-3, t - self.last_t)
        self.last_t = t
        self.steps += 1
        self.dead = []
        for tr in self.tracks:
            tr.predict(dt)
            tr.pred_t = t
        self._associate(dets, t, dt)
        keep = []
        for tr in self.tracks:
            age_missing = t - tr.last_t
            limit = self.max_age_s if tr.hits >= 2 else min(self.max_age_s, 0.8)
            if age_missing > max(limit, 1.5 * dt):
                (self.dead if tr.hits >= 2 else []).append(tr)
            else:
                keep.append(tr)
        self.tracks = keep
        return self.tracks

    def _associate(self, dets: list[Detection], t: float, dt: float):
        if self.tracks and dets:
            n, m = len(self.tracks), len(dets)
            cost = np.full((n, m), 1e3)
            for i, tr in enumerate(self.tracks):
                px, py = tr.x[0], tr.x[1]
                tb = tr.box
                tsz = tr.size
                tentative = tr.hits <= 2
                for j, d in enumerate(dets):
                    dcx, dcy = (d.x1 + d.x2) / 2, (d.y1 + d.y2) / 2
                    dist = math.hypot(dcx - px, dcy - py)
                    sz = max(tsz, d.w, d.h)
                    gate = sz * (2.2 if tentative else 1.5) + math.hypot(tr.x[4], tr.x[5]) * dt * 0.35
                    if dist > gate:
                        continue
                    ix = max(0.0, min(tb[2], d.x2) - max(tb[0], d.x1)); iy = max(0.0, min(tb[3], d.y2) - max(tb[1], d.y1))
                    inter = ix * iy
                    iou = inter / ((tb[2] - tb[0]) * (tb[3] - tb[1]) + d.w * d.h - inter + 1e-9)
                    c = dist / gate * 0.7 + (1 - iou) * 0.3
                    fa, fb = VEHICLE_FAMILY.get(tr.cls, 0), VEHICLE_FAMILY.get(d.cls, 0)
                    if fa != fb:
                        c += 0.25
                    cost[i, j] = c
            rows, cols = linear_sum_assignment(cost)
            used = set()
            for r, c in zip(rows, cols):
                if cost[r, c] < 1.0:
                    self.tracks[r].update(dets[c], t)
                    used.add(c)
            new = [dets[j] for j in range(m) if j not in used]
        else:
            new = list(dets)
        for d in new:
            if d.cls == "other" and d.conf < 0.35:
                # kelas 'other' dari gerak: abaikan bila sudah ada trek yang menempati area itu
                if any(self._inside(tr, d) for tr in self.tracks):
                    continue
            self.tracks.append(Track(d, t))

    @staticmethod
    def _inside(tr: Track, d: Detection) -> bool:
        cx, cy = (d.x1 + d.x2) / 2, (d.y1 + d.y2) / 2
        b = tr.box
        return b[0] - 4 <= cx <= b[2] + 4 and b[1] - 4 <= cy <= b[3] + 4
