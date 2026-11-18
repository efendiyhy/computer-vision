"""Detektor kendaraan.

* SSDDetector  - MobileNet-SSD (Caffe, OpenCV DNN), bawaan, tanpa dependensi tambahan.
               Kelas VOC: car, bus, motorbike, bicycle. Deteksi dijalankan pada seluruh frame
               DAN pada potongan zona pengamatan (ROI) yang diperbesar, sehingga kendaraan kecil/jauh
               lebih mudah terdeteksi; hasilnya digabung dengan NMS.
* YOLODetector - opsional (pip install ultralytics). Menambah kelas truk dan lebih akurat.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
PROTOTXT = ROOT / "models" / "deploy.prototxt"
CAFFEMODEL = ROOT / "models" / "mobilenet_iter_73000.caffemodel"

VOC_TO_CLASS = {2: "bicycle", 6: "bus", 7: "car", 14: "motorbike"}
COCO_TO_CLASS = {1: "bicycle", 2: "car", 3: "motorbike", 5: "bus", 7: "truck"}


@dataclass
class Detection:
    x1: float
    y1: float
    x2: float
    y2: float
    conf: float
    cls: str

    @property
    def w(self): return self.x2 - self.x1

    @property
    def h(self): return self.y2 - self.y1


def _nms(dets: list[Detection], iou_thr: float = 0.45) -> list[Detection]:
    if len(dets) < 2:
        return dets
    boxes = [[d.x1, d.y1, d.w, d.h] for d in dets]
    scores = [d.conf for d in dets]
    keep = cv2.dnn.NMSBoxes(boxes, scores, 0.0, iou_thr)
    return [dets[int(i)] for i in np.array(keep).flatten()]


class SSDDetector:
    name = "MobileNet-SSD"

    def __init__(self):
        if not PROTOTXT.exists() or not CAFFEMODEL.exists():
            raise FileNotFoundError("Model MobileNet-SSD tidak ditemukan di folder 'models'.")
        self.net = cv2.dnn.readNetFromCaffe(str(PROTOTXT), str(CAFFEMODEL))

    def _run(self, img: np.ndarray, conf: float, wanted: set[str]) -> list[Detection]:
        h, w = img.shape[:2]
        blob = cv2.dnn.blobFromImage(img, 0.007843, (300, 300), 127.5)
        self.net.setInput(blob)
        out = self.net.forward()
        res = []
        for i in range(out.shape[2]):
            c = float(out[0, 0, i, 2])
            cls = VOC_TO_CLASS.get(int(out[0, 0, i, 1]))
            if cls is None or cls not in wanted or c < conf:
                continue
            x1, y1, x2, y2 = out[0, 0, i, 3:7] * np.array([w, h, w, h])
            x1, y1 = max(0.0, x1), max(0.0, y1)
            x2, y2 = min(w - 1.0, x2), min(h - 1.0, y2)
            if x2 > x1 and y2 > y1:
                res.append(Detection(x1, y1, x2, y2, c, cls))
        return res

    def detect(self, frame: np.ndarray, conf: float, wanted: set[str],
               roi_rect: tuple[int, int, int, int] | None = None, min_box: int = 14) -> list[Detection]:
        dets = self._run(frame, conf, wanted)
        if roi_rect is not None:
            x1, y1, x2, y2 = roi_rect
            crop = frame[y1:y2, x1:x2]
            # hanya berguna bila zona jauh lebih kecil dari frame
            if crop.size and crop.shape[0] * crop.shape[1] < 0.8 * frame.shape[0] * frame.shape[1]:
                for d in self._run(crop, conf, wanted):
                    dets.append(Detection(d.x1 + x1, d.y1 + y1, d.x2 + x1, d.y2 + y1, d.conf, d.cls))
        dets = [d for d in dets if d.w >= min_box and d.h >= min_box]
        return _nms(dets)


class YOLODetector:
    name = "YOLO"

    def __init__(self, weights: str = "yolov8n.pt"):
        try:
            from ultralytics import YOLO  # impor malas: hanya dibutuhkan bila dipilih
        except ImportError as exc:
            raise RuntimeError("Detektor YOLO membutuhkan paket 'ultralytics' (pip install ultralytics).") from exc
        self.model = YOLO(weights)
        self.name = f"YOLO ({weights})"

    def detect(self, frame, conf, wanted, roi_rect=None, min_box=14):
        r = self.model.predict(frame, conf=conf, verbose=False, imgsz=640)[0]
        res = []
        names = r.names
        for b in r.boxes:
            cid = int(b.cls[0])
            cls = {"bicycle": "bicycle", "car": "car", "motorcycle": "motorbike", "bus": "bus", "truck": "truck"}.get(names.get(cid, ""))
            if cls is None or cls not in wanted:
                continue
            x1, y1, x2, y2 = [float(v) for v in b.xyxy[0]]
            if x2 - x1 >= min_box and y2 - y1 >= min_box:
                res.append(Detection(x1, y1, x2, y2, float(b.conf[0]), cls))
        return _nms(res)


def create_detector(kind: str, yolo_model: str = "yolov8n.pt"):
    if kind == "yolo":
        return YOLODetector(yolo_model)
    return SSDDetector()
