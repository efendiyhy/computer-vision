"""Alur video: tiga utas terpisah supaya video tetap lancar walaupun deteksi lambat.

  grab    membaca sumber (HLS/MJPEG/snapshot/RTSP/berkas) dan menyimpan frame terbaru
  detect  deteksi + deteksi gerak + pelacakan + analitik pada frame terbaru (kecepatan sendiri)
  stream  menggambar overlay pada frame terbaru memakai posisi trek yang diekstrapolasi, lalu mengirim MJPEG
"""
from __future__ import annotations

import threading
import time

import cv2
import numpy as np

from .analytics import Analytics
from .config import CLASS_COLOR, CLASS_LABEL, Config
from .detector import MotionDetector, create_detector
from .reader import SourceError, open_source
from .simulator import TrafficSimulator
from .tracker import Tracker


def _ema(old, new, a=0.2):
    return new if old in (None, 0) else (1 - a) * old + a * new


class Pipeline:
    def __init__(self, cfg: Config, analytics: Analytics, demo: bool = False):
        self.cfg, self.an, self.demo = cfg, analytics, demo
        self.tracker = Tracker()
        self.motion = MotionDetector()
        self.detector = None
        self._det_key = None
        self._stop = threading.Event()
        self._reload = threading.Event()
        self._frame_cv = threading.Condition()
        self._latest = None                 # (frame, ts, seq, extra)
        self._seq = 0
        self._view = {"t": 0.0, "tracks": [], "raw": [], "blobs": []}
        self._view_lock = threading.Lock()
        self._jpeg_cv = threading.Condition()
        self._jpeg, self._jpeg_seq = None, 0
        self.paused = False
        self.t_boot = time.time()
        self.status = {"state": "mulai", "message": "Menyiapkan…", "kind": None, "desc": None, "src_fps": 0.0, "det_fps": 0.0,
                       "det_ms": 0.0, "stream_fps": 0.0, "frame": None, "source_size": None, "detector": "-", "source": cfg["source"],
                       "demo": demo, "raw_dets": 0, "blobs": 0, "tracks": 0, "frames_in": 0, "reconnects": 0, "last_frame_t": 0.0,
                       "paused": False}
        self._threads = [threading.Thread(target=f, daemon=True, name=n)
                         for f, n in ((self._grab_loop, "grab"), (self._detect_loop, "detect"), (self._stream_loop, "stream"))]

    # ------------------------------------------------------------ kontrol
    def start(self):
        for t in self._threads:
            t.start()

    def stop(self):
        self._stop.set()

    def reload_source(self):
        self.tracker.reset()
        self.motion.reset()
        self._reload.set()
        with self._frame_cv:
            self._frame_cv.notify_all()

    def set_paused(self, v: bool):
        self.paused = v
        self.status["paused"] = v

    def get_status(self) -> dict:
        s = dict(self.status)
        s["uptime_s"] = int(time.time() - self.t_boot)
        s["last_frame_age"] = round(time.time() - s["last_frame_t"], 1) if s["last_frame_t"] else None
        return s

    def jpeg(self, last_seq: int, timeout: float = 5.0):
        with self._jpeg_cv:
            if self._jpeg_seq == last_seq:
                self._jpeg_cv.wait(timeout)
            return self._jpeg_seq, self._jpeg

    # ------------------------------------------------------------ utas grab
    def _publish(self, frame, ts, extra=None):
        with self._frame_cv:
            self._seq += 1
            self._latest = (frame, ts, self._seq, extra)
            self._frame_cv.notify_all()

    def _resize(self, frame):
        fw = int(self.cfg["frame_width"])
        h0, w0 = frame.shape[:2]
        self.status["source_size"] = [w0, h0]
        if w0 > fw:
            return cv2.resize(frame, (fw, max(2, int(h0 * fw / w0))), interpolation=cv2.INTER_AREA)
        return frame

    def _grab_loop(self):
        if self.demo:
            sim = TrafficSimulator()
            self.status.update(state="live", message="Mode demo: lalu lintas simulasi", detector="Simulator (demo)", kind="demo", desc="Simulasi")
            t = 0.0
            last = time.time()
            while not self._stop.is_set():
                if self.paused:
                    time.sleep(0.1); last = time.time(); continue
                dt = 1 / 15
                sim.step(dt); t += dt
                frame, dets = sim.frame_and_dets()
                self._publish(frame, t, dets)
                self.status.update(frames_in=self.status["frames_in"] + 1, last_frame_t=time.time(), src_fps=15.0, frame=[frame.shape[1], frame.shape[0]],
                                   source_size=[frame.shape[1], frame.shape[0]])
                wait = dt - (time.time() - last)
                if wait > 0:
                    time.sleep(wait)
                last = time.time()
            return
        backoff = 1.0
        while not self._stop.is_set():
            src = self.cfg["source"]
            self._reload.clear()
            self.status.update(source=src, state="menghubungkan", message="Menghubungkan ke sumber video…", kind=None, desc=None, src_fps=0.0)
            try:
                reader = open_source(src)
            except SourceError as exc:
                self.status.update(state="error", message=str(exc))
                self._stop.wait(backoff); backoff = min(backoff * 1.7, 20)
                continue
            except Exception as exc:
                self.status.update(state="error", message=f"{type(exc).__name__}: {exc}")
                self._stop.wait(backoff); backoff = min(backoff * 1.7, 20)
                continue
            backoff = 1.0
            self.status.update(kind=reader.kind, desc=reader.desc, message="Terhubung, menunggu frame…")
            fails, win, first = 0, [], True
            while not self._stop.is_set() and not self._reload.is_set():
                if self.paused:
                    time.sleep(0.1); continue
                ok, frame, ts = reader.read()
                if not ok:
                    fails += 1
                    if fails > 30:
                        break
                    time.sleep(0.05)
                    continue
                fails = 0
                now = time.time()
                win.append((now, getattr(reader, "parsed", 0) or (win[-1][1] + 1 if win else 0)))
                while len(win) > 2 and now - win[0][0] > 3.0:
                    win.pop(0)
                if len(win) >= 3 and win[-1][0] - win[0][0] >= 0.8:
                    self.status["src_fps"] = round((win[-1][1] - win[0][1]) / (win[-1][0] - win[0][0]), 1)
                frame = self._resize(frame)
                self._publish(frame, ts)
                self.status.update(frames_in=self.status["frames_in"] + 1, last_frame_t=now, frame=[frame.shape[1], frame.shape[0]],
                                   state="live", message="Terhubung")
            reader.close()
            if not self._stop.is_set() and not self._reload.is_set():
                self.status.update(state="error", message="Koneksi terputus. Menyambung ulang…", reconnects=self.status["reconnects"] + 1)
                self._stop.wait(2.0)

    # ------------------------------------------------------------ utas deteksi
    def _ensure_detector(self, cfg):
        key = (cfg["detector"], cfg["yolo_model"])
        if key != self._det_key:
            try:
                self.detector = create_detector(*key)
            except Exception as exc:
                self.status["message"] = f"Detektor {key[0]} gagal ({exc}); memakai MobileNet-SSD"
                self.detector = create_detector("ssd")
            self._det_key = key
            self.status["detector"] = self.detector.name

    def _detect_loop(self):
        last_seq = 0
        while not self._stop.is_set():
            with self._frame_cv:
                if self._latest is None or self._latest[2] == last_seq:
                    self._frame_cv.wait(0.5)
                item = self._latest
            if item is None or item[2] == last_seq or self.paused:
                time.sleep(0.01)
                continue
            frame, ts, last_seq, extra = item
            cfg = self.cfg.get()
            H, W = frame.shape[:2]
            t0 = time.time()
            blobs: list = []
            try:
                if self.demo:
                    rng = np.random.default_rng(last_seq)
                    from .detector import Detection
                    dets = [Detection(d.x1 + rng.normal(0, 1.5), d.y1 + rng.normal(0, 1.5), d.x2 + rng.normal(0, 1.5), d.y2 + rng.normal(0, 1.5), d.conf, d.cls) for d in extra]
                else:
                    self._ensure_detector(cfg)
                    if cfg["use_motion"] and getattr(self.detector, "name", "").startswith("MobileNet"):
                        blobs = self.motion.blobs(frame, cfg["roi"])
                    roi_pts = np.array([[p[0] * W, p[1] * H] for p in cfg["roi"]])
                    rx1, ry1 = np.clip(roi_pts.min(0) - 8, 0, [W - 1, H - 1]).astype(int)
                    rx2, ry2 = np.clip(roi_pts.max(0) + 8, 0, [W, H]).astype(int)
                    dets = self.detector.detect(frame, float(cfg["confidence"]), set(cfg["classes"]), (int(rx1), int(ry1), int(rx2), int(ry2)),
                                                int(cfg["min_box_px"]), int(cfg["quality"]), blobs, bool(cfg["allow_other"]))
            except Exception as exc:
                self.status["message"] = f"Kesalahan deteksi: {type(exc).__name__}: {exc}"
                dets = []
            tracks = self.tracker.step(dets, ts)
            self.an.update(tracks, self.tracker.dead, ts, (W, H))
            ms = (time.time() - t0) * 1000
            view_tracks = []
            for tr in tracks:
                if not tr.confirmed:
                    continue
                view_tracks.append({"id": tr.id, "cls": tr.cls, "cx": float(tr.x[0]), "cy": float(tr.x[1]), "w": float(tr.x[2]), "h": float(tr.x[3]),
                                    "vx": float(tr.x[4]), "vy": float(tr.x[5]), "speed": tr.speed_kmh, "t_last": tr.last_t,
                                    "trail": [(p[1], p[2]) for p in list(tr.trail)[-14:]], "counted": tr.id in self.an.counted_ids,
                                    "stale": (ts - tr.last_t) > 1.2})
            with self._view_lock:
                self._view = {"t": ts, "tracks": view_tracks, "raw": [(d.x1, d.y1, d.x2, d.y2, d.cls) for d in dets], "blobs": [b[:4] for b in blobs]}
            self.status.update(det_ms=round(_ema(self.status["det_ms"], ms), 1), det_fps=round(_ema(self.status["det_fps"], 1000.0 / max(ms, 1.0), 0.15), 1),
                               raw_dets=len(dets), blobs=len(blobs), tracks=len(view_tracks))

    # ------------------------------------------------------------ utas aliran
    def _stream_loop(self):
        last_seq, last_emit, fps_t, fps_n = 0, 0.0, time.time(), 0
        while not self._stop.is_set():
            with self._frame_cv:
                if self._latest is None or self._latest[2] == last_seq:
                    self._frame_cv.wait(0.5)
                item = self._latest
            if item is None or item[2] == last_seq:
                continue
            cfg = self.cfg.get()
            min_dt = 1.0 / max(2, int(cfg["stream_fps"]))
            wait = min_dt - (time.time() - last_emit)
            if wait > 0:
                time.sleep(wait)
                with self._frame_cv:
                    item = self._latest            # pakai frame yang paling baru setelah menunggu
            frame, ts, last_seq, _ = item
            img = self._draw(frame, ts, cfg)
            ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, int(cfg["jpeg_quality"])])
            last_emit = time.time()
            if ok:
                with self._jpeg_cv:
                    self._jpeg, self._jpeg_seq = buf.tobytes(), self._jpeg_seq + 1
                    self._jpeg_cv.notify_all()
                fps_n += 1
                if last_emit - fps_t >= 1.0:
                    self.status["stream_fps"] = round(fps_n / (last_emit - fps_t), 1)
                    fps_t, fps_n = last_emit, 0

    def _draw(self, frame: np.ndarray, ts: float, cfg) -> np.ndarray:
        img = frame.copy()
        H, W = img.shape[:2]
        d = cfg["display"]
        if d["roi"]:
            roi = np.array([[p[0] * W, p[1] * H] for p in cfg["roi"]], np.int32)
            cv2.polylines(img, [roi], True, (90, 200, 255), 1, cv2.LINE_AA)
        if d["lines"]:
            for ln in cfg["lines"]:
                a = (int(ln["p1"][0] * W), int(ln["p1"][1] * H)); b = (int(ln["p2"][0] * W), int(ln["p2"][1] * H))
                cv2.line(img, a, b, (0, 200, 255), 2, cv2.LINE_AA)
                cv2.putText(img, ln["name"], (a[0] + 4, a[1] - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 200, 255), 1, cv2.LINE_AA)
        with self._view_lock:
            view = self._view
        dt = max(0.0, min(ts - view["t"], 1.2))
        if d.get("raw"):
            for x1, y1, x2, y2, cls in view["raw"]:
                cv2.rectangle(img, (int(x1), int(y1)), (int(x2), int(y2)), (200, 200, 200), 1)
        for tr in view["tracks"]:
            if tr["stale"] and (ts - tr["t_last"]) > 1.6:
                continue
            col = CLASS_COLOR.get(tr["cls"], (200, 200, 200))
            cx, cy = tr["cx"] + tr["vx"] * dt, tr["cy"] + tr["vy"] * dt
            x1, y1, x2, y2 = int(cx - tr["w"] / 2), int(cy - tr["h"] / 2), int(cx + tr["w"] / 2), int(cy + tr["h"] / 2)
            if d["trails"] and len(tr["trail"]) > 1:
                cv2.polylines(img, [np.array(tr["trail"], np.int32)], False, col, 2, cv2.LINE_AA)
            if d["boxes"]:
                cv2.rectangle(img, (x1, y1), (x2, y2), col, 2 if tr["counted"] else 1, cv2.LINE_AA)
            if d["labels"]:
                txt = f"{CLASS_LABEL.get(tr['cls'], tr['cls'])} #{tr['id']}"
                if d["speed"] and tr["speed"] is not None:
                    txt += f" {tr['speed']:.0f} km/j"
                (tw, th), _ = cv2.getTextSize(txt, cv2.FONT_HERSHEY_SIMPLEX, 0.42, 1)
                ty = max(th + 5, y1)
                cv2.rectangle(img, (x1, ty - th - 6), (x1 + tw + 6, ty), col, -1)
                cv2.putText(img, txt, (x1 + 3, ty - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (255, 255, 255), 1, cv2.LINE_AA)
        return img
