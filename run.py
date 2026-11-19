#!/usr/bin/env python3
"""Menjalankan dasbor EmisiSense Vision.

  python run.py                 # CCTV Kota Malang (sumber acuan), dapat diakses dari jaringan lokal
  python run.py --demo          # simulasi lalu lintas tanpa CCTV
  python run.py --source video.mp4
  python run.py --local         # hanya dapat diakses dari komputer ini
  python run.py --port 8080 --password rahasia
"""
import argparse
import os
import signal
import sys
import threading
import time
import webbrowser

from emisisense_vision import netinfo
from emisisense_vision.config import DEFAULT_STREAM_URL
from emisisense_vision.server import create_app


def main():
    # Semua waktu (pencatatan, rekaman, tampilan) memakai WIB / GMT+7, apa pun zona waktu sistem.
    os.environ["TZ"] = "Asia/Jakarta"
    if hasattr(time, "tzset"):
        time.tzset()
    ap = argparse.ArgumentParser(description="EmisiSense Vision - dasbor visi komputer lalu lintas & cuaca")
    ap.add_argument("--source", help=f"URL CCTV/berkas video/indeks kamera (bawaan: {DEFAULT_STREAM_URL})")
    ap.add_argument("--demo", action="store_true", help="mode simulasi (tanpa CCTV & internet)")
    ap.add_argument("--host", default="0.0.0.0", help="0.0.0.0 = bisa diakses dari jaringan lokal (bawaan)")
    ap.add_argument("--local", action="store_true", help="hanya localhost (sama dengan --host 127.0.0.1)")
    ap.add_argument("--port", type=int, default=int(os.environ.get("EMISISENSE_PORT", 5000)))
    ap.add_argument("--password", default=os.environ.get("EMISISENSE_PASSWORD"), help="kata sandi akses (opsional, disarankan di jaringan bersama)")
    ap.add_argument("--no-browser", action="store_true", help="jangan membuka browser otomatis")
    a = ap.parse_args()
    host = "127.0.0.1" if a.local else a.host
    urls = netinfo.urls(a.port, host)
    app = create_app(demo=a.demo, source=a.source, urls=urls, password=a.password)

    bar = "=" * 62
    print(f"\n{bar}\n  EmisiSense Vision berjalan{'  [MODE DEMO]' if a.demo else ''}\n{bar}")
    print("  Buka dari perangkat mana pun di jaringan yang sama:")
    for u in urls:
        print(f"     {u}")
    if a.password:
        print("  Akses dilindungi kata sandi (nama pengguna bebas).")
    elif host != "127.0.0.1":
        print("  Peringatan: tanpa kata sandi. Pakai --password bila jaringan dipakai bersama.")
    print("  Data tersimpan di folder data/ (SQLite). Tekan Ctrl+C untuk berhenti.\n")

    def stop(*_):
        app.shutdown()
        sys.exit(0)
    signal.signal(signal.SIGTERM, stop)
    if not a.no_browser and sys.stdout.isatty():
        threading.Timer(1.2, lambda: webbrowser.open(f"http://localhost:{a.port}")).start()
    try:
        app.run(host=host, port=a.port, threaded=True, debug=False, use_reloader=False)
    finally:
        app.shutdown()


if __name__ == "__main__":
    main()
