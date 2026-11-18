#!/usr/bin/env python3
"""Menjalankan dasbor EmisiSense Vision.

  python run.py                 # CCTV Kota Malang (sumber acuan penelitian)
  python run.py --demo          # simulasi lalu lintas tanpa CCTV
  python run.py --source video.mp4
  python run.py --port 8080 --host 0.0.0.0
"""
import argparse
import threading
import webbrowser

from emisisense_vision.config import DEFAULT_STREAM_URL
from emisisense_vision.server import create_app


def main():
    ap = argparse.ArgumentParser(description="EmisiSense Vision - dasbor visi komputer lalu lintas & cuaca")
    ap.add_argument("--source", help=f"URL CCTV/berkas video/indeks kamera (bawaan: {DEFAULT_STREAM_URL})")
    ap.add_argument("--demo", action="store_true", help="mode simulasi (tanpa CCTV & internet)")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=5000)
    ap.add_argument("--no-browser", action="store_true")
    a = ap.parse_args()
    app = create_app(demo=a.demo, source=a.source)
    url = f"http://{'localhost' if a.host in ('0.0.0.0', '127.0.0.1') else a.host}:{a.port}"
    print(f"\n  EmisiSense Vision berjalan di {url}\n  Tekan Ctrl+C untuk berhenti.\n")
    if not a.no_browser:
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    app.run(host=a.host, port=a.port, threaded=True, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
