"""Server Flask: video MJPEG, status waktu nyata (SSE), konfigurasi, cuaca, dan ekspor data."""
from __future__ import annotations

import json
import time
from pathlib import Path

from flask import Flask, Response, jsonify, request, send_from_directory

from . import __version__
from .analytics import Analytics
from .config import CLASS_LABEL, DEFAULT_STREAM_URL, Config
from .pipeline import Pipeline
from .weather import WeatherService

WEB = Path(__file__).resolve().parent / "web"


def create_app(demo: bool = False, source: str | None = None, config_path: str | None = None):
    cfg = Config(Path(config_path) if config_path else None)
    if source:
        cfg.update({"source": source}, save=False)
    weather = WeatherService(cfg, demo=demo)
    analytics = Analytics(cfg, weather_cb=weather.snapshot)
    pipe = Pipeline(cfg, analytics, demo=demo)
    app = Flask(__name__, static_folder=None)
    app.config["JSON_AS_ASCII"] = False
    app.pipeline, app.analytics, app.weather, app.cfg = pipe, analytics, weather, cfg

    def started():
        if not getattr(app, "_started", False):
            app._started = True
            weather.start(); pipe.start()

    started()

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

    @app.get("/snapshot.jpg")
    def snapshot_jpg():
        _, jpg = pipe.jpeg(-1, 3.0)
        if jpg is None:
            return Response(status=503)
        return Response(jpg, mimetype="image/jpeg", headers={"Content-Disposition": f"attachment; filename=snapshot_{int(time.time())}.jpg"})

    def payload():
        return {"t": time.time(), "status": pipe.status, "stats": analytics.snapshot(), "weather": weather.snapshot(),
                "version": __version__}

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

    @app.get("/api/config")
    def get_cfg():
        c = cfg.get(); c["default_source"] = DEFAULT_STREAM_URL; c["class_labels"] = CLASS_LABEL
        return jsonify(c)

    @app.post("/api/config")
    def set_cfg():
        patch = request.get_json(force=True, silent=True) or {}
        old = cfg["source"]
        patch.pop("default_source", None); patch.pop("class_labels", None)
        new = cfg.update(patch)
        if "source" in patch and patch["source"] != old:
            pipe.reload_source(); analytics.reset()
        if "location" in patch:
            weather.refresh()
        return jsonify(new)

    @app.post("/api/source/reset")
    def reset_source():
        cfg.update({"source": DEFAULT_STREAM_URL}); pipe.reload_source(); analytics.reset()
        return jsonify({"ok": True, "source": DEFAULT_STREAM_URL})

    @app.post("/api/reset")
    def reset_counts():
        analytics.reset()
        return jsonify({"ok": True})

    @app.post("/api/pause")
    def pause():
        pipe.paused = bool((request.get_json(silent=True) or {}).get("paused", not pipe.paused))
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

    @app.get("/api/export/events.csv")
    def export_events():
        return Response(analytics.export_events_csv(), mimetype="text/csv",
                        headers={"Content-Disposition": "attachment; filename=kejadian_lintas.csv"})

    @app.get("/api/export/minutes.csv")
    def export_minutes():
        return Response(analytics.export_minutes_csv(), mimetype="text/csv",
                        headers={"Content-Disposition": "attachment; filename=lalu_lintas_per_menit.csv"})

    return app
