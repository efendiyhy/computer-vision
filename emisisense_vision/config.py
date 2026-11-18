"""Konfigurasi aplikasi. Nilai bawaan dapat diubah lewat dashboard (disimpan ke config.json)."""
from __future__ import annotations

import copy
import json
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Sumber CCTV acuan penelitian (jangan dihapus: ini rujukan lokasi pengamatan).
DEFAULT_STREAM_URL = (
    "https://cctvmalang.24hour.id/twentyfourhourid/"
    "proxy.php?id=767576969564466612969572"
)

DEFAULTS: dict = {
    "source": DEFAULT_STREAM_URL,
    "frame_width": 960,
    "detector": "ssd",            # "ssd" (MobileNet-SSD, bawaan) atau "yolo" (opsional, butuh ultralytics)
    "yolo_model": "yolov8n.pt",
    "confidence": 0.40,
    "detect_every": 2,            # deteksi setiap N frame (frame lain: prediksi tracker)
    "min_box_px": 14,             # kotak lebih kecil dari ini diabaikan
    "classes": ["car", "motorbike", "bus", "truck", "bicycle"],
    "location": {"name": "Kota Malang", "lat": -7.9797, "lon": 112.6304},
    # Garis hitung (koordinat ternormalisasi 0..1). Arah 1 = sisi kiri vektor p1->p2.
    "lines": [
        {"id": "A", "name": "Garis A", "p1": [0.08, 0.62], "p2": [0.92, 0.62],
         "dir1": "Mendekat", "dir2": "Menjauh"},
    ],
    # Zona pengamatan (ROI) - kepadatan dihitung di dalam zona ini, deteksi difokuskan ke sini.
    "roi": [[0.05, 0.30], [0.95, 0.30], [0.95, 0.95], [0.05, 0.95]],
    "calibration": {"m_per_px": None, "ref_px": None, "ref_m": None},
    "speed_limit_kmh": 50,
    "pcu": {"car": 1.0, "bus": 1.2, "truck": 1.2, "motorbike": 0.25, "bicycle": 0.2},
    "display": {"boxes": True, "trails": True, "lines": True, "speed": True, "roi": True, "labels": True},
    "log_dir": "data",
    "log_events": True,
}

CLASS_LABEL = {"car": "Mobil", "motorbike": "Motor", "bus": "Bus", "truck": "Truk", "bicycle": "Sepeda"}
CLASS_COLOR = {  # BGR untuk OpenCV; versi hex di web/app.js
    "car": (246, 173, 55), "motorbike": (60, 200, 255), "bus": (110, 214, 120),
    "truck": (90, 120, 255), "bicycle": (230, 120, 220),
}


class Config:
    """Konfigurasi aman-thread dengan penyimpanan JSON."""

    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else ROOT / "config.json"
        self._lock = threading.RLock()
        self._data = copy.deepcopy(DEFAULTS)
        self._load()

    def _load(self):
        if self.path.exists():
            try:
                saved = json.loads(self.path.read_text(encoding="utf-8"))
                self._merge(self._data, saved)
            except Exception as exc:  # berkas rusak -> pakai bawaan
                print(f"[config] gagal membaca {self.path}: {exc}")

    @staticmethod
    def _merge(dst: dict, src: dict):
        for k, v in src.items():
            if k in dst and isinstance(dst[k], dict) and isinstance(v, dict):
                Config._merge(dst[k], v)
            else:
                dst[k] = v

    def get(self) -> dict:
        with self._lock:
            return copy.deepcopy(self._data)

    def __getitem__(self, key):
        with self._lock:
            return copy.deepcopy(self._data[key])

    def update(self, patch: dict, save: bool = True) -> dict:
        with self._lock:
            self._merge(self._data, patch)
            # daftar (lines, roi, classes) diganti utuh, bukan digabung
            for k in ("lines", "roi", "classes"):
                if k in patch:
                    self._data[k] = copy.deepcopy(patch[k])
            if save:
                self.save()
            return copy.deepcopy(self._data)

    def save(self):
        with self._lock:
            try:
                self.path.write_text(json.dumps(self._data, indent=2, ensure_ascii=False), encoding="utf-8")
            except OSError as exc:
                print(f"[config] gagal menyimpan: {exc}")
