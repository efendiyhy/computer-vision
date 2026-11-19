"""Perekam video: menulis video yang sama seperti di layar (lengkap dengan watermark) ke berkas MP4 di data/recordings.

Penulis memakai ffmpeg (H.264, bisa diputar di browser) bila ada; bila tidak, OpenCV (MP4V, cukup untuk diunduh).
Frame diambil dengan jam dinding sehingga durasi video sama dengan waktu nyata walau frame sumber tidak rata.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

NAME_RE = re.compile(r"^rec_\d{8}_\d{6}(_\d+)?\.mp4$")


def _even(img: np.ndarray) -> np.ndarray:
    h, w = img.shape[:2]
    return img[: h - h % 2, : w - w % 2] if (h % 2 or w % 2) else img


class _FfmpegWriter:
    name = "H.264 (ffmpeg)"
    playable = True

    def __init__(self, path: Path, w: int, h: int, fps: float):
        self.p = subprocess.Popen(
            ["ffmpeg", "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{w}x{h}", "-r", f"{fps:g}", "-i", "-",
             "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "26", "-pix_fmt", "yuv420p",
             "-movflags", "frag_keyframe+empty_moov+default_base_moof", str(path)],
            stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def write(self, img):
        try:
            self.p.stdin.write(img.tobytes())
        except (BrokenPipeError, OSError, ValueError):
            raise RuntimeError("ffmpeg berhenti")

    def close(self):
        try:
            self.p.stdin.close()
        except Exception:
            pass
        try:
            self.p.wait(timeout=20)
        except Exception:
            self.p.kill()


class _CvWriter:
    name = "MP4V (OpenCV)"
    playable = False

    def __init__(self, path: Path, w: int, h: int, fps: float):
        self.w = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))
        if not self.w.isOpened():
            raise RuntimeError("Penulis video OpenCV tidak bisa dibuka")

    def write(self, img):
        self.w.write(img)

    def close(self):
        self.w.release()


class Recorder:
    def __init__(self, directory: Path, get_frame, cfg):
        self.dir = Path(directory)
        self.get_frame = get_frame
        self.cfg = cfg
        self._lock = threading.RLock()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self.state = {"recording": False, "name": None, "since": None, "bytes": 0, "encoder": None, "playable": False, "message": "", "segments": 0}
        self._path: Path | None = None

    # ------------------------------------------------------------ kontrol
    def start(self, overlay: bool = True) -> dict:
        with self._lock:
            if self.state["recording"]:
                return self.status()
            self.dir.mkdir(parents=True, exist_ok=True)
            if shutil.disk_usage(self.dir).free < self.cfg["record_min_free_mb"] * 1048576:
                self.state["message"] = "Ruang disk hampir penuh; rekaman tidak dimulai."
                return self.status()
            self._stop.clear()
            self.state.update(recording=True, since=time.time(), message="", segments=0, bytes=0)
            self._thread = threading.Thread(target=self._run, args=(overlay,), daemon=True, name="recorder")
            self._thread.start()
        return self.status()

    def stop(self) -> dict:
        t = None
        with self._lock:
            if not self.state["recording"]:
                return self.status()
            self._stop.set()
            t = self._thread
        if t:
            t.join(timeout=30)
        return self.status()

    def status(self) -> dict:
        with self._lock:
            s = dict(self.state)
        if s["recording"] and self._path and self._path.exists():
            s["bytes"] = self._path.stat().st_size
        s["seconds"] = int(time.time() - s["since"]) if s["recording"] and s["since"] else 0
        try:
            s["free_mb"] = int(shutil.disk_usage(self.dir if self.dir.exists() else self.dir.parent).free / 1048576)
        except OSError:
            s["free_mb"] = None
        return s

    # ------------------------------------------------------------ daftar berkas
    def list(self) -> list[dict]:
        if not self.dir.exists():
            return []
        out = []
        for p in sorted(self.dir.glob("rec_*.mp4"), reverse=True):
            if NAME_RE.match(p.name):
                st = p.stat()
                out.append({"name": p.name, "bytes": st.st_size, "mtime": st.st_mtime, "active": bool(self.state["recording"] and self._path == p)})
        return out

    def path_of(self, name: str) -> Path | None:
        if not NAME_RE.match(name or ""):
            return None
        p = self.dir / name
        return p if p.exists() else None

    def delete(self, name: str) -> bool:
        p = self.path_of(name)
        if not p or (self.state["recording"] and self._path == p):
            return False
        p.unlink()
        return True

    # ------------------------------------------------------------ utas penulis
    def _open(self, w: int, h: int, fps: float):
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = self.dir / f"rec_{stamp}.mp4"
        n = 1
        while path.exists():
            n += 1
            path = self.dir / f"rec_{stamp}_{n}.mp4"
        writer = None
        if shutil.which("ffmpeg"):
            try:
                writer = _FfmpegWriter(path, w, h, fps)
            except Exception:
                writer = None
        if writer is None:
            writer = _CvWriter(path, w, h, fps)
        self._path = path
        with self._lock:
            self.state.update(name=path.name, encoder=writer.name, playable=writer.playable, segments=self.state["segments"] + 1)
        return writer

    def _run(self, overlay: bool):
        writer, size, seg_t0 = None, None, 0.0
        fps = max(2.0, min(30.0, float(self.cfg["record_fps"])))
        seg_len = max(1.0, float(self.cfg["record_segment_min"])) * 60
        min_free = self.cfg["record_min_free_mb"] * 1048576
        nxt, n = time.time(), 0
        try:
            while not self._stop.is_set():
                img = self.get_frame(overlay)
                if img is None:
                    time.sleep(0.2)
                    continue
                img = _even(img).copy()
                h, w = img.shape[:2]
                if size is not None and (w, h) != size:       # ukuran frame berubah (ganti sumber): mulai berkas baru
                    writer.close(); writer = None
                if writer is None:
                    size = (w, h)
                    writer = self._open(w, h, fps)
                    seg_t0 = time.time()
                cv2.putText(img, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), (8, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 3, cv2.LINE_AA)
                cv2.putText(img, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), (8, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
                writer.write(img)
                n += 1
                nxt += 1.0 / fps
                if time.time() - seg_t0 >= seg_len:           # potong per segmen supaya berkas tidak terlalu besar
                    writer.close(); writer = None
                if n % int(fps * 5) == 0 and shutil.disk_usage(self.dir).free < min_free:
                    with self._lock:
                        self.state["message"] = "Rekaman dihentikan: ruang disk hampir penuh."
                    break
                delay = nxt - time.time()
                if delay > 0:
                    time.sleep(delay)
                elif delay < -1.0:
                    nxt = time.time()
        except Exception as exc:
            with self._lock:
                self.state["message"] = f"Rekaman berhenti: {type(exc).__name__}: {exc}"
        finally:
            if writer is not None:
                writer.close()
            with self._lock:
                self.state.update(recording=False)
