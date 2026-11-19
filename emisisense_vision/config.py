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
    "frame_width": 800,           # lebar frame yang diproses & ditampilkan (lebih kecil = lebih ringan)
    "detector": "ssd",            # "ssd" (MobileNet-SSD, bawaan) atau "yolo" (opsional, butuh ultralytics)
    "yolo_model": "yolov8n.pt",
    "confidence": 0.35,
    "quality": 2,                 # presisi deteksi: 1 cepat, 2 seimbang, 3 teliti (deteksi ubin)
    "use_motion": True,           # bantu deteksi dengan pemisah latar (objek bergerak)
    "allow_other": True,          # objek bergerak yang tak dikenali model tetap dihitung sebagai "Lainnya"
    "min_box_px": 12,             # kotak lebih kecil dari ini diabaikan
    "stream_fps": 20,             # batas frame/detik video yang dikirim ke browser
    "jpeg_quality": 72,
    "classes": ["car", "motorbike", "bus", "truck", "bicycle"],
    "location": {"name": "Kota Malang", "lat": -7.9797, "lon": 112.6304},
    # Garis hitung (koordinat ternormalisasi 0..1). SATU garis = SATU arah: hanya kendaraan yang lewat searah
    # panah yang dihitung. Panah menunjuk ke kanan orang yang berjalan dari p1 ke p2 (p1->p2 melintang kiri ke kanan
    # layar = panah ke bawah). Jalan dua arah memakai dua garis, satu per arah.
    "lines": [
        {"id": "A", "name": "Garis A", "p1": [0.08, 0.64], "p2": [0.92, 0.64], "dir": "Mendekat", "color": "#ffd400"},
        {"id": "B", "name": "Garis B", "p1": [0.92, 0.56], "p2": [0.08, 0.56], "dir": "Menjauh", "color": "#ff4fa3"},
    ],
    "count_outside": True,        # kendaraan yang jelas bergerak tetapi tidak menyentuh garis mana pun tetap dihitung ("Di luar garis")
    # Zona pengamatan (ROI) - kepadatan dihitung di dalam zona ini, deteksi difokuskan ke sini.
    "roi": [[0.05, 0.30], [0.95, 0.30], [0.95, 0.95], [0.05, 0.95]],
    "calibration": {"m_per_px": None, "ref_px": None, "ref_m": None},
    "speed_limit_kmh": 50,
    "pcu": {"car": 1.0, "bus": 1.2, "truck": 1.2, "motorbike": 0.25, "bicycle": 0.2, "other": 1.0},
    "display": {"boxes": True, "trails": True, "lines": True, "speed": True, "roi": True, "labels": True, "raw": False},
    "log_dir": "data",
    "log_events": True,
}

LINE_COLORS = ["#ffd400", "#ff4fa3", "#7cff4f", "#ff8a00", "#c77dff", "#ffffff"]   # warna garis (zona selalu cyan)
ZONE_COLOR = "#22d3ee"


def normalize_lines(lines: list) -> list:
    """Rapikan daftar garis: satu arah per garis, warna, id unik. Garis lama dua-arah (dir1/dir2) dipecah jadi dua garis."""
    out, used = [], set()

    def uid(base):
        i = str(base or "L")
        while i in used:
            i += "'"
        used.add(i)
        return i
    for ln in lines or []:
        if not isinstance(ln, dict) or "p1" not in ln or "p2" not in ln:
            continue
        legacy2 = ln.get("dir2") if "dir" not in ln else None
        name = ln.get("name") or f"Garis {ln.get('id', len(out) + 1)}"
        base = {"id": uid(ln.get("id")), "name": name, "p1": list(ln["p1"]), "p2": list(ln["p2"]),
                "dir": ln.get("dir") or ln.get("dir1") or "Arah", "color": ln.get("color") or LINE_COLORS[len(out) % len(LINE_COLORS)]}
        out.append(base)
        if legacy2:                              # versi lama menghitung dua arah: pertahankan dengan garis kebalikan
            out.append({"id": uid(f"{ln.get('id', 'L')}2"), "name": f"{name} (balik)", "p1": list(ln["p2"]), "p2": list(ln["p1"]),
                        "dir": legacy2, "color": LINE_COLORS[len(out) % len(LINE_COLORS)]})
    return out


CLASS_LABEL = {"car": "Mobil", "motorbike": "Motor", "bus": "Bus", "truck": "Truk", "bicycle": "Sepeda", "other": "Lainnya"}
CLASS_COLOR = {  # BGR untuk OpenCV (palet Okabe-Ito, aman bagi buta warna); hex-nya ada di web/app.js
    "car": (178, 114, 0), "motorbike": (0, 159, 230), "bus": (115, 158, 0),
    "truck": (0, 94, 213), "bicycle": (167, 121, 204), "other": (145, 134, 122),
}


class Config:
    """Konfigurasi aman-thread dengan penyimpanan JSON."""

    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else ROOT / "config.json"
        self._lock = threading.RLock()
        self._data = copy.deepcopy(DEFAULTS)
        self._load()
        self._data["lines"] = normalize_lines(self._data["lines"])

    def _load(self):
        if self.path.exists():
            try:
                saved = json.loads(self.path.read_text(encoding="utf-8"))
                self._merge(self._data, saved)
                if "lines" in saved:
                    self._data["lines"] = saved["lines"]
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
            if "lines" in patch:
                self._data["lines"] = normalize_lines(self._data["lines"])
            if save:
                self.save()
            return copy.deepcopy(self._data)

    def save(self):
        with self._lock:
            try:
                self.path.write_text(json.dumps(self._data, indent=2, ensure_ascii=False), encoding="utf-8")
            except OSError as exc:
                print(f"[config] gagal menyimpan: {exc}")
