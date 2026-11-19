"""Simulator lalu lintas (mode --demo): adegan jalan sintetis + deteksi palsu.

Dipakai untuk mencoba dashboard tanpa CCTV. Deteksi tetap melewati tracker, penghitung, dan analitik
yang sama dengan mode nyata, sehingga seluruh alur diuji.
"""
from __future__ import annotations

import random

import cv2
import numpy as np

from .config import CLASS_COLOR
from .detector import Detection

SPEC = {  # lebar, tinggi relatif pada y=1 (dekat kamera), kecepatan relatif, bobot kemunculan
    "car": (0.16, 0.13, 1.0, 0.46), "motorbike": (0.07, 0.11, 1.25, 0.34),
    "bus": (0.22, 0.20, 0.8, 0.07), "truck": (0.20, 0.17, 0.85, 0.08), "bicycle": (0.05, 0.10, 0.45, 0.05),
    "person": (0.028, 0.095, 0.16, 0.10),
}


class SimVehicle:
    def __init__(self, cls: str, lane_x: float, going_down: bool):
        self.cls = cls
        self.lane_x = lane_x
        self.down = going_down
        w, h, sp, _ = SPEC[cls]
        self.base = (w, h)
        self.speed = sp * random.uniform(0.18, 0.30)      # satuan layar/detik (terhadap y)
        self.y = 0.26 if going_down else 1.02
        self.jitter = random.uniform(-0.01, 0.01)

    def step(self, dt):
        self.y += (1 if self.down else -1) * self.speed * dt * (0.35 + self.y)

    @property
    def alive(self):
        return 0.22 < self.y < 1.08

    def box(self, W, H):
        s = 0.25 + 0.75 * min(1.0, (self.y - 0.25) / 0.75)
        w, h = self.base[0] * W * s, self.base[1] * H * s
        # lajur menyempit ke titik hilang di y=0.25
        cx = W * (0.5 + (self.lane_x - 0.5) * (0.25 + 0.75 * (self.y - 0.25) / 0.75)) + self.jitter * W
        by = H * self.y
        return cx - w / 2, by - h, cx + w / 2, by


class TrafficSimulator:
    def __init__(self, width=960, height=540, seed=7):
        self.W, self.H = width, height
        random.seed(seed)
        self.vehicles: list[SimVehicle] = []
        self.t = 0.0
        self._next = 0.0
        self._bg = self._make_bg()

    def _make_bg(self):
        W, H = self.W, self.H
        img = np.zeros((H, W, 3), np.uint8)
        for y in range(H):  # langit -> tanah
            k = y / H
            img[y, :] = (int(210 - 60 * k), int(190 - 50 * k), int(160 - 40 * k)) if y < H * 0.24 else (70, 78, 74)
        hor = int(H * 0.24)
        top_l, top_r = W * 0.43, W * 0.57
        road = np.array([[top_l, hor], [top_r, hor], [W * 1.02, H], [-W * 0.02, H]], np.int32)
        cv2.fillPoly(img, [road], (58, 58, 62))
        for frac in (0.5,):  # marka tengah putus-putus
            for i in range(14):
                a, b = i / 14, (i + 0.5) / 14
                pa = (W * (0.5 + (frac - 0.5) * 0), hor + (H - hor) * a ** 1.4)
                pb = (W * (0.5 + (frac - 0.5) * 0), hor + (H - hor) * b ** 1.4)
                cv2.line(img, (int(pa[0]), int(pa[1])), (int(pb[0]), int(pb[1])), (210, 210, 200), max(1, int(1 + 4 * a)))
        cv2.line(img, (int(top_l), hor), (0, H), (200, 200, 190), 2)
        cv2.line(img, (int(top_r), hor), (W, H), (200, 200, 190), 2)
        for x in range(0, W, 38):  # siluet bangunan
            hgt = random.randint(20, 70)
            cv2.rectangle(img, (x, hor - hgt), (x + 30, hor), (95, 100, 98), -1)
        return img

    def step(self, dt: float):
        self.t += dt
        if self.t >= self._next:
            r, acc = random.random() * sum(v[3] for v in SPEC.values()), 0.0
            for cls, (_, _, _, wgt) in SPEC.items():
                acc += wgt
                if r <= acc:
                    break
            down = random.random() < 0.5
            lane = random.choice([0.08, 0.14] if down else [0.86, 0.92]) if cls == "person" else random.choice([0.28, 0.40] if down else [0.60, 0.72])
            self.vehicles.append(SimVehicle(cls, lane, down))
            self._next = self.t + random.uniform(0.35, 1.7)
        for v in self.vehicles:
            v.step(dt)
        self.vehicles = [v for v in self.vehicles if v.alive]

    def frame_and_dets(self) -> tuple[np.ndarray, list[Detection]]:
        img = self._bg.copy()
        dets = []
        for v in sorted(self.vehicles, key=lambda v: v.y):
            x1, y1, x2, y2 = v.box(self.W, self.H)
            col = tuple(int(c * 0.8) for c in CLASS_COLOR[v.cls])
            if v.cls == "person":          # sosok sederhana: kepala + badan
                cx, hd = int((x1 + x2) / 2), max(2, int((y2 - y1) * 0.16))
                cv2.circle(img, (cx, int(y1) + hd), hd, (190, 205, 225), -1)
                cv2.rectangle(img, (int(x1), int(y1) + 2 * hd), (int(x2), int(y2)), col, -1)
                if x2 - x1 > 3 and y2 - y1 > 8:
                    dets.append(Detection(x1 + random.uniform(-1, 1), y1 + random.uniform(-1, 1), x2 + random.uniform(-1, 1), y2 + random.uniform(-1, 1), random.uniform(0.55, 0.95), "person"))
                continue
            cv2.rectangle(img, (int(x1), int(y1)), (int(x2), int(y2)), col, -1)
            cv2.rectangle(img, (int(x1), int(y1)), (int(x2), int(y2)), (25, 25, 25), 1)
            wy = int(y1 + (y2 - y1) * 0.25)
            cv2.rectangle(img, (int(x1 + (x2 - x1) * 0.12), wy), (int(x2 - (x2 - x1) * 0.12), int(y1 + (y2 - y1) * 0.5)), (35, 35, 40), -1)
            cv2.putText(img, "DEMO", (int(x1), max(12, int(y1) - 4)), cv2.FONT_HERSHEY_PLAIN, 0.9, (240, 240, 240), 1)
            if x2 - x1 > 8 and y2 - y1 > 8:
                dets.append(Detection(x1 + random.uniform(-2, 2), y1 + random.uniform(-2, 2), x2 + random.uniform(-2, 2),
                                      y2 + random.uniform(-2, 2), random.uniform(0.62, 0.97), v.cls))
        return img, dets
