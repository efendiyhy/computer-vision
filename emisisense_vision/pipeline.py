"""Pipeline video: pengambil frame -> deteksi -> pelacakan -> analitik -> gambar overlay -> JPEG (MJPEG)."""
from __future__ import annotations

import threading
import time
from pathlib import Path

import cv2
import numpy as np

from .analytics import Analytics
from .config import CLASS_COLOR, CLASS_LABEL, Config
from .detector import Detection, create_detector
from .simulator import TrafficSimulator
from .tracker import Tracker


def is_file_source(src: str) -> bool:
    return not str(src).lower().startswith(("http://", "https://", "rtsp://", "rtmp://")) and not str(src).isdigit()


class Pipeline:
    def __init__(self, cfg: Config, analytics: Analytics, demo: bool = False):
        self.cfg, self.an, self.demo = cfg, analytics, demo
        self.tracker = Tracker()
        self.detector = None
        self._det_key = None
        self._cond = threading.Condition()
        self._jpeg: bytes | None = None
        self._seq = 0
        self._stop = threading.Event()
        self._reload = threading.Event()
        self._latest = None          # (frame, media_time)
        self._latest_lock = threading.Lock()
        self._frame_id = 0
        self.status = {"state": "mulai", "message": "Menyiapkan…", "fps": 0.0, "latency_ms": 0.0, "frame": None,
                       "detector": "-", "source": cfg["source"], "demo": demo}
        self._threads = [threading.Thread(target=self._grab_loop, daemon=True, name="grab"),
                         threading.Thread(target=self._proc_loop, daemon=True, name="proc")]
        self.paused = False
        self.snap_request = False

    # ------------------------------------------------------------ kontrol
    def start(self):
        for t in self._threads:
            t.start()

    def stop(self):
        self._stop.set()

    def reload_source(self):
        self._reload.set()
        self.tracker.reset()

    def _set(self, **kw):
        self.status.update(kw)

    def jpeg(self, last_seq: int, timeout: float = 5.0):
        with self._cond:
            if self._seq == last_seq:
                self._cond.wait(timeout)
            return self._seq, self._jpeg

    # ------------------------------------------------------------ pengambil frame
    def _grab_loop(self):
        if self.demo:
            return
        backoff = 1.0
        while not self._stop.is_set():
            src = self.cfg["source"]
            self._reload.clear()
            self._set(source=src, state="menghubungkan", message="Menghubungkan ke sumber video…")
            cap = cv2.VideoCapture(int(src) if str(src).isdigit() else src)
            if not cap.isOpened():
                self._set(state="error", message="Tidak dapat membuka sumber video. Coba lagi otomatis…")
                cap.release()
                self._stop.wait(backoff); backoff = min(backoff * 1.7, 15)
                continue
            backoff = 1.0
            fps = cap.get(cv2.CAP_PROP_FPS) or 0
            is_file = is_file_source(src)
            fps = fps if 1 < fps < 120 else 25.0
            n, t0, fails = 0, time.time(), 0
            while not self._stop.is_set() and not self._reload.is_set():
                if self.paused:
                    time.sleep(0.1); continue
                ok, frame = cap.read()
                if not ok:
                    fails += 1
                    if is_file:           # berkas: ulangi dari awal
                        cap.set(cv2.CAP_PROP_POS_FRAMES, 0); n, t0 = 0, time.time(); continue
                    if fails > 25:
                        break
                    time.sleep(0.2); continue
                fails = 0
                n += 1
                mt = n / fps if is_file else time.time()
                with self._latest_lock:
                    self._latest = (frame, mt)
                    self._frame_id += 1
                if is_file:               # tahan sesuai waktu video
                    wait = t0 + n / fps - time.time()
                    if wait > 0:
                        time.sleep(wait)
            cap.release()
            if not self._stop.is_set() and not self._reload.is_set():
                self._set(state="error", message="Koneksi terputus. Menyambung ulang…")
                self._stop.wait(2.0)

    # ------------------------------------------------------------ pemrosesan
    def _ensure_detector(self, cfg):
        key = (cfg["detector"], cfg["yolo_model"])
        if key != self._det_key:
            try:
                self.detector = create_detector(*key)
            except Exception as exc:
                self._set(message=f"Detektor {key[0]} gagal ({exc}); memakai MobileNet-SSD")
                self.detector = create_detector("ssd")
            self._det_key = key
            self._set(detector=self.detector.name)

    def _proc_loop(self):
        sim = TrafficSimulator() if self.demo else None
        last_id, fcount = 0, 0
        fps_t, fps_n = time.time(), 0
        last_dets: list[Detection] = []
        last_wall = time.time()
        sim_t = 0.0
        if self.demo:
            self._set(state="live", message="Mode demo: lalu lintas simulasi", detector="Simulator (demo)")
        while not self._stop.is_set():
            cfg = self.cfg.get()
            if self.paused:
                time.sleep(0.1); continue
            t_loop = time.time()
            if sim:
                dt = 1 / 20
                sim.step(dt); sim_t += dt
                frame, dets = sim.frame_and_dets()
                tracks = self.tracker.step(dets if fcount % 2 == 0 else None, sim_t, float(np.hypot(*frame.shape[1::-1])))
                mt, W, H = sim_t, frame.shape[1], frame.shape[0]
                # simulasi memakai waktu dinding agar log/menit konsisten
                self.an.update(tracks, sim_t, (W, H))
                last_dets = dets
                wait = dt - (time.time() - t_loop)
                if wait > 0:
                    time.sleep(wait)
            else:
                with self._latest_lock:
                    item, fid = self._latest, self._frame_id
                if item is None or fid == last_id:
                    time.sleep(0.01); continue
                last_id = fid
                frame, mt = item
                self._ensure_detector(cfg)
                fw = cfg["frame_width"]
                h0, w0 = frame.shape[:2]
                if w0 != fw:
                    frame = cv2.resize(frame, (fw, int(h0 * fw / w0)), interpolation=cv2.INTER_AREA)
                H, W = frame.shape[:2]
                diag = float(np.hypot(W, H))
                dets = None
                if fcount % max(1, int(cfg["detect_every"])) == 0:
                    roi_pts = np.array([[p[0] * W, p[1] * H] for p in cfg["roi"]])
                    rx1, ry1 = np.clip(roi_pts.min(0) - 10, 0, [W - 1, H - 1]).astype(int)
                    rx2, ry2 = np.clip(roi_pts.max(0) + 10, 0, [W, H]).astype(int)
                    td = time.time()
                    try:
                        dets = self.detector.detect(frame, float(cfg["confidence"]), set(cfg["classes"]),
                                                    (int(rx1), int(ry1), int(rx2), int(ry2)), int(cfg["min_box_px"]))
                    except Exception as exc:
                        self._set(message=f"Kesalahan deteksi: {exc}"); dets = []
                    self.status["latency_ms"] = round((time.time() - td) * 1000, 1)
                    last_dets = dets
                tracks = self.tracker.step(dets, mt, diag)
                self.an.update(tracks, mt, (W, H))
            fcount += 1
            fps_n += 1
            if time.time() - fps_t >= 1.0:
                self.status["fps"] = round(fps_n / (time.time() - fps_t), 1)
                fps_t, fps_n = time.time(), 0
            if not self.demo:
                self._set(state="live", message="Terhubung", frame=[W, H])
            else:
                self._set(frame=[W, H])
            out = self._draw(frame, tracks, cfg)
            ok, buf = cv2.imencode(".jpg", out, [cv2.IMWRITE_JPEG_QUALITY, 80])
            if ok:
                with self._cond:
                    self._jpeg = buf.tobytes(); self._seq += 1
                    self._cond.notify_all()

    # ------------------------------------------------------------ gambar overlay
    def _draw(self, frame: np.ndarray, tracks, cfg) -> np.ndarray:
        img = frame.copy()
        H, W = img.shape[:2]
        d = cfg["display"]
        if d["roi"]:
            roi = np.array([[p[0] * W, p[1] * H] for p in cfg["roi"]], np.int32)
            ov = img.copy()
            cv2.fillPoly(ov, [roi], (90, 200, 120))
            img = cv2.addWeighted(ov, 0.10, img, 0.90, 0)
            cv2.polylines(img, [roi], True, (110, 220, 140), 1, cv2.LINE_AA)
        if d["lines"]:
            for ln in cfg["lines"]:
                a = (int(ln["p1"][0] * W), int(ln["p1"][1] * H)); b = (int(ln["p2"][0] * W), int(ln["p2"][1] * H))
                cv2.line(img, a, b, (40, 180, 255), 2, cv2.LINE_AA)
                cv2.putText(img, ln["name"], (a[0] + 4, a[1] - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (40, 180, 255), 1, cv2.LINE_AA)
        for tr in tracks:
            if not tr.confirmed or tr.miss > 4:
                continue
            col = CLASS_COLOR.get(tr.cls, (200, 200, 200))
            x1, y1, x2, y2 = [int(v) for v in tr.box]
            if d["trails"] and len(tr.trail) > 2:
                pts = np.array([[p[1], p[2]] for p in list(tr.trail)[-25:]], np.int32)
                cv2.polylines(img, [pts], False, col, 2, cv2.LINE_AA)
            if d["boxes"]:
                thick = 2 if tr.id in self.an.counted_ids else 1
                cv2.rectangle(img, (x1, y1), (x2, y2), col, thick, cv2.LINE_AA)
            if d["labels"]:
                txt = f"{CLASS_LABEL.get(tr.cls, tr.cls)} #{tr.id}"
                if d["speed"] and tr.speed_kmh is not None:
                    txt += f" {tr.speed_kmh:.0f} km/j"
                (tw, th), _ = cv2.getTextSize(txt, cv2.FONT_HERSHEY_SIMPLEX, 0.42, 1)
                ty = max(th + 4, y1)
                cv2.rectangle(img, (x1, ty - th - 5), (x1 + tw + 6, ty), col, -1)
                cv2.putText(img, txt, (x1 + 3, ty - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (15, 15, 15), 1, cv2.LINE_AA)
        return img
