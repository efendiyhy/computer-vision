"""Pembaruan aplikasi dari git: cek, terapkan, lalu mulai ulang proses.

Hanya bekerja bila aplikasi dipasang lewat ``git clone`` (pemasang install.sh / install.ps1 melakukannya).
Data (folder data/) dan pengaturan (config.json) tidak masuk git, sehingga tidak tersentuh.
"""
from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from pathlib import Path

from . import __version__
from .config import ROOT

BRANCH = os.environ.get("EMISISENSE_BRANCH", "main")
_cache = {"t": 0.0, "data": None}
_lock = threading.Lock()


def _git(*args, timeout=60) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True, timeout=timeout)


def is_git() -> bool:
    try:
        return (ROOT / ".git").exists() and _git("rev-parse", "--is-inside-work-tree", timeout=10).returncode == 0
    except Exception:
        return False


def current() -> dict:
    info = {"version": __version__, "git": False, "commit": None, "date": None, "subject": None}
    if not is_git():
        return info
    try:
        out = _git("log", "-1", "--format=%h|%cI|%s", timeout=10).stdout.strip().split("|", 2)
        if len(out) == 3:
            info.update(git=True, commit=out[0], date=out[1], subject=out[2])
    except Exception:
        pass
    return info


def check(force: bool = False) -> dict:
    """Bandingkan dengan origin/<branch>. Hasil di-cache 10 menit."""
    with _lock:
        if not force and _cache["data"] and time.time() - _cache["t"] < 600:
            return _cache["data"]
        res = {**current(), "checked": time.strftime("%Y-%m-%dT%H:%M:%S"), "available": False, "behind": 0, "changes": [], "dirty": False,
               "error": None, "branch": BRANCH}
        if not res["git"]:
            res["error"] = "Aplikasi tidak dipasang lewat git, perbarui dengan menjalankan ulang pemasang."
        else:
            try:
                f = _git("fetch", "--quiet", "origin", BRANCH, timeout=60)
                if f.returncode != 0:
                    res["error"] = "Tidak dapat menghubungi GitHub: " + (f.stderr.strip().splitlines() or ["gagal"])[-1]
                else:
                    behind = int(_git("rev-list", "--count", f"HEAD..origin/{BRANCH}", timeout=10).stdout.strip() or 0)
                    res["behind"], res["available"] = behind, behind > 0
                    if behind:
                        log = _git("log", f"HEAD..origin/{BRANCH}", "--format=%h|%cs|%s", "-n", "15", timeout=10).stdout.strip().splitlines()
                        res["changes"] = [dict(zip(("commit", "date", "subject"), ln.split("|", 2))) for ln in log]
                    st = _git("status", "--porcelain", "--untracked-files=no", timeout=10).stdout.strip()
                    res["dirty"] = bool(st)
            except Exception as exc:
                res["error"] = f"{type(exc).__name__}: {exc}"
        _cache.update(t=time.time(), data=res)
        return res


def apply() -> dict:
    """git pull (fast-forward) + pasang dependensi bila requirements.txt berubah. Tidak memulai ulang."""
    if not is_git():
        return {"ok": False, "message": "Bukan instalasi git."}
    log = []
    try:
        if _git("status", "--porcelain", "--untracked-files=no", timeout=10).stdout.strip():
            return {"ok": False, "message": "Ada perubahan lokal pada berkas kode; perbarui manual (git stash) agar tidak tertimpa."}
        old_req = _git("rev-parse", "HEAD:requirements.txt", timeout=10).stdout.strip()
        p = _git("pull", "--ff-only", "origin", BRANCH, timeout=120)
        log.append(p.stdout.strip() or p.stderr.strip())
        if p.returncode != 0:
            return {"ok": False, "message": "git pull gagal: " + (p.stderr.strip().splitlines() or ["?"])[-1], "log": log}
        new_req = _git("rev-parse", "HEAD:requirements.txt", timeout=10).stdout.strip()
        if old_req != new_req:
            pip = subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", "-r", str(ROOT / "requirements.txt")],
                                 capture_output=True, text=True, timeout=900)
            log.append("pip: " + ("OK" if pip.returncode == 0 else pip.stderr.strip()[-300:]))
            if pip.returncode != 0:
                return {"ok": False, "message": "Pemasangan dependensi gagal; kode sudah diperbarui, jalankan pip manual.", "log": log}
        _cache["data"] = None
        return {"ok": True, "message": "Pembaruan terpasang.", "log": log, "current": current()}
    except Exception as exc:
        return {"ok": False, "message": f"{type(exc).__name__}: {exc}", "log": log}


def restart_soon(shutdown_cb, delay: float = 1.0):
    """Mulai ulang proses ini dengan argumen yang sama (setelah respons HTTP terkirim)."""
    def go():
        time.sleep(delay)
        try:
            shutdown_cb()
        except Exception:
            pass
        args = [sys.executable] + sys.argv
        if os.name == "nt":
            helper = ("import subprocess,sys,time; time.sleep(3); subprocess.Popen(%r, cwd=%r)" % (args, str(ROOT)))
            subprocess.Popen([sys.executable, "-c", helper], creationflags=0x00000008 | 0x00000200, close_fds=True)
            os._exit(0)
        os.execv(sys.executable, args)
    threading.Thread(target=go, daemon=True).start()
