"""Pembaca sumber video yang mengenali jenis sumbernya.

Jenis yang didukung: kamera USB (angka), berkas video, RTSP, HLS (.m3u8), aliran MJPEG (multipart),
gambar JPEG yang diperbarui (snapshot), serta halaman web yang menautkan salah satunya.
Untuk URL http(s) jenis ditentukan dari isi respons (bukan dari akhiran URL), karena proxy CCTV sering
memakai satu alamat ``proxy.php?id=...`` untuk semua jenis.
"""
from __future__ import annotations

import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from . import resolver

import cv2
import numpy as np

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
_env_lock = threading.Lock()


class SourceError(Exception):
    pass


def is_remote(src: str) -> bool:
    return str(src).lower().startswith(("http://", "https://", "rtsp://", "rtmp://", "rtsps://", "udp://", "tcp://"))


def _headers(url: str) -> dict:
    p = urllib.parse.urlparse(url)
    return {"User-Agent": UA, "Referer": f"{p.scheme}://{p.netloc}/", "Accept": "*/*"}


def _ffmpeg_options(url: str) -> str:
    h = _headers(url)
    return ("rtsp_transport;tcp|user_agent;%s|headers;Referer: %s\r\n|reconnect;1|reconnect_streamed;1|reconnect_delay_max;5"
            "|timeout;10000000|rw_timeout;10000000" % (UA, h["Referer"]))


def _open_cv(target, remote: bool):
    with _env_lock:
        if remote and isinstance(target, str) and target.lower().startswith("http"):
            os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = _ffmpeg_options(target)
        elif remote:
            os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp|timeout;10000000"
        else:
            os.environ.pop("OPENCV_FFMPEG_CAPTURE_OPTIONS", None)
        try:
            params = [cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 12000, cv2.CAP_PROP_READ_TIMEOUT_MSEC, 12000] if remote else []
            cap = cv2.VideoCapture(target, cv2.CAP_FFMPEG, params) if isinstance(target, str) else cv2.VideoCapture(target)
        except (TypeError, cv2.error):
            cap = cv2.VideoCapture(target)
    try:
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    except Exception:
        pass
    return cap


# ------------------------------------------------------------------------------------------ pembaca
class CvReader:
    """Kamera, berkas, RTSP, HLS, atau video HTTP lewat FFmpeg/OpenCV."""

    def __init__(self, target, kind: str, desc: str, is_file: bool = False):
        remote = isinstance(target, str) and is_remote(target)
        self.cap = _open_cv(target, remote)
        if not self.cap.isOpened():
            self.cap.release()
            raise SourceError("OpenCV/FFmpeg tidak dapat membuka sumber ini" + (" (periksa URL, jaringan, atau pemblokiran server)" if remote else ""))
        self.kind, self.desc, self.is_file = kind, desc, is_file
        fps = self.cap.get(cv2.CAP_PROP_FPS) or 0
        self.nominal_fps = fps if 1 < fps < 121 else 25.0
        self._n, self._t0 = 0, time.time()

    def read(self):
        ok, frame = self.cap.read()
        if not ok or frame is None:
            if self.is_file:
                self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0); self._n, self._t0 = 0, time.time()
                ok, frame = self.cap.read()
            if not ok or frame is None:
                return False, None, time.time()
        self._n += 1
        if self.is_file:                                    # berkas: putar sesuai waktu video
            due = self._t0 + self._n / self.nominal_fps
            wait = due - time.time()
            if wait > 0:
                time.sleep(min(wait, 0.5))
            return True, frame, self._n / self.nominal_fps
        return True, frame, time.time()

    def close(self):
        self.cap.release()


class MjpegReader:
    kind = "mjpeg"

    def __init__(self, resp, head: bytes, desc: str):
        self.resp, self.buf, self.desc = resp, head, desc
        self.parsed = 0
        self.is_file = False
        self.nominal_fps = 0.0

    def read(self):
        """Ambil frame TERBARU; frame lama yang menumpuk di buffer dilewati agar video tidak tertinggal."""
        for _ in range(400):
            jpg = None
            while True:
                a = self.buf.find(b"\xff\xd8")
                if a < 0:
                    break
                b = self.buf.find(b"\xff\xd9", a + 2)
                if b < 0:
                    break
                jpg, self.buf = self.buf[a:b + 2], self.buf[b + 2:]
                self.parsed += 1
            if jpg is not None:
                frame = cv2.imdecode(np.frombuffer(jpg, np.uint8), cv2.IMREAD_COLOR)
                if frame is not None:
                    return True, frame, time.time()
                continue
            if len(self.buf) > 8_000_000:
                self.buf = b""
            try:
                chunk = self.resp.read(4096)
            except Exception:
                return False, None, time.time()
            if not chunk:
                return False, None, time.time()
            self.buf += chunk
        return False, None, time.time()

    def close(self):
        try:
            self.resp.close()
        except Exception:
            pass


class SnapshotReader:
    kind = "snapshot"

    def __init__(self, url: str, first: bytes | None, desc: str, min_interval: float = 0.25):
        self.url, self.desc, self.min_interval = url, desc, min_interval
        self.is_file = False
        self.nominal_fps = 0.0
        self._last_bytes, self._last_t = None, 0.0
        self._first = first

    def _fetch(self) -> bytes:
        u = self.url + ("&" if "?" in self.url else "?") + "_=" + str(int(time.time() * 1000))
        with urllib.request.urlopen(urllib.request.Request(u, headers=_headers(self.url)), timeout=10) as r:
            return r.read()

    def read(self):
        wait = self.min_interval - (time.time() - self._last_t)
        if wait > 0:
            time.sleep(wait)
        for _ in range(12):
            try:
                data = self._first or self._fetch()
                self._first = None
            except Exception:
                return False, None, time.time()
            self._last_t = time.time()
            if data != self._last_bytes:                    # lewati gambar yang belum berubah
                self._last_bytes = data
                frame = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
                if frame is not None:
                    return True, frame, time.time()
            time.sleep(0.25)
        return False, None, time.time()

    def close(self):
        pass


# ------------------------------------------------------------------------------------------ pengenalan
_LINK = re.compile(r"""(?:src|href|data-src|data-url|file|source)\s*[=:]\s*["']([^"']+?\.(?:m3u8|mjpg|mjpeg|mp4|flv)[^"']*)["']""", re.I)
_LINK2 = re.compile(r"""["'](https?:[^"'\s]+?\.(?:m3u8|mjpg|mjpeg)[^"'\s]*)["']""", re.I)


def _classify(url: str, resp, head: bytes):
    ctype = (resp.headers.get("Content-Type") or "").lower()
    stripped = head.lstrip()[:12]
    if stripped.startswith(b"#EXTM3U") or "mpegurl" in ctype:
        return "hls", ctype
    if "multipart" in ctype:
        return "mjpeg", ctype
    if head[:2] == b"\xff\xd8" or ctype.startswith("image/jpeg") or ctype.startswith("image/jpg"):
        return "snapshot", ctype
    if "text/html" in ctype or stripped[:1] == b"<":
        return "html", ctype
    if ctype.startswith("video/") or "octet-stream" in ctype or "mp2t" in ctype or "flv" in ctype or "mp4" in ctype:
        return "video", ctype
    return "unknown", ctype


def _open_resolved(src: str):
    try:
        r = resolver.resolve(src)
    except resolver.ResolveError as exc:
        raise SourceError(str(exc)) from exc
    kind = "hls" if (r["live"] or ".m3u8" in r["url"] or "m3u8" in r["protocol"]) else "video"
    label = ("siaran langsung" if r["live"] else "video") + (f" {r['height']}p" if r.get("height") else "")
    title = (r["title"] or "tanpa judul")[:60]
    try:
        return CvReader(r["url"], kind, f"YouTube/web: {title} ({label})", is_file=not r["live"])
    except SourceError:
        resolver._cache.clear()                                # alamat mungkin sudah kedaluwarsa; coba sekali lagi dengan yang baru
        r = resolver.resolve(src, force=True)
        return CvReader(r["url"], kind, f"YouTube/web: {title} ({label})", is_file=not r["live"])


def open_source(src: str, depth: int = 0):
    """Kembalikan pembaca untuk 'src'. Melempar SourceError dengan pesan yang dapat ditindaklanjuti."""
    src = str(src).strip()
    if not src:
        raise SourceError("Sumber kosong")
    if src.isdigit():
        return CvReader(int(src), "camera", f"Kamera #{src}")
    if not is_remote(src):
        if not Path(src).exists():
            raise SourceError(f"Berkas tidak ditemukan di server: {src}")
        return CvReader(src, "file", "Berkas video", is_file=True)
    if not src.lower().startswith(("http://", "https://")):
        return CvReader(src, "stream", "Aliran jaringan (RTSP/RTMP)")
    if depth == 0 and resolver.is_youtube(src):
        return _open_resolved(src)
    try:
        resp = urllib.request.urlopen(urllib.request.Request(src, headers=_headers(src)), timeout=12)
    except urllib.error.HTTPError as exc:
        hint = {403: " Server menolak akses (mungkin memblokir IP di luar Indonesia / butuh Referer).", 404: " Alamat tidak ditemukan.",
                401: " Butuh login."}.get(exc.code, "")
        raise SourceError(f"Server membalas HTTP {exc.code}.{hint}") from exc
    except Exception as exc:
        raise SourceError(f"Tidak dapat terhubung: {type(exc).__name__}: {exc}") from exc
    try:
        head = resp.read(4096)
    except Exception as exc:
        resp.close()
        raise SourceError(f"Koneksi terbuka tetapi tidak ada data: {exc}") from exc
    final = resp.geturl()
    kind, ctype = _classify(final, resp, head)
    if kind == "mjpeg":
        return MjpegReader(resp, head, f"Aliran MJPEG ({ctype.split(';')[0]})")
    if kind == "snapshot":
        resp.close()
        return SnapshotReader(final, head, "Gambar JPEG yang diperbarui (snapshot)")
    if kind in ("hls", "video"):
        resp.close()
        return CvReader(final, kind, "Aliran HLS (.m3u8)" if kind == "hls" else f"Video HTTP ({ctype.split(';')[0]})")
    if kind == "html" and depth == 0:
        try:
            text = (head + resp.read(300_000)).decode("utf-8", "ignore")
        except Exception:
            text = head.decode("utf-8", "ignore")
        resp.close()
        m = _LINK2.search(text) or _LINK.search(text) or re.search(r"""<(?:img|video|source|iframe)[^>]+src=["']([^"']+)["']""", text, re.I)
        if m:
            return open_source(urllib.parse.urljoin(final, m.group(1)), depth + 1)
        try:                                                  # cadangan: yt-dlp punya pengenal untuk banyak situs video
            return _open_resolved(src)
        except SourceError as exc:
            if "belum terpasang" in str(exc):
                raise
        raise SourceError("Alamat ini mengembalikan halaman web (HTML), bukan video, dan tidak ada tautan aliran di dalamnya. "
                          "Gunakan alamat langsung ke aliran (.m3u8 / MJPEG / JPEG), atau tautan YouTube.")
    resp.close()
    if kind == "unknown":                                    # coba serahkan ke FFmpeg
        return CvReader(final, "video", f"Aliran tidak dikenal ({ctype or 'tanpa tipe'})")
    raise SourceError(f"Jenis isi tidak didukung: {ctype or 'tidak diketahui'}")


def test_source(src: str, seconds: float = 4.0) -> dict:
    """Uji sumber: jenis, resolusi, dan frame rate nyata selama beberapa detik."""
    t0 = time.time()
    try:
        rd = open_source(src)
    except SourceError as exc:
        return {"ok": False, "message": str(exc)}
    except Exception as exc:
        return {"ok": False, "message": f"{type(exc).__name__}: {exc}"}
    try:
        n, first, size, last = 0, None, None, None
        t_end = time.time() + seconds
        while time.time() < t_end:
            ok, frame, _ = rd.read()
            if not ok:
                if n == 0 and time.time() - t0 > 8:
                    break
                continue
            n += 1; last = time.time()
            if first is None:
                first = time.time(); size = (int(frame.shape[1]), int(frame.shape[0]))
        if not n:
            return {"ok": False, "message": f"{rd.desc}: terhubung tetapi tidak ada frame yang bisa dibaca", "kind": rd.kind}
        cnt = getattr(rd, "parsed", 0) or n
        fps = (cnt - 1) / max(last - first, 0.001) if cnt > 1 and last > first else 0.0
        return {"ok": True, "kind": rd.kind, "desc": rd.desc, "width": size[0], "height": size[1], "fps": round(fps, 1),
                "first_ms": int((first - t0) * 1000), "message": "Berhasil membaca video"}
    finally:
        rd.close()
