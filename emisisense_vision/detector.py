"""Detektor kendaraan.

SSDDetector   MobileNet-SSD (OpenCV DNN, tanpa dependensi tambahan). Karena model ini lemah pada objek kecil,
              deteksi dilakukan berlapis:
                1. seluruh frame,
                2. zona pengamatan diperbesar (satu potongan, atau ubin bila presisi "teliti"),
                3. potongan di sekitar objek bergerak (hasil MotionDetector) -> kendaraan jauh tetap terbaca,
                4. objek bergerak yang tetap tidak dikenali model dijadikan kelas "other" (kendaraan lain)
                   agar tetap terhitung (kecuali bila tumpang tindih dengan orang).
YOLODetector  opsional (pip install ultralytics): lebih akurat, menambah kelas truk.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
PROTOTXT = ROOT / "models" / "deploy.prototxt"
CAFFEMODEL = ROOT / "models" / "mobilenet_iter_73000.caffemodel"

VOC_TO_CLASS = {2: "bicycle", 6: "bus", 7: "car", 14: "motorbike", 15: "person"}
QUALITY_FAST, QUALITY_BALANCED, QUALITY_THOROUGH = 1, 2, 3


@dataclass
class Detection:
    x1: float
    y1: float
    x2: float
    y2: float
    conf: float
    cls: str
    src: str = "full"

    @property
    def w(self): return self.x2 - self.x1

    @property
    def h(self): return self.y2 - self.y1


def iou(a: Detection, b: Detection) -> float:
    ix = max(0.0, min(a.x2, b.x2) - max(a.x1, b.x1)); iy = max(0.0, min(a.y2, b.y2) - max(a.y1, b.y1))
    inter = ix * iy
    return inter / (a.w * a.h + b.w * b.h - inter + 1e-9)


def covered(box, dets, frac=0.55) -> bool:
    """Apakah sebagian besar kotak (x1,y1,x2,y2) tertutup oleh salah satu deteksi?"""
    area = max(1.0, (box[2] - box[0]) * (box[3] - box[1]))
    for d in dets:
        ix = max(0.0, min(box[2], d.x2) - max(box[0], d.x1)); iy = max(0.0, min(box[3], d.y2) - max(box[1], d.y1))
        if ix * iy / area >= frac:
            return True
    return False


def nms(dets: list[Detection], iou_thr: float = 0.5) -> list[Detection]:
    if len(dets) < 2:
        return dets
    keep = cv2.dnn.NMSBoxes([[d.x1, d.y1, d.w, d.h] for d in dets], [d.conf for d in dets], 0.0, iou_thr)
    return [dets[int(i)] for i in np.array(keep).flatten()]


# --------------------------------------------------------------------------------------------- gerak
class MotionDetector:
    """Pemisah latar (MOG2) di resolusi kecil untuk menemukan objek bergerak pada kamera tetap."""

    def __init__(self, work_width: int = 320):
        self.work_w = work_width
        self.reset()

    def reset(self):
        self.bg = cv2.createBackgroundSubtractorMOG2(history=160, varThreshold=26, detectShadows=True)
        self.n = 0
        self.k_open = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
        self.k_close = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9))
        self.fg_ratio = 0.0
        self.mask_small = None

    def blobs(self, frame: np.ndarray, roi_poly_norm, min_area_frac: float = 0.0012, max_area_frac: float = 0.45):
        H, W = frame.shape[:2]
        s = self.work_w / float(W)
        small = cv2.resize(frame, (self.work_w, max(8, int(H * s))), interpolation=cv2.INTER_AREA)
        small = cv2.GaussianBlur(small, (3, 3), 0)
        fg = self.bg.apply(small)
        self.n += 1
        if self.n < 15:
            return []
        fg = cv2.threshold(fg, 200, 255, cv2.THRESH_BINARY)[1]        # buang bayangan (nilai 127)
        sh, sw = fg.shape
        if roi_poly_norm:
            m = np.zeros_like(fg)
            cv2.fillPoly(m, [np.array([[p[0] * sw, p[1] * sh] for p in roi_poly_norm], np.int32)], 255)
            fg = cv2.bitwise_and(fg, m)
        fg = cv2.morphologyEx(fg, cv2.MORPH_OPEN, self.k_open)
        fg = cv2.morphologyEx(fg, cv2.MORPH_CLOSE, self.k_close)
        self.mask_small = fg
        self.fg_ratio = float(np.count_nonzero(fg)) / fg.size
        if self.fg_ratio > 0.40:        # perubahan global (kamera goyang / cahaya berubah): abaikan frame ini
            return []
        cnts, _ = cv2.findContours(fg, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        out = []
        lo, hi = min_area_frac * fg.size, max_area_frac * fg.size
        for c in cnts:
            a = cv2.contourArea(c)
            if a < lo or a > hi:
                continue
            x, y, w, h = cv2.boundingRect(c)
            out.append((x / s, y / s, (x + w) / s, (y + h) / s, a / (s * s)))
        out.sort(key=lambda b: -b[4])
        return out[:12]


# --------------------------------------------------------------------------------------------- SSD
class SSDDetector:
    name = "MobileNet-SSD"

    def __init__(self):
        if not PROTOTXT.exists() or not CAFFEMODEL.exists():
            raise FileNotFoundError("Model MobileNet-SSD tidak ditemukan di folder 'models'.")
        self.net = cv2.dnn.readNetFromCaffe(str(PROTOTXT), str(CAFFEMODEL))

    def _run(self, img: np.ndarray, conf: float, wanted: set[str], tag: str = "full") -> list[Detection]:
        h, w = img.shape[:2]
        if h < 8 or w < 8:
            return []
        self.net.setInput(cv2.dnn.blobFromImage(img, 0.007843, (300, 300), 127.5))
        out = self.net.forward()
        res = []
        for i in range(out.shape[2]):
            c = float(out[0, 0, i, 2])
            if c < conf:
                continue
            cls = VOC_TO_CLASS.get(int(out[0, 0, i, 1]))
            if cls is None or cls not in wanted:
                continue
            x1, y1, x2, y2 = out[0, 0, i, 3:7] * np.array([w, h, w, h])
            x1, y1, x2, y2 = max(0.0, x1), max(0.0, y1), min(w - 1.0, x2), min(h - 1.0, y2)
            if x2 > x1 + 2 and y2 > y1 + 2:
                res.append(Detection(x1, y1, x2, y2, c, cls, tag))
        return res

    def _crop(self, frame, rect, conf, wanted, tag, scale_up=True):
        x1, y1, x2, y2 = [int(v) for v in rect]
        crop = frame[y1:y2, x1:x2]
        if crop.size == 0:
            return []
        return [Detection(d.x1 + x1, d.y1 + y1, d.x2 + x1, d.y2 + y1, d.conf, d.cls, tag) for d in self._run(crop, conf, wanted, tag)]

    def detect(self, frame, conf, wanted, roi_rect=None, min_box=12, quality=QUALITY_BALANCED, blobs=None, allow_other=True):
        H, W = frame.shape[:2]
        want = set(wanted) | {"person"}
        dets = self._run(frame, conf, want, "full")

        if roi_rect is not None and quality >= QUALITY_BALANCED:
            x1, y1, x2, y2 = roi_rect
            rw, rh = x2 - x1, y2 - y1
            if rw * rh < 0.8 * W * H and rw > 40 and rh > 40:
                if quality == QUALITY_THOROUGH:      # ubin persegi dengan tumpang tindih 25%
                    side = int(min(rh, max(rw * 0.5, rh)))
                    side = max(side, 96)
                    step = max(1, int(side * 0.75))
                    xs = list(range(int(x1), max(int(x1) + 1, int(x2 - side) + step), step))
                    for tx in xs[:6]:
                        tx2 = min(int(x2), tx + side)
                        dets += self._crop(frame, (max(0, tx2 - side), y1, tx2, min(H, y1 + side)), conf, want, "tile")
                else:
                    dets += self._crop(frame, roi_rect, conf, want, "roi")

        people = [d for d in dets if d.cls == "person"]
        dets = nms([d for d in dets if d.cls != "person" and d.cls in wanted and d.w >= min_box and d.h >= min_box] , 0.5)

        extra_people = list(people)
        if blobs:
            for b in blobs[:6]:
                if covered(b[:4], dets, 0.6):
                    continue
                bw, bh = b[2] - b[0], b[3] - b[1]
                side = max(bw, bh) * 1.9
                side = max(side, 110.0)
                cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
                rect = (max(0, cx - side / 2), max(0, cy - side / 2), min(W, cx + side / 2), min(H, cy + side / 2))
                found = self._crop(frame, rect, max(0.25, conf * 0.8), want, "motion")
                for d in found:
                    dcx, dcy = (d.x1 + d.x2) / 2, (d.y1 + d.y2) / 2
                    if b[0] - bw * 0.3 <= dcx <= b[2] + bw * 0.3 and b[1] - bh * 0.3 <= dcy <= b[3] + bh * 0.3:
                        (extra_people if d.cls == "person" else dets).append(d)
            dets = nms([d for d in dets if d.cls != "person" and d.w >= min_box and d.h >= min_box], 0.5)

            if allow_other:
                for b in blobs[:6]:
                    bw, bh = b[2] - b[0], b[3] - b[1]
                    if bw < min_box * 1.5 or bh < min_box or not (0.35 <= bw / max(bh, 1) <= 4.5):
                        continue
                    if covered(b[:4], dets, 0.4) or covered(b[:4], extra_people, 0.4):
                        continue
                    dets.append(Detection(b[0], b[1], b[2], b[3], 0.30, "other", "motion"))
        return dets


# --------------------------------------------------------------------------------------------- YOLO (opsional)
class YOLODetector:
    name = "YOLO"
    MAP = {"bicycle": "bicycle", "car": "car", "motorcycle": "motorbike", "bus": "bus", "truck": "truck"}

    def __init__(self, weights: str = "yolov8n.pt"):
        try:
            from ultralytics import YOLO
        except ImportError as exc:
            raise RuntimeError("Detektor YOLO membutuhkan paket 'ultralytics' (lihat README).") from exc
        self.model = YOLO(weights)
        self.name = f"YOLO ({weights})"

    def detect(self, frame, conf, wanted, roi_rect=None, min_box=12, quality=QUALITY_BALANCED, blobs=None, allow_other=True):
        imgsz = {QUALITY_FAST: 480, QUALITY_BALANCED: 640, QUALITY_THOROUGH: 960}.get(quality, 640)
        r = self.model.predict(frame, conf=conf, verbose=False, imgsz=imgsz)[0]
        res = []
        for b in r.boxes:
            cls = self.MAP.get(r.names.get(int(b.cls[0]), ""))
            if cls is None or cls not in wanted:
                continue
            x1, y1, x2, y2 = [float(v) for v in b.xyxy[0]]
            if x2 - x1 >= min_box and y2 - y1 >= min_box:
                res.append(Detection(x1, y1, x2, y2, float(b.conf[0]), cls, "yolo"))
        return nms(res, 0.5)


def create_detector(kind: str, yolo_model: str = "yolov8n.pt"):
    return YOLODetector(yolo_model) if kind == "yolo" else SSDDetector()
