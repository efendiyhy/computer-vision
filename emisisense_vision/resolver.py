"""Mengubah tautan halaman (YouTube dan situs video lain) menjadi alamat aliran langsung memakai yt-dlp."""
from __future__ import annotations

import re
import threading
import time
import urllib.parse

_YT_HOST = re.compile(r"(^|\.)(youtube\.com|youtu\.be|youtube-nocookie\.com)$", re.I)
_TTL = 20 * 60          # alamat langsung YouTube kedaluwarsa dalam hitungan jam; segarkan tiap 20 menit
_cache: dict[str, tuple[float, dict]] = {}
_lock = threading.Lock()


class ResolveError(Exception):
    pass


def is_youtube(url: str) -> bool:
    try:
        return bool(_YT_HOST.search(urllib.parse.urlparse(url).hostname or ""))
    except Exception:
        return False


def _friendly(msg: str) -> str:
    m = msg.lower()
    if "sign in to confirm" in m or "not a bot" in m:
        return ("YouTube meminta verifikasi (menganggap server ini bot). Coba lagi nanti, perbarui yt-dlp "
                "(menu Sistem → Perbarui, atau `.venv/bin/pip install -U yt-dlp`), atau unduh videonya lalu unggah berkasnya.")
    if "private" in m or "members-only" in m or "age" in m and "restrict" in m:
        return "Video ini privat, khusus anggota, atau dibatasi umur sehingga tidak bisa dibaca tanpa login."
    if "unavailable" in m or "not available" in m:
        return "Video tidak tersedia (dihapus, dibatasi wilayah, atau siaran sudah berakhir)."
    if "premieres in" in m or "will begin in" in m:
        return "Siaran langsung ini belum dimulai."
    if "urlopen" in m or "network" in m or "name or service" in m or "timed out" in m or "unable to download" in m:
        return "Tidak dapat menghubungi YouTube dari server ini. Periksa koneksi internet server."
    return "yt-dlp gagal membaca tautan: " + msg.strip().splitlines()[-1][:200]


def resolve(url: str, max_height: int = 720, force: bool = False) -> dict:
    """Kembalikan {url, title, live, height}. Hasil disimpan sementara agar sambung-ulang tidak memanggil YouTube terus-menerus."""
    key = f"{url}|{max_height}"
    with _lock:
        hit = _cache.get(key)
        if hit and not force and time.time() - hit[0] < _TTL:
            return hit[1]
    try:
        import yt_dlp
    except ImportError as exc:
        raise ResolveError("Modul yt-dlp belum terpasang. Jalankan: .venv/bin/pip install yt-dlp  (Windows: .venv\\Scripts\\pip install yt-dlp), "
                           "lalu mulai ulang aplikasi.") from exc
    opts = {"quiet": True, "no_warnings": True, "noplaylist": True, "socket_timeout": 15, "skip_download": True,
            "format": f"best[height<={max_height}][vcodec!=none][acodec!=none]/best[height<={max_height}]/best"}
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as exc:
        raise ResolveError(_friendly(str(exc))) from exc
    if info.get("entries"):
        info = next((e for e in info["entries"] if e), info)
    direct = info.get("url")
    if not direct:
        fm = [f for f in info.get("formats", []) if f.get("url") and f.get("vcodec") not in (None, "none")]
        if not fm:
            raise ResolveError("yt-dlp tidak menemukan aliran video pada tautan ini.")
        direct = sorted(fm, key=lambda f: (f.get("height") or 0) <= max_height and (f.get("height") or 0))[-1]["url"]
    res = {"url": direct, "title": info.get("title") or "", "live": bool(info.get("is_live")), "height": info.get("height"),
           "protocol": info.get("protocol") or ""}
    with _lock:
        _cache[key] = (time.time(), res)
    return res
