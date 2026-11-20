"""Server Flask: video MJPEG, status waktu nyata (SSE), konfigurasi, cuaca, penyimpanan, dan ekspor data."""
from __future__ import annotations

import atexit
import json
import os
import shutil
import subprocess
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
from . import export as ex
from .combined import HEAD as COMBINED_HEAD, combined_rows, to_csv
from .pmgas import FIELDS as PG_FIELDS, FILL_GAP_DEFAULT, MERGED_COLS, RAW_COLS, PmGasStore, start_demo_feed
from .weather import WeatherService, _get_json, fetch_hourly

WEB = Path(__file__).resolve().parent / "web"
VIDEO_EXT = {".mp4", ".avi", ".mkv", ".mov", ".webm", ".m4v"}
NET_HELPER = os.environ.get("EMISISENSE_NET_HELPER", "/usr/local/bin/emisisense-net")
GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"


def _net_prefix():
    return [] if os.geteuid() == 0 else ["sudo", "-n"]


def _net_ready():
    return os.name == "posix" and os.path.exists(NET_HELPER) and (os.geteuid() == 0 or bool(shutil.which("sudo")))


def _net_run(cmd, stdin=None, timeout=25):
    """Panggil pengatur jaringan Orange Pi (hotspot/Wi-Fi) lewat sudo; None bila tidak terpasang."""
    if not _net_ready():
        return None
    try:
        p = subprocess.run([*_net_prefix(), NET_HELPER, *cmd], input=stdin, capture_output=True, text=True, timeout=timeout)
        return json.loads(p.stdout.strip().splitlines()[-1]) if p.stdout.strip() else {"ok": False, "message": p.stderr.strip()[:200]}
    except (OSError, ValueError, subprocess.TimeoutExpired) as e:
        return {"ok": False, "message": str(e)[:200]}


def _net_detached(cmd, payload):
    """Jalankan perubahan jaringan terpisah dari server (koneksi klien akan terputus sesaat)."""
    p = subprocess.Popen([*_net_prefix(), NET_HELPER, *cmd], stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True, text=True)
    p.stdin.write(json.dumps(payload))
    p.stdin.close()



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
    pg = PmGasStore(log_dir, "pmgas_demo.db" if demo else "pmgas.db")
    pg_token = os.environ.get("ESP_LAN_TOKEN", "")
    pipe = Pipeline(cfg, analytics, demo=demo)
    recorder = Recorder(log_dir / ("recordings_demo" if demo else "recordings"), pipe.get_record_frame, cfg)
    app = Flask(__name__, static_folder=None)
    app.config["JSON_AS_ASCII"] = False
    app.pipeline, app.analytics, app.weather, app.cfg, app.storage, app.pmgas = pipe, analytics, weather, cfg, storage, pg
    server_urls = urls or []

    weather.start()
    pipe.start()
    if demo:
        start_demo_feed(pg)

    def shutdown():
        try:
            recorder.stop()
            analytics.flush()
            storage.close()
            pg.close()
        except Exception:
            pass
    atexit.register(shutdown)
    app.shutdown = shutdown

    @app.before_request
    def auth():
        if not password or (request.path == "/api/ingest" and request.method == "POST"):   # ESP32 tidak bisa kata sandi; pakai token (ESP_LAN_TOKEN) bila perlu
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

    @app.get("/video/raw")
    def video_raw():
        """MJPEG bersih (tanpa gambar tambahan) agar program lain bisa memakai kamera yang sama. ?fps=1..30 (bawaan 10)."""
        try:
            fps = min(30.0, max(1.0, float(request.args.get("fps", 10))))
        except ValueError:
            fps = 10.0

        def gen():
            seq, last = 0, 0.0
            while True:
                seq, jpg = pipe.raw_jpeg(seq)
                if jpg is None:
                    time.sleep(0.1); continue
                wait = 1.0 / fps - (time.time() - last)
                if wait > 0:
                    time.sleep(wait)
                last = time.time()
                yield b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: " + str(len(jpg)).encode() + b"\r\n\r\n" + jpg + b"\r\n"
        return Response(gen(), mimetype="multipart/x-mixed-replace; boundary=frame")

    @app.get("/snapshot/raw.jpg")
    def snapshot_raw():
        _, jpg = pipe.raw_jpeg(-1, 3.0)
        if jpg is None:
            return jsonify({"error": "belum ada frame"}), 503
        return Response(jpg, mimetype="image/jpeg", headers={"Cache-Control": "no-store"})

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
                "version": __version__, "urls": server_urls, "demo": demo, "recording": recorder.status(), "pmgas": pg.latest()}

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

    # ---------------------------------------------------------------- sensor PM & Gas (ESP32)
    def ingest_view():
        if pg_token and request.headers.get("X-Device-Token", "") != pg_token:
            return jsonify({"ok": False, "error": "Device token invalid"}), 401
        try:
            if request.content_length and request.content_length > 8192:
                raise ValueError("Request too large")
            return jsonify({"ok": True, **pg.ingest(json.loads(request.get_data() or b"{}"))})
        except (ValueError, json.JSONDecodeError) as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        except Exception:
            return jsonify({"ok": False, "error": "Internal error"}), 500
    app.add_url_rule("/api/ingest", "ingest", ingest_view, methods=["POST"])

    def pmgas_listen(port: int = 8787, host: str = "0.0.0.0"):
        """Firmware ESP32 selalu mengirim ke port 8787; buka penerima kecil di port itu (hanya /api/ingest)."""
        from werkzeug.serving import make_server
        mini = Flask("ingest")
        mini.add_url_rule("/api/ingest", "ingest", ingest_view, methods=["POST"])
        mini.add_url_rule("/", "root", lambda: "EmisiSense Vision: penerima sensor PM/Gas (POST /api/ingest)")
        try:
            srv = make_server(host, port, mini, threaded=True)
        except OSError as exc:
            return None, str(exc)
        threading.Thread(target=srv.serve_forever, daemon=True, name="pmgas-ingest").start()
        return srv, None
    app.pmgas_listen = pmgas_listen

    @app.get("/api/pmgas")
    def pmgas_status():
        hosts = []
        for u in server_urls:
            h = urllib.parse.urlsplit(u).hostname
            if h and h not in hosts and h not in ("localhost", "127.0.0.1"):
                hosts.append(h)
        return jsonify({"latest": pg.latest(), "meta": pg.get_meta(), "stats": pg.stats(), "token": bool(pg_token),
                        "ingest": [f"http://{h}:{getattr(app, 'ingest_port', 8787)}/api/ingest" for h in hosts],
                        "series": pg.recent_series(1800, 30)})

    @app.post("/api/pmgas/meta")
    def pmgas_meta():
        b = request.get_json(force=True, silent=True) or {}
        for k in ("session", "label"):
            if k in b and (not isinstance(b[k], str) or any(ord(c) < 32 for c in b[k])):
                return jsonify({"error": "Teks tidak boleh berisi karakter kontrol"}), 400
        return jsonify(pg.set_meta(b.get("session"), b.get("label")))

    @app.get("/api/pmgas/history")
    def pmgas_history():
        try:
            hours = min(24 * 90, max(1.0, float(request.args.get("hours", 24))))
        except ValueError:
            hours = 24.0
        bucket = 300 if hours <= 3 else 900 if hours <= 12 else 3600 if hours <= 72 else 6 * 3600
        t1 = int(time.time() // bucket * bucket) + bucket
        t0 = t1 - int(hours * 3600 // bucket) * bucket
        return jsonify({"bucket": bucket, "data": pg.history(t0, t1, bucket)})

    # ---------------------------------------------------------------- sinkronisasi cuaca (Open-Meteo)
    sync_lock = threading.Lock()
    sync_last: dict = {}

    def _demo_hourly(t0):
        from .weather import demo_weather
        out, h = {}, int(t0 // 3600 * 3600)
        while h <= time.time():
            c = demo_weather(cfg["location"])
            out[h] = {**c["current"], **c["air_quality"], "relative_humidity_2m": 70}
            h += 3600
        return out, []

    @app.get("/api/sync")
    def sync_status():
        p = storage.wx_pending()
        return jsonify({"pending": p, "last": sync_last or None, "busy": sync_lock.locked(),
                        "online_weather": bool(weather.snapshot().get("current")) and not weather.snapshot().get("error")})

    @app.post("/api/sync")
    def sync_run():
        """Ambil data Open-Meteo untuk menit yang direkam saat offline lalu isi ke database (per jam). Aman diulang."""
        if not sync_lock.acquire(blocking=False):
            return jsonify({"ok": False, "message": "Sinkronisasi sedang berjalan"}), 409
        try:
            analytics.flush()
            loc, pend = dict(cfg["location"]), storage.wx_pending()
            res = {"ok": True, "pending_before": pend["minutes"], "minutes_filled": 0, "hours_used": 0, "warnings": []}
            try:
                if pend["minutes"]:
                    hourly, warns = _demo_hourly(pend["first"]) if demo else fetch_hourly(loc, pend["first"])
                    res["warnings"] = warns
                    if not hourly:
                        raise RuntimeError("Open-Meteo tidak mengirim data")
                    res.update(storage.backfill_weather(hourly, loc))
                weather.refresh()                      # cuaca saat ini + riwayat angin ikut diperbarui
            except Exception as exc:
                res.update(ok=False, message="Tidak dapat mengambil data Open-Meteo. Pastikan Orange Pi terhubung ke internet, lalu coba lagi.",
                           detail=f"{type(exc).__name__}: {exc}"[:200])
            left = storage.wx_pending()
            res["pending_after"] = left["minutes"]
            if res["ok"]:
                res["message"] = ("Semua data sudah memiliki cuaca." if not pend["minutes"] else
                                  f"Cuaca terisi untuk {res['minutes_filled']} menit ({res['hours_used']} jam)." +
                                  (f" {left['minutes']} menit belum terisi (jam terbaru, tersedia nanti)." if left["minutes"] else ""))
            res["time"] = datetime.now().astimezone().isoformat(timespec="seconds")
            sync_last.clear(); sync_last.update(res)
            return jsonify(res), (200 if res["ok"] else 502)
        finally:
            sync_lock.release()

    # ---------------------------------------------------------------- jaringan (hotspot / Wi-Fi Orange Pi)
    @app.get("/api/net")
    def net_status():
        res = _net_run(["status"], timeout=15)
        if res is None:
            why = "Hanya tersedia di Orange Pi/Linux." if os.name != "posix" else "Pengatur jaringan belum terpasang di perangkat ini."
            return jsonify({"available": False, "installed": False, "message": why})
        if res.get("available") is False:
            return jsonify({"available": False, "installed": True, "message": res.get("message") or "Adaptor atau NetworkManager tidak tersedia."})
        return jsonify(res)

    @app.get("/api/net/scan")
    def net_scan():
        res = _net_run(["scan"], timeout=30)
        return jsonify(res or {"ok": False, "networks": [], "message": "Pengatur jaringan belum terpasang"})

    @app.post("/api/net/connect")
    def net_connect():
        b = request.get_json(silent=True) or {}
        ssid, pw = str(b.get("ssid", "")), str(b.get("password", ""))
        if not ssid or len(ssid.encode()) > 32 or (pw and not 8 <= len(pw) <= 63):
            return jsonify({"ok": False, "message": "Nama Wi-Fi atau kata sandi tidak valid (sandi 8-63 karakter)"}), 400
        if _net_run(["status"], timeout=15) is None:
            return jsonify({"ok": False, "message": "Pengatur jaringan belum terpasang"}), 503
        _net_detached(["connect"], {"ssid": ssid, "password": pw})
        return jsonify({"ok": True, "started": True})

    @app.post("/api/net/hotspot")
    def net_hotspot():
        b = request.get_json(silent=True) or {}
        payload = {k: str(b[k]) for k in ("ssid", "password") if b.get(k)}
        if payload.get("password") and not 8 <= len(payload["password"]) <= 63:
            return jsonify({"ok": False, "message": "Kata sandi hotspot harus 8-63 karakter"}), 400
        if _net_run(["status"], timeout=15) is None:
            return jsonify({"ok": False, "message": "Pengatur jaringan belum terpasang"}), 503
        _net_detached(["hotspot"], payload)
        return jsonify({"ok": True, "started": True})

    @app.post("/api/time")
    def sync_time():
        """Orange Pi tanpa internet tidak punya jam yang benar; ponsel/browser mengirim waktu yang benar."""
        try:
            t = int(float((request.get_json(silent=True) or {}).get("t")))
        except (TypeError, ValueError):
            return jsonify({"ok": False}), 400
        if abs(t - time.time()) < 60:
            return jsonify({"ok": True, "changed": False})
        res = _net_run(["settime", str(t)], timeout=10)
        return jsonify(res or {"ok": False, "changed": False})

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

    def _gap():
        try:
            return max(0, min(86400, int(request.args.get("gap", FILL_GAP_DEFAULT))))
        except ValueError:
            return FILL_GAP_DEFAULT

    def _fill_note(gap):
        return ([f"Nilai KOSONG diisi dengan nilai valid terakhir sebelumnya selama selisih waktu paling lama {gap} detik (batas isian); lebih dari itu tetap kosong. "
                 "Baris/kolom yang diisi ditandai."] if gap else ["Pengisian nilai kosong dimatikan (gap=0): sel yang tidak punya pembacaan dibiarkan kosong."])

    @app.get("/api/export/events.zip")
    def export_events():
        analytics.flush(); t0, t1 = ex.parse_range(request.args)
        text = storage.events_csv(t0, t1)
        return ex.zip_response("kejadian_lintas", text, ex.keterangan(
            "Kejadian lintas kendaraan", "Satu baris untuk setiap kendaraan atau pejalan kaki yang melewati garis hitung (hasil computer vision). Setiap garis menghitung satu arah.",
            ex.COL_EVENTS, t0, t1, max(0, text.count("\n") - 1), version=__version__), t0, t1)

    @app.get("/api/export/minutes.zip")
    def export_minutes():
        analytics.flush(); t0, t1 = ex.parse_range(request.args)
        text = storage.minutes_csv(t0, t1)
        return ex.zip_response("lalu_lintas_per_menit", text, ex.keterangan(
            "Agregat lalu lintas per menit", "Jumlah kendaraan per jenis, volume SMP, dan kecepatan rata-rata untuk setiap menit pencatatan, beserta cuaca dan kualitas udara Open-Meteo pada menit itu.",
            ex.COL_MINUTES, t0, t1, max(0, text.count("\n") - 1),
            ["Kolom pm2_5, pm10, co, no2, us_aqi pada berkas ini berasal dari model Open-Meteo, BUKAN dari sensor PM/Gas lokal. Untuk data sensor lokal lihat unduhan PM & Gas atau dokumen sinkron kendaraan + PM/Gas.",
             "Menit yang direkam saat offline dan belum disinkronkan memiliki kolom cuaca kosong (tekan Sinkronisasi saat online)."], __version__), t0, t1)

    @app.get("/api/export/weather.zip")
    def export_weather():
        t0, t1 = ex.parse_range(request.args)
        text = storage.weather_csv(t0, t1)
        return ex.zip_response("cuaca_kualitas_udara", text, ex.keterangan(
            "Cuaca dan kualitas udara (Open-Meteo)", "Rekaman cuaca, angin, dan kualitas udara dari layanan Open-Meteo untuk lokasi pemantauan. Ini data model/prakiraan, bukan hasil sensor di lokasi.",
            ex.COL_WEATHER, t0, t1, max(0, text.count("\n") - 1), version=__version__), t0, t1)

    @app.get("/api/export/pmgas-gabungan.zip")
    def export_pmgas_merged():
        t0, t1 = ex.parse_range(request.args); gap = _gap()
        rows = pg.merged(t0, t1, gap=gap, fill=gap > 0)
        return ex.zip_response("sensor_pm_gas_gabungan", to_csv(MERGED_COLS, rows), ex.keterangan(
            "Sensor PM dan Gas lokal - gabungan per detik (sudah diisi)",
            "Data dua alat ESP32 (PM partikulat dan Gas) yang disinkronkan menurut WAKTU UKUR sensor, satu baris per detik. Nilai yang hilang sudah ditangani sehingga siap dianalisis.",
            ex.COL_PM_MERGED, t0, t1, len(rows),
            ["Penggabungan memakai waktu ukur pada paket sensor, bukan waktu paket diterima (paket antrean microSD tidak salah pasang)."] + _fill_note(gap) +
            ["Data asli sebelum pengisian tersedia pada unduhan 'PM & Gas data mentah'."], __version__), t0, t1)

    @app.get("/api/export/pmgas-mentah.zip")
    def export_pmgas_raw():
        t0, t1 = ex.parse_range(request.args)
        kind = request.args.get("device_type", "all")
        rows = pg.raw_rows(t0, t1, kind if kind in PG_FIELDS else None)
        return ex.zip_response("sensor_pm_gas_mentah", to_csv(RAW_COLS, rows), ex.keterangan(
            "Sensor PM dan Gas lokal - data mentah",
            "Setiap paket yang diterima dari ESP32 apa adanya (satu baris per paket), untuk audit. TIDAK digabung dan TIDAK diisi; nilai kosong tetap kosong.",
            ex.COL_PM_RAW, t0, t1, len(rows), ["Rentang waktu memakai waktu ukur sensor (atau waktu terima bila jam sensor tidak sah)."], __version__), t0, t1)

    @app.get("/api/export/sinkron-kendaraan-pmgas.zip")
    def export_combined():
        analytics.flush(); t0, t1 = ex.parse_range(request.args); gap = _gap()
        rows = combined_rows(storage.minutes_rows(t0, t1), pg, gap)
        return ex.zip_response("sinkron_kendaraan_pm_gas_per_menit", to_csv(COMBINED_HEAD, rows), ex.keterangan(
            "Sinkron kendaraan + sensor PM/Gas lokal (per menit)",
            "Hitungan kendaraan dari computer vision disatukan dengan sensor PM dan Gas lokal. Karena vision membaca per menit, PM dan gas dirata-ratakan per menit (khusus berkas ini). Satu baris = satu menit pencatatan vision.",
            ex.COL_COMBINED, t0, t1, len(rows),
            ["Rata-rata per menit dihitung dari semua pembacaan sensor yang masuk pada menit itu (waktu ukur sensor, UTC dikonversi ke WIB).",
             "Hanya menit yang tercatat oleh vision yang menjadi baris; data sensor pada menit tanpa pencatatan vision tidak tampil di sini (ada di unduhan PM & Gas)."]
            + _fill_note(gap)[:1] + ["Kolom *_openmeteo adalah data model Open-Meteo, terpisah dari sensor lokal."], __version__), t0, t1)

    @app.get("/api/export/database.zip")
    def export_db():
        analytics.flush()
        tmp = Path(tempfile.mkdtemp())
        storage.backup_to(tmp / "emisisense.db"); pg.backup_to(tmp / "pmgas.db")
        buf_name = f"emisisense_database_{datetime.now():%Y%m%d_%H%M}.zip"
        import io, zipfile
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
            z.write(tmp / "emisisense.db", "emisisense.db"); z.write(tmp / "pmgas.db", "pmgas.db")
            z.writestr("KETERANGAN.txt", "\ufeff" + ex.keterangan(
                "Salinan seluruh database", "Salinan lengkap dua basis data SQLite sistem ini (dibuka dengan DB Browser for SQLite atau pustaka sqlite3).",
                ex.COL_DB, None, None, 0, ["Berisi SEMUA data tanpa pembersihan/pengisian; pilihan rentang jam tidak berlaku."], __version__))
        shutil.rmtree(tmp, ignore_errors=True)
        return Response(out.getvalue(), mimetype="application/zip", headers={"Content-Disposition": f'attachment; filename="{buf_name}"'})

    return app
