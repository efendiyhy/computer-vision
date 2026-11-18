"""Alamat IP jaringan lokal server (untuk ditampilkan saat dijalankan)."""
from __future__ import annotations

import socket
import subprocess


def lan_ips() -> list[str]:
    found: list[str] = []

    def add(ip: str):
        if ip and not ip.startswith(("127.", "169.254.", "0.")) and ip not in found and ip.count(".") == 3:
            found.append(ip)

    try:  # IP antarmuka utama (tanpa mengirim paket)
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        add(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            add(info[4][0])
    except OSError:
        pass
    try:  # Linux: semua antarmuka
        out = subprocess.run(["hostname", "-I"], capture_output=True, text=True, timeout=2).stdout.split()
        for ip in out:
            add(ip)
    except Exception:
        pass
    return found


def urls(port: int, host: str = "0.0.0.0") -> list[str]:
    if host in ("127.0.0.1", "localhost"):
        return [f"http://localhost:{port}"]
    ips = lan_ips() if host in ("0.0.0.0", "::") else [host]
    return [f"http://{ip}:{port}" for ip in ips] + [f"http://localhost:{port}"]
