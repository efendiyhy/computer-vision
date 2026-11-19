"""Server Flask: video MJPEG, status waktu nyata (SSE), konfigurasi, cuaca, penyimpanan, dan ekspor data."""
from __future__ import annotations

import atexit
import json
import os
import tempfile
import threading
import time
import urllib.parse
from datetime import datetime, timedelta
from pathlib import Path

import cv2
from flask import Flask, Response, jsonify, request, send_file, send_from_directory
from werkzeug.utils import secure_filename

from . import __version__
from .analytics import Analytics
from .recorder import Recorder
from .config import CLASS_LABEL, DEFAULT_STREAM_URL, ROOT, Config
from . import updater
from .pipeline import Pipeline
from .reader import test_source as probe_source
from .storage import Storage
from .weather import WeatherService, _get_json

WEB = Path(__file__).resolve().parent / "web"
VIDEO_EXT = {".mp4", ".avi", ".mkv", ".mov", ".webm", ".m4v"}
GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"


def _date_range():
    """?from=YYYY-MM-DD&to=YYYY-MM-DD (waktu setempat, tanggal akhir ikut) -> (t0, t1) epoch."""
    def p(k):
        v = request.args.get(k)
        try:
            return datetime.strptime(v, "%Y-%m-%d") if v else None
        except ValueError:
            return None
    a, b = p("from"), p("to")
    return (a.timestamp() if a else None), ((b + timedelta(days=1)).timestamp() if b else None)


def create_app(demo: bool = False, source: str | None = None, config_path: str | None = None,
               urls: list[str] | None = None, password: str | None = None):
    cfg = Config(Path(config_path) if config_path else None)
    if source:
        cfg.update({"source": source}, save=False)
    log_dir = Path(cfg["log_dir"])
    log_dir = log_dir if log_dir.is_absolute() else ROOT / log_dir
    storage = Storage(log_dir, "emisisense_demo.db" if demo else "emisisense.db")
    weather = WeatherService(cfg, demo=demo, on_data=None if demo else storage.add_weather, on_wind=storage.upsert_wind)
    analytics = Analytics(cfg, weather_cb=weather.snapshot, storage=storage)
    pipe = Pipeline(cfg, analytics, demo=demo)
    recorder = Recorder(log_dir / ("recordings_demo" if demo else "recordings"), pipe.get_record_frame, cfg)
    app = Flask(__name__, static_folder=None)
    app.config["JSON_AS_ASCII"] = False
    app.pipeline, app.analytics, app.weather, app.cfg, app.storage = pipe, analytics, weather, cfg, storage
    server_urls = urls or []

    weather.start()
    pipe.start()

    def shutdown():
        try:
            recorder.stop()
            analytics.flush()
            storage.close()
        except Exception:
            pass
    atexit.register(shutdown)
    app.shutdown = shutdown

    @app.before_request
    def auth():
        if not password:
            return None
        a = request.authorization
        if a and a.password == password:
            return None
        return Response("Butuh kata sandi.", 401, {"WWW-Authenticate": 'Basic realm="EmisiSense Vision"'})

    @app.after_request
    def nocache(r):
        r.headers["Cache-Control"] = "no-store"
        return r

    @app.get("/")
    def index():
        return send_from_directory(WEB, "index.html")

    @app.get("/static/<path:name>")
    def static_files(name):
        return send_from_directory(WEB, name)

    @app.get("/video")
    def video():
        def gen():
            seq = 0
            while True:
                seq, jpg = pipe.jpeg(seq)
                if jpg is None:
                    time.sleep(0.2); continue
                yield b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: " + str(len(jpg)).encode() + b"\r\n\r\n" + jpg + b"\r\n"
        return Response(gen(), mimetype="multipart/x-mixed-replace; boundary=frame")

    @app.get("/api/record")
    def record_status():
        return jsonify(recorder.status())

    @app.post("/api/record")
    def record_ctl():
        body = request.get_json(force=True, silent=True) or {}
        if body.get("on"):
            if "overlay" in body:
                cfg.update({"record_overlay": bool(body["overlay"])})
            return jsonify(recorder.start(bool(cfg["record_overlay"])))
        return jsonify(recorder.stop())

    @app.get("/api/recordings")
    def recordings():
        return jsonify({"items": recorder.list(), "status": recorder.status()})

    @app.get("/api/recordings/<name>")
    def recording_file(name):
        p = recorder.path_of(name)
        if not p:
            return Response(status=404)
        dl = request.args.get("dl") == "1"
        return send_file(p, mimetype="video/mp4", as_attachment=dl, download_name=name, conditional=True)

    @app.delete("/api/recordings/<name>")
    def recording_delete(name):
        return jsonify({"ok": recorder.delete(name)})

    @app.get("/snapshot.jpg")
    def snapshot_jpg():
        _, jpg = pipe.jpeg(-1, 3.0)
        if jpg is None:
            return Response(status=503)
        return Response(jpg, mimetype="image/jpeg", headers={"Content-Disposition": f"attachment; filename=snapshot_{int(time.time())}.jpg"})

    def payload():
        return {"t": time.time(), "status": pipe.get_status(), "stats": analytics.snapshot(), "weather": weather.snapshot(),
                "version": __version__, "urls": server_urls, "demo": demo, "recording": recorder.status()}

    @app.get("/api/state")
    def state():
        return jsonify(payload())

    @app.get("/api/stream")
    def stream():
        def gen():
            while True:
                yield f"data: {json.dumps(payload(), ensure_ascii=False)}\n\n"
                time.sleep(1.0)
        return Response(gen(), mimetype="text/event-stream", headers={"X-Accel-Buffering": "no"})

    # ---------------------------------------------------------------- konfigurasi
    @app.get("/api/config")
    def get_cfg():
        c = cfg.get(); c["default_source"] = DEFAULT_STREAM_URL; c["class_labels"] = CLASS_LABEL
        return jsonify(c)

    @app.post("/api/config")
    def set_cfg():
        patch = request.get_json(force=True, silent=True) or {}
        old = cfg["source"]
        patch.pop("default_source", None); patch.pop("class_labels", None)
        if "location" in patch:
            try:
                loc = patch["location"]
                lat, lon = float(loc["lat"]), float(loc["lon"])
                if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                    raise ValueError
                patch["location"] = {"name": str(loc.get("name") or f"{lat:.4f}, {lon:.4f}")[:80], "lat": lat, "lon": lon}
            except (KeyError, ValueError, TypeError):
                return jsonify({"error": "Lintang harus -90..90 dan bujur -180..180"}), 400
        if "source" in patch:
            patch["source"] = str(patch["source"]).strip() or DEFAULT_STREAM_URL
        new = cfg.update(patch)
        if "source" in patch and patch["source"] != old:
            analytics.flush(); pipe.reload_source(); analytics.reset()
        if "location" in patch:
            weather.refresh()
        return jsonify(new)

    @app.post("/api/source/reset")
    def reset_source():
        analytics.flush()
        cfg.update({"source": DEFAULT_STREAM_URL}); pipe.reload_source(); analytics.reset()
        return jsonify({"ok": True, "source": DEFAULT_STREAM_URL})

    @app.post("/api/source/test")
    def test_source():
        src = str((request.get_json(silent=True) or {}).get("source", "")).strip()
        if not src:
            return jsonify({"ok": False, "message": "Sumber kosong"}), 400
        res: dict = {}
        th = threading.Thread(target=lambda: res.update(probe_source(src, 4.0)), daemon=True)
        th.start(); th.join(40)
        return jsonify(res or {"ok": False, "message": "Waktu habis: sumber tidak merespons dalam 40 detik"})

    @app.post("/api/source/upload")
    def upload_source():
        f = request.files.get("file")
        if not f or not f.filename:
            return jsonify({"error": "Tidak ada berkas"}), 400
        name = secure_filename(f.filename)
        if Path(name).suffix.lower() not in VIDEO_EXT:
            return jsonify({"error": "Format harus " + ", ".join(sorted(VIDEO_EXT))}), 400
        up = log_dir / "uploads"
        up.mkdir(parents=True, exist_ok=True)
        dest = up / name
        f.save(dest)
        analytics.flush()
        cfg.update({"source": str(dest)}); pipe.reload_source(); analytics.reset()
        return jsonify({"ok": True, "source": str(dest)})

    @app.get("/api/geocode")
    def geocode():
        q = (request.args.get("q") or "").strip()
        if len(q) < 2:
            return jsonify({"results": []})
        try:
            js = _get_json(GEOCODE_URL, {"name": q, "count": 8, "language": "id", "format": "json"}, timeout=8)
        except Exception as exc:
            return jsonify({"results": [], "error": f"Tidak dapat menghubungi Open-Meteo: {type(exc).__name__}"}), 502
        out = [{"name": r.get("name"), "admin": ", ".join(x for x in (r.get("admin2"), r.get("admin1"), r.get("country")) if x),
                "lat": r.get("latitude"), "lon": r.get("longitude"), "elevation": r.get("elevation")} for r in js.get("results", [])]
        return jsonify({"results": out})

    @app.post("/api/reset")
    def reset_counts():
        analytics.reset()
        return jsonify({"ok": True})

    @app.post("/api/pause")
    def pause():
        pipe.set_paused(bool((request.get_json(silent=True) or {}).get("paused", not pipe.paused)))
        return jsonify({"paused": pipe.paused})

    @app.post("/api/calibrate")
    def calibrate():
        j = request.get_json(force=True, silent=True) or {}
        try:
            px, m = float(j["ref_px"]), float(j["ref_m"])
            assert px > 0 and m > 0
        except Exception:
            return jsonify({"error": "ref_px dan ref_m harus angka positif"}), 400
        cal = {"m_per_px": m / px, "ref_px": px, "ref_m": m}
        cfg.update({"calibration": cal})
        return jsonify(cal)

    @app.post("/api/calibrate/clear")
    def calibrate_clear():
        cfg.update({"calibration": {"m_per_px": None, "ref_px": None, "ref_m": None}})
        return jsonify({"ok": True})

    # ---------------------------------------------------------------- pembaruan
    @app.get("/api/update/check")
    def update_check():
        return jsonify(updater.check(force=request.args.get("force") == "1"))

    @app.post("/api/update/apply")
    def update_apply():
        if os.environ.get("EMISISENSE_DISABLE_WEB_UPDATE") == "1":
            return jsonify({"ok": False, "message": "Pembaruan lewat web dinonaktifkan di server ini."}), 403
        analytics.flush()
        res = updater.apply()
        if res.get("ok") and (request.get_json(silent=True) or {}).get("restart", True):
            res["restarting"] = True
            updater.restart_soon(app.shutdown)
        return jsonify(res)

    # ---------------------------------------------------------------- data tersimpan
    @app.get("/api/storage")
    def storage_info():
        analytics.flush()
        return jsonify(storage.stats())

    @app.get("/api/history")
    def history():
        try:
            hours = min(24 * 90, max(1.0, float(request.args.get("hours", 24))))
        except ValueError:
            hours = 24.0
        bucket = 300 if hours <= 3 else 900 if hours <= 12 else 3600 if hours <= 72 else 6 * 3600
        analytics.flush()
        return jsonify({"bucket": bucket, "data": storage.history(hours, bucket)})

    @app.get("/api/windrose")
    def windrose():
        try:
            hours = min(24 * 30, max(1.0, float(request.args.get("hours", 24))))
        except ValueError:
            hours = 24.0
        return jsonify(storage.windrose(hours, cfg["location"]))

    def csv_resp(text, name):
        return Response("﻿" + text, mimetype="text/csv; charset=utf-8", headers={"Content-Disposition": f"attachment; filename={name}"})

    @app.get("/api/export/events.csv")
    def export_events():
        analytics.flush(); t0, t1 = _date_range()
        return csv_resp(storage.events_csv(t0, t1), "kejadian_lintas.csv")

    @app.get("/api/export/minutes.csv")
    def export_minutes():
        analytics.flush(); t0, t1 = _date_range()
        return csv_resp(storage.minutes_csv(t0, t1), "lalu_lintas_per_menit.csv")

    @app.get("/api/export/weather.csv")
    def export_weather():
        t0, t1 = _date_range()
        return csv_resp(storage.weather_csv(t0, t1), "cuaca_kualitas_udara.csv")

    @app.get("/api/export/database")
    def export_db():
        analytics.flush()
        tmp = Path(tempfile.gettempdir()) / f"emisisense_backup_{int(time.time())}.db"
        storage.backup_to(tmp)
        return send_file(tmp, as_attachment=True, download_name=f"emisisense_{datetime.now():%Y%m%d_%H%M}.db")

    return app
