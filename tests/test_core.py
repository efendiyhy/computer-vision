import json
import http.server, subprocess, sys, threading, time
from pathlib import Path
import cv2
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from emisisense_vision import updater
from emisisense_vision.analytics import Analytics, density_level
from emisisense_vision.config import Config, DEFAULT_STREAM_URL
from emisisense_vision.detector import Detection, MotionDetector, iou, nms
from emisisense_vision import reader as rd
from emisisense_vision.reader import SourceError, open_source
from emisisense_vision.storage import Storage
from emisisense_vision.tracker import Tracker
from emisisense_vision.weather import describe

W, H = 800, 450


def make_cfg(tmp_path):
    c = Config(Path(tmp_path) / "c.json")
    c.update({"log_dir": str(Path(tmp_path) / "data")}, save=False)
    return c


def make_an(cfg):
    return Analytics(cfg, storage=Storage(Path(cfg["log_dir"])))


def run(an, tr, frames):
    for t, dets in frames:
        tracks = tr.step(dets, t)
        an.update(tracks, tr.dead, t, (W, H))
    # akhiri: beri waktu agar trek yang hilang ditutup
    t_end = frames[-1][0]
    for k in range(1, 8):
        tracks = tr.step([], t_end + k * 0.5)
        an.update(tracks, tr.dead, t_end + k * 0.5, (W, H))
    return an.snapshot()


def test_default_cctv_link_kept(tmp_path):
    assert make_cfg(tmp_path)["source"] == DEFAULT_STREAM_URL
    assert "cctvmalang.24hour.id" in DEFAULT_STREAM_URL


def test_tracker_low_fps_keeps_identity():
    """Sumber CCTV 3 fps: kendaraan bergerak cepat tetap satu ID."""
    tr, ids = Tracker(), set()
    for i in range(14):
        t = i / 3.0
        d = Detection(100 + i * 40, 200, 170 + i * 40, 240, .8, "car")
        ids |= {x.id for x in tr.step([d], t) if x.confirmed}
    assert len(ids) == 1


def test_tracker_two_vehicles_separate_ids():
    tr, ids = Tracker(), set()
    for i in range(20):
        t = i / 5.0
        ds = [Detection(100 + i * 12, 150, 170 + i * 12, 190, .9, "car"),
              Detection(600 - i * 15, 300, 640 - i * 15, 330, .8, "motorbike")]
        ids |= {x.id for x in tr.step(ds, t) if x.confirmed}
    assert len(ids) == 2


def test_counts_by_line_with_types(tmp_path):
    cfg = make_cfg(tmp_path)
    cfg.update({"lines": [{"id": "A", "name": "Garis A", "p1": [0.0, 0.55], "p2": [1.0, 0.55], "dir1": "Maju", "dir2": "Mundur"}]}, save=False)
    an, tr = make_an(cfg), Tracker()
    frames = []
    for i in range(30):
        t = i / 6
        frames.append((t, [Detection(300, 80 + i * 10, 380, 130 + i * 10, .9, "car"),
                           Detection(550, 60 + i * 9, 590, 110 + i * 9, .7, "motorbike")]))
    s = run(an, tr, frames)
    assert s["total"] == 2 and s["totals"]["car"] == 1 and s["totals"]["motorbike"] == 1
    assert s["speed"]["n"] >= 1


def test_counts_even_when_line_misplaced(tmp_path):
    """Garis di tempat yang salah: kendaraan tetap terhitung lewat bukti gerak (di luar garis)."""
    cfg = make_cfg(tmp_path)
    cfg.update({"lines": [{"id": "A", "name": "Garis A", "p1": [0.0, 0.02], "p2": [1.0, 0.02], "dir1": "Maju", "dir2": "Mundur"}]}, save=False)
    an, tr = make_an(cfg), Tracker()
    frames = [(i / 5, [Detection(200 + i * 14, 250, 280 + i * 14, 300, .8, "car")]) for i in range(24)]
    s = run(an, tr, frames)
    assert s["total"] == 1
    assert any(l.get("free") and l["d1"] + l["d2"] == 1 for l in s["lines"])


def test_parked_vehicle_not_counted(tmp_path):
    cfg = make_cfg(tmp_path)
    an, tr = make_an(cfg), Tracker()
    frames = [(i / 5, [Detection(300, 250, 380, 300, .9, "car")]) for i in range(40)]
    assert run(an, tr, frames)["total"] == 0


def test_no_double_count_on_jitter(tmp_path):
    cfg = make_cfg(tmp_path)
    an, tr = make_an(cfg), Tracker()
    y = 0.62 * H
    frames = [(i / 5, [Detection(300, y - 40 + (6 if i % 2 else -6), 380, y + 10 + (6 if i % 2 else -6), .9, "car")]) for i in range(40)]
    assert run(an, tr, frames)["total"] <= 1


def test_motion_detector_finds_moving_block():
    md = MotionDetector()
    poly = [[0, 0], [1, 0], [1, 1], [0, 1]]
    found = []
    for i in range(30):
        f = np.full((H, W, 3), 90, np.uint8)
        x = 100 + i * 15
        cv2.rectangle(f, (x, 200), (x + 90, 260), (30, 60, 200), -1)
        found = md.blobs(f, poly)
    assert found, "objek bergerak harus terdeteksi sebagai blob"


def test_iou_nms():
    a, b = Detection(0, 0, 10, 10, .9, "car"), Detection(1, 1, 11, 11, .5, "car")
    assert iou(a, b) > .6 and len(nms([a, b])) == 1


def test_storage_roundtrip_and_restart(tmp_path):
    cfg = make_cfg(tmp_path)
    st = Storage(Path(cfg["log_dir"]))
    st.add_event({"t": time.time(), "cls": "car", "id": 1, "line": "A", "dir": "Maju", "speed": 30.0, "first": True, "via": "garis"}, "uji")
    assert st.stats()["events"] == 1
    st.close()
    assert Storage(Path(cfg["log_dir"])).stats()["events"] == 1
    assert "cara_hitung" in Storage(Path(cfg["log_dir"])).events_csv().splitlines()[0]


def test_density_and_weather():
    assert density_level(0)[1] == 0 and density_level(20)[1] == 4
    assert describe(0, True)["icon"] == "clear" and describe(95, True)["icon"] == "storm"


class _Mjpeg(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
        self.end_headers()
        try:
            for i in range(40):
                f = np.full((240, 320, 3), 80, np.uint8)
                cv2.rectangle(f, (10 + i * 5, 100), (60 + i * 5, 140), (0, 0, 220), -1)
                ok, jpg = cv2.imencode(".jpg", f)
                self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: %d\r\n\r\n" % len(jpg) + jpg.tobytes() + b"\r\n")
                time.sleep(0.1)
        except Exception:
            pass


def test_reader_sniffs_mjpeg():
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Mjpeg)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        r = rd.test_source(f"http://127.0.0.1:{srv.server_address[1]}/cam", seconds=2.5)
        assert r["ok"] and r["width"] == 320 and r["fps"] > 3, r
    finally:
        srv.shutdown()


def test_reader_errors_are_readable():
    for bad in ("", "/tmp/tidak-ada.mp4"):
        try:
            open_source(bad)
            assert False
        except SourceError as e:
            assert str(e)


def _git(cwd, *a):
    return subprocess.run(["git", *a], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def test_updater_check_and_apply(tmp_path, monkeypatch):
    origin, work = tmp_path / "origin", tmp_path / "work"
    origin.mkdir()
    _git(origin, "init", "-q", "-b", "main")
    _git(origin, "config", "user.email", "t@t"); _git(origin, "config", "user.name", "t")
    (origin / "a.txt").write_text("1"); _git(origin, "add", "."); _git(origin, "commit", "-qm", "awal")
    subprocess.run(["git", "clone", "-q", str(origin), str(work)], check=True)
    monkeypatch.setattr(updater, "ROOT", work)
    monkeypatch.setattr(updater, "BRANCH", "main")
    updater._cache.update(t=0, data=None)
    assert updater.check(force=True)["available"] is False
    (origin / "a.txt").write_text("2"); _git(origin, "commit", "-qam", "perubahan baru")
    r = updater.check(force=True)
    assert r["available"] and r["behind"] == 1 and r["changes"][0]["subject"] == "perubahan baru"
    res = updater.apply()
    assert res["ok"] and (work / "a.txt").read_text() == "2"
    assert updater.check(force=True)["available"] is False


def test_youtube_link_is_resolved(monkeypatch, tmp_path):
    from emisisense_vision import resolver
    vid = tmp_path / "v.avi"
    w = cv2.VideoWriter(str(vid), cv2.VideoWriter_fourcc(*"MJPG"), 10, (160, 120))
    for i in range(20):
        w.write(np.full((120, 160, 3), i * 5, np.uint8))
    w.release()
    monkeypatch.setattr(resolver, "resolve", lambda url, max_height=720, force=False: {"url": str(vid), "title": "Jalan", "live": False, "height": 720, "protocol": "https"})
    assert resolver.is_youtube("https://youtu.be/abc") and resolver.is_youtube("https://www.youtube.com/watch?v=abc")
    assert not resolver.is_youtube("https://cctvmalang.24hour.id/x")
    rd0 = open_source("https://www.youtube.com/watch?v=abc")
    try:
        ok, frame, _ = rd0.read()
        assert ok and "YouTube" in rd0.desc and rd0.is_file
    finally:
        rd0.close()


def test_youtube_errors_are_readable(monkeypatch):
    from emisisense_vision import resolver
    def boom(*a, **k): raise resolver.ResolveError("Tidak dapat menghubungi YouTube dari server ini.")
    monkeypatch.setattr(resolver, "resolve", boom)
    try:
        open_source("https://youtu.be/abc")
        assert False
    except SourceError as e:
        assert "YouTube" in str(e)
    assert "bot" in resolver._friendly("ERROR: Sign in to confirm you're not a bot")


def _one_way_cfg(tmp_path):
    cfg = make_cfg(tmp_path)
    # p1 kiri -> p2 kanan: panah menunjuk ke BAWAH layar
    cfg.update({"lines": [{"id": "A", "name": "Garis A", "dir": "Mendekat", "p1": [0.0, 0.55], "p2": [1.0, 0.55]}], "count_outside": False}, save=False)
    return cfg


def test_line_counts_only_arrow_direction(tmp_path):
    down = [(i / 6, [Detection(300, 80 + i * 10, 380, 130 + i * 10, .9, "car")]) for i in range(30)]
    up = [(i / 6, [Detection(300, 330 - i * 10, 380, 380 - i * 10, .9, "car")]) for i in range(30)]
    cfg = _one_way_cfg(tmp_path)
    assert run(make_an(cfg), Tracker(), down)["total"] == 1
    assert run(make_an(cfg), Tracker(), up)["total"] == 0, "lawan arah panah tidak boleh dihitung"


def test_legacy_two_direction_line_becomes_two_lines():
    from emisisense_vision.config import normalize_lines
    out = normalize_lines([{"id": "A", "name": "Garis A", "p1": [0, .5], "p2": [1, .5], "dir1": "Maju", "dir2": "Mundur"}])
    assert len(out) == 2 and {l["dir"] for l in out} == {"Maju", "Mundur"}
    assert len({l["color"] for l in out}) == 2 and all(l["id"] for l in out)


def test_windrose_and_compass():
    from emisisense_vision.wind import compass, windrose
    assert compass(0)["abbr"] == "U" and compass(135)["abbr"] == "TG" and compass(359)["abbr"] == "U" and compass(None) is None
    w = windrose([(8, 90)] * 6 + [(20, 270)] * 2 + [(0.2, 10)] * 2)
    assert w["n"] == 10 and w["calm_pct"] == 20.0
    assert w["prevailing"]["abbr"] == "T" and round(w["prevailing"]["pct"]) == 60
    assert abs(sum(s["pct"] for s in w["sectors"]) + w["calm_pct"] - 100) < 0.1


def test_windrose_storage(tmp_path):
    import time as _t
    st = Storage(str(tmp_path / "w.db"))
    loc = {"lat": -7.98, "lon": 112.63}
    now = int(_t.time() // 3600 * 3600)
    st.upsert_wind([(now - 3600, 10, 90, 15), (now - 7200, 12, 100, 18), (now - 90 * 3600, 5, 270, 9)], loc)
    w = st.windrose(24, loc)
    assert w["n"] == 2 and w["prevailing"]["abbr"] == "T"
    assert st.windrose(24 * 7, loc)["n"] == 3


def test_no_lines_means_no_counting(tmp_path):
    cfg = make_cfg(tmp_path)
    cfg.update({"lines": []}, save=False)
    assert cfg["lines"] == []
    frames = [(i / 6, [Detection(300, 80 + i * 10, 380, 130 + i * 10, .9, "car")]) for i in range(30)]
    assert run(make_an(cfg), Tracker(), frames)["total"] == 0


def test_riders_are_not_pedestrians():
    from emisisense_vision.detector import drop_riders
    bike = Detection(100, 150, 160, 220, .8, "motorbike")
    rider = Detection(110, 90, 150, 190, .7, "person")          # menumpang di motor
    walker = Detection(400, 100, 430, 190, .7, "person")
    kept = drop_riders([rider, walker], [bike])
    assert kept == [walker]


def test_pedestrians_counted_separately(tmp_path):
    cfg = make_cfg(tmp_path)
    cfg.update({"lines": [{"id": "A", "name": "Garis A", "dir": "Mendekat", "p1": [0.0, 0.55], "p2": [1.0, 0.55]}]}, save=False)
    an, tr = make_an(cfg), Tracker()
    car = [Detection(300, 80 + i * 10, 380, 130 + i * 10, .9, "car") for i in range(30)]
    man = [Detection(600, 70 + i * 10, 620, 130 + i * 10, .8, "person") for i in range(30)]
    s = run(an, tr, [(i / 6, [car[i], man[i]]) for i in range(30)])
    assert s["total"] == 1 and s["people"]["total"] == 1 and s["totals"]["person"] == 1
    assert s["lines"][0]["count"] == 1 and s["lines"][0]["people"] == 1
    assert s["speed"]["n"] == 1, "kecepatan pejalan kaki tidak masuk statistik kendaraan"


def test_pedestrian_storage_roundtrip(tmp_path):
    st = Storage(tmp_path / "p")
    st.upsert_minute({"t": 600, "pcu": 1.0, "sp_sum": 0.0, "sp_n": 0, "car": 2, "person": 5}, {}, "x")
    m = st.get_minute(600)
    assert m["person"] == 5 and m["total"] == 2
    assert "person" in st.minutes_csv().splitlines()[0]
    assert st.history(24, 3600)[-1].keys() >= {"person"}


def test_watermark_is_burned_into_frames():
    from emisisense_vision.pipeline import draw_watermark
    img = np.full((540, 960, 3), 120, np.uint8)
    out = draw_watermark(img.copy())
    assert (out[520:536, 780:956] == 255).any() and (out[:400] == 120).all() and (out[:, :600] == 120).all()


def test_recorder_writes_playable_file(tmp_path):
    import cv2 as _cv
    from emisisense_vision.recorder import NAME_RE, Recorder
    cfg = make_cfg(tmp_path)
    frame = np.full((240, 320, 3), 90, np.uint8)
    rec = Recorder(tmp_path / "rec", lambda overlay: frame, cfg)
    assert rec.start(True)["recording"]
    time.sleep(2.2)
    assert rec.stop()["recording"] is False
    items = rec.list()
    assert len(items) == 1 and items[0]["bytes"] > 500 and NAME_RE.match(items[0]["name"])
    cap = _cv.VideoCapture(str(rec.dir / items[0]["name"]))
    ok, fr = cap.read()
    assert ok and fr.shape[:2] == (240, 320)
    assert rec.path_of("../../etc/passwd") is None and not rec.delete("nama-ngawur.mp4")
    assert rec.delete(items[0]["name"]) and rec.list() == []


def _net():
    from importlib.machinery import SourceFileLoader
    return SourceFileLoader("emisisense_net", str(Path(__file__).resolve().parent.parent / "hotspot" / "emisisense-net")).load_module()


def test_net_terse_parsing_and_validation():
    n = _net()
    assert n.terse(r"*:Lab\:AQHI:82:WPA2") == ["*", "Lab:AQHI", "82", "WPA2"]
    assert n.terse(":Kampus Guest:45:") == ["", "Kampus Guest", "45", ""]
    assert n.valid_ssid("Lab AQHI") and not n.valid_ssid("") and not n.valid_ssid("x" * 33) and not n.valid_ssid("a\nb")
    assert n.valid_pass("") and n.valid_pass("12345678") and not n.valid_pass("1234567") and not n.valid_pass("x" * 64)


def test_net_default_config_is_hotspot_first(monkeypatch, tmp_path):
    n = _net()
    monkeypatch.setattr(n, "CFG", str(tmp_path / "net.json"))
    monkeypatch.setattr(n, "wifi_dev", lambda: None)
    cfg = n.load_cfg()
    assert cfg["mode"] == "hotspot" and cfg["ip"] == "10.42.0.1/24" and len(cfg["password"]) >= 8 and cfg["ssid"].startswith("EmisiSense-")


def test_net_settime_rejects_nonsense():
    n = _net()
    assert n.cmd_settime("abc") == 2 and n.cmd_settime("100") == 2


# ---------------------------------------------------------------- sinkronisasi cuaca (data offline, cuaca menyusul)
def _fake_getter(now, hours=6):
    """Tiruan Open-Meteo: data per jam untuk `hours` jam terakhir (waktu UTC, unixtime)."""
    base = int(now // 3600 * 3600)
    ts = [base - i * 3600 for i in range(hours, -1, -1)]

    def get(url, params, timeout=10.0):
        assert params["timeformat"] == "unixtime" and params["timezone"] == "GMT"
        if "air-quality" in url:
            return {"hourly": {"time": ts, "pm2_5": [10 + i for i in range(len(ts))], "us_aqi": [50] * len(ts)}}
        return {"hourly": {"time": ts + [base + 3600], "temperature_2m": [20.0 + i for i in range(len(ts) + 1)],
                           "wind_speed_10m": [5.0] * (len(ts) + 1), "wind_direction_10m": [90.0] * (len(ts) + 1)}}
    return get


def test_fetch_hourly_drops_future_and_merges_air():
    from emisisense_vision.weather import fetch_hourly
    now = 1_800_000_000.0
    out, warns = fetch_hourly({"lat": -7.9, "lon": 112.6}, now - 4 * 3600, now, getter=_fake_getter(now))
    assert max(out) <= now and not warns
    h = out[max(out)]
    assert h["temperature_2m"] and h["pm2_5"] and h["us_aqi"] == 50


def test_fetch_hourly_survives_air_failure_and_warns_when_too_old():
    from emisisense_vision.weather import fetch_hourly
    now = 1_800_000_000.0
    base = _fake_getter(now)

    def flaky(url, params, timeout=10.0):
        if "air-quality" in url:
            raise OSError("down")
        return base(url, params, timeout)
    out, warns = fetch_hourly({"lat": 0, "lon": 0}, now - 120 * 86400, now, getter=flaky)
    assert out and any("Kualitas udara" in w for w in warns) and any("92" in w for w in warns)


def test_backfill_fills_only_empty_minutes_and_is_idempotent(tmp_path):
    cfg = make_cfg(tmp_path)
    st = Storage(Path(cfg["log_dir"]))
    now = time.time()
    h0 = int(now // 3600 * 3600) - 3600                      # jam penuh yang sudah lewat
    base = {"car": 1, "motorbike": 0, "bus": 0, "truck": 0, "bicycle": 0, "other": 0, "person": 0, "pcu": 1.0, "sp_sum": 0, "sp_n": 0}
    st.upsert_minute({**base, "t": h0 + 60}, None)           # direkam offline: tanpa cuaca
    st.upsert_minute({**base, "t": h0 + 120}, None)
    st.upsert_minute({**base, "t": h0 + 180}, {"current": {"temperature_2m": 33.3, "wind_speed_10m": 2.0}, "air_quality": {}})   # sudah punya cuaca nyata
    assert st.wx_pending()["minutes"] == 2 and st.stats()["wx_pending"] == 2
    hourly = {h0: {"temperature_2m": 25.0, "relative_humidity_2m": 80, "wind_speed_10m": 7.0, "wind_direction_10m": 120.0, "pm2_5": 12.0}}
    loc = {"lat": -7.9, "lon": 112.6, "name": "Uji"}
    r = st.backfill_weather(hourly, loc)
    assert r == {"minutes_filled": 2, "hours_used": 1}
    assert st.wx_pending()["minutes"] == 0
    assert st.get_minute(h0 + 60)["temp"] == 25.0 and st.get_minute(h0 + 60)["wx_sync"] == 1
    assert st.get_minute(h0 + 180)["temp"] == 33.3 and not st.get_minute(h0 + 180)["wx_sync"]     # data nyata tidak ditimpa
    assert st.backfill_weather(hourly, loc)["minutes_filled"] == 0                              # aman diulang
    assert "cuaca_sinkron" in st.minutes_csv().splitlines()[0]


def test_stale_or_errored_weather_not_attached_offline(tmp_path):
    from emisisense_vision.analytics import _wx_fresh
    from datetime import datetime, timedelta
    ok = {"current": {"temperature_2m": 1}, "updated": datetime.now().astimezone().isoformat(timespec="seconds")}
    assert _wx_fresh(ok)
    assert not _wx_fresh({**ok, "error": "URLError"})
    assert not _wx_fresh({**ok, "updated": (datetime.now().astimezone() - timedelta(hours=2)).isoformat(timespec="seconds")})
    assert not _wx_fresh({}) and not _wx_fresh({"current": {}})


def test_sync_endpoint_demo_and_net_message(tmp_path):
    from emisisense_vision.server import create_app
    app = create_app(demo=True, config_path=str(Path(tmp_path) / "c.json"))
    app.cfg.update({"log_dir": str(Path(tmp_path) / "d")}, save=False)
    c = app.test_client()
    s = c.get("/api/sync").get_json()
    assert "pending" in s and s["last"] is None
    r = c.post("/api/sync").get_json()
    assert r["ok"] and "message" in r and r["pending_after"] <= r["pending_before"]
    assert c.get("/api/sync").get_json()["last"]["ok"]
    n = c.get("/api/net").get_json()
    assert n["available"] is False and n["message"]


# ---------------------------------------------------------------- sensor PM & Gas (ESP32), sinkronisasi dan pengisian data kosong
def _pg(tmp_path):
    from emisisense_vision.pmgas import PmGasStore
    return PmGasStore(Path(tmp_path) / "pg")


def _pkt(kind, eid, ts, **vals):
    if kind == "pm":
        m = {"pm1_pms1": 5, "pm25_pms1": 10, "pm10_pms1": 14, "pm1_pms2": 7, "pm25_pms2": 12, "pm10_pms2": 16, "suhu": 30, "kelembapan": 60}
    else:
        m = {"co_ppm": 1.0, "co2_ppm": 500, "no2_ppm": 0.05, "suhu_c": 31, "rh_pct": 58, "red_v": 1, "nox_v": 1, "red_ratio": 1, "nox_ratio": 1}
    m.update(vals)
    return {"device_type": kind, "event_id": eid, "device_id": kind + "1", "sample_name": "s", "timestamp": ts, "uptime_ms": 1, "measurements": m}


T0 = 1_800_000_000          # detik UTC (kelipatan 60)
def _iso(sec):
    from datetime import datetime, timezone
    return datetime.fromtimestamp(sec, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def test_pmgas_ingest_validation_and_duplicates(tmp_path):
    import pytest
    pg = _pg(tmp_path)
    assert pg.ingest(_pkt("pm", "a", _iso(T0)), now=T0)["duplicate"] is False
    assert pg.ingest(_pkt("pm", "a", _iso(T0)), now=T0)["duplicate"] is True
    for bad in ({"device_type": "x"}, {**_pkt("pm", "b", _iso(T0)), "measurements": {"pm1_pms1": "abc"}}, {**_pkt("pm", "", _iso(T0))}):
        with pytest.raises(ValueError):
            pg.ingest(bad)
    assert pg.stats()["pm"] == 1


def test_pmgas_merge_by_sensor_time_and_forward_fill(tmp_path):
    pg = _pg(tmp_path)
    # detik 0..5: PM ada semua; Gas hilang pada detik 2 dan 3; paket Gas diterima terlambat (backlog) tetap dipasangkan menurut waktu ukur
    for s in range(6):
        pg.ingest(_pkt("pm", f"p{s}", _iso(T0 + s), pm25_pms1=10 + s, pm25_pms2=10 + s), now=T0 + 100)
        if s not in (2, 3):
            pg.ingest(_pkt("gas", f"g{s}", _iso(T0 + s), co2_ppm=500 + s), now=T0 + 200)
    from emisisense_vision.pmgas import MERGED_COLS
    ix = {c: i for i, c in enumerate(MERGED_COLS)}
    rows = pg.merged(gap=300)
    assert len(rows) == 6 and [r[ix["sync_status"]] for r in rows] == ["LENGKAP", "LENGKAP", "HANYA_PM", "HANYA_PM", "LENGKAP", "LENGKAP"]
    assert rows[2][ix["co2_ppm"]] == 501 and rows[3][ix["co2_ppm"]] == 501              # diisi nilai sebelumnya
    assert "co2_ppm" in rows[2][ix["filled_columns"]] and rows[1][ix["filled_columns"]] == ""
    assert rows[4][ix["co2_ppm"]] == 504                                                   # nilai asli kembali
    raw = pg.merged(gap=300, fill=False)
    assert raw[2][ix["co2_ppm"]] is None and raw[2][ix["filled_columns"]] == ""
    assert rows[0][ix["time_basis"]] == "SENSOR"


def test_pmgas_fill_respects_gap_and_time_range_lookback(tmp_path):
    pg = _pg(tmp_path)
    from emisisense_vision.pmgas import MERGED_COLS
    ix = {c: i for i, c in enumerate(MERGED_COLS)}
    pg.ingest(_pkt("gas", "g0", _iso(T0), co2_ppm=777), now=T0)
    for s in (10, 100, 1000):
        pg.ingest(_pkt("pm", f"p{s}", _iso(T0 + s)), now=T0 + s)
    rows = pg.merged(gap=300)
    by = {r[ix["time_basis"]] and r[ix["waktu_utc"]]: r for r in rows}
    assert by[_iso(T0 + 100)][ix["co2_ppm"]] == 777            # 100 dtk <= 300
    assert by[_iso(T0 + 1000)][ix["co2_ppm"]] is None          # 1000 dtk > 300: tetap kosong
    sub = pg.merged(T0 + 50, T0 + 500, gap=300)                # rentang jam: nilai sebelum awal rentang tetap jadi sumber isian
    assert len(sub) == 1 and sub[0][ix["co2_ppm"]] == 777
    assert len(pg.raw_rows(T0 + 50, T0 + 500)) == 1 and len(pg.raw_rows(None, None, "gas")) == 1


def test_pmgas_invalid_sensor_clock_falls_back_to_received(tmp_path):
    pg = _pg(tmp_path)
    pg.ingest(_pkt("pm", "x", "1970-01-01T00:00:03Z"), now=T0 + 5)
    from emisisense_vision.pmgas import MERGED_COLS
    r = pg.merged()[0]
    assert r[MERGED_COLS.index("time_basis")] == "RECEIVED"


def test_pmgas_minute_average_and_combined_with_vision(tmp_path):
    pg = _pg(tmp_path)
    for s in range(60):                                           # menit T0: PM2,5 = 10 dan 30 bergantian -> rata-rata 20
        pg.ingest(_pkt("pm", f"p{s}", _iso(T0 + s), pm25_pms1=10 if s % 2 else 30, pm25_pms2=10 if s % 2 else 30), now=T0 + s)
        pg.ingest(_pkt("gas", f"g{s}", _iso(T0 + s), co_ppm=2.0), now=T0 + s)
    ser = pg.minute_series([T0, T0 + 60, T0 + 60 * 20])
    assert ser[T0]["v"]["pm25"] == 20 and ser[T0]["n_pm"] == 60 and ser[T0]["filled"] == []
    assert ser[T0 + 60]["v"]["pm25"] == 20 and "pm25" in ser[T0 + 60]["filled"]      # menit tanpa data: dari menit sebelumnya
    assert ser[T0 + 60 * 20]["v"]["pm25"] is None                                      # terlalu jauh dari data (> 300 dtk)
    from emisisense_vision.combined import HEAD, combined_rows
    vrow = {"minute": T0, "car": 3, "motorbike": 9, "bus": 0, "truck": 1, "bicycle": 0, "other": 0, "person": 2, "total": 13, "pcu": 7.0,
            "sp_sum": 100.0, "sp_n": 4, "temp": 28.0, "rh": 70.0, "rain": 0.0, "wind": 5.0, "wind_dir": 90.0, "pm2_5": 15.0, "pm10": 20.0,
            "no2": 9.0, "co": 100.0, "us_aqi": 50}
    out = combined_rows([vrow], pg, 300)[0]
    d = dict(zip(HEAD, out))
    assert d["motorbike"] == 9 and d["pm25_ugm3"] == 20 and d["co_ppm"] == 2 and d["n_pm"] == 60 and d["pm2_5_openmeteo"] == 15.0 and d["kecepatan_rata_kmh"] == 25.0


def test_export_zip_range_parsing_and_keterangan(tmp_path):
    from emisisense_vision import export as ex
    t0, t1 = ex.parse_range({"from": "2026-11-20T08:00", "to": "2026-11-20T09:30"})
    assert t1 - t0 == 90 * 60 + 60                                  # jam akhir ikut sampai menit itu selesai
    d0, d1 = ex.parse_range({"from": "2026-11-20", "to": "2026-11-20"})
    assert d1 - d0 == 86400 and ex.parse_range({}) == (None, None) and ex.parse_range({"from": "ngawur"})[0] is None
    txt = ex.keterangan("Judul", "Uraian data", [("kolom_a", "Arti A")], t0, t1, 5, ["catatan 1"])
    assert "DATA APA INI" in txt and "kolom_a: Arti A" in txt and "WIB" in txt and "catatan 1" in txt
    import zipfile, io
    resp = ex.zip_response("tes data", "a,b\n1,2\n", txt, t0, t1)
    z = zipfile.ZipFile(io.BytesIO(resp.get_data()))
    assert sorted(z.namelist()) == ["KETERANGAN.txt", "tes_data.csv"] and ".zip" in resp.headers["Content-Disposition"]


def test_ingest_endpoint_bypasses_password_and_exports_are_zip(tmp_path):
    from emisisense_vision.server import create_app
    app = create_app(demo=False, config_path=str(Path(tmp_path) / "c.json"), password="rahasia")
    app.cfg.update({"log_dir": str(Path(tmp_path) / "d")}, save=False)
    c = app.test_client()
    assert c.get("/api/state").status_code == 401                                     # dashboard tetap dikunci
    r = c.post("/api/ingest", data=json.dumps(_pkt("pm", "z1", _iso(int(time.time())))), content_type="application/json")
    assert r.status_code == 200 and r.get_json()["ok"] and r.get_json()["duplicate"] is False
    assert c.post("/api/ingest", data="{bad", content_type="application/json").status_code == 400
    auth = {"Authorization": "Basic " + __import__("base64").b64encode(b"u:rahasia").decode()}
    st = c.get("/api/pmgas", headers=auth).get_json()
    assert st["latest"]["pm"]["online"] and st["stats"]["pm"] == 1
    for name in ("pmgas-gabungan", "pmgas-mentah", "sinkron-kendaraan-pmgas", "minutes", "events", "weather", "database"):
        resp = c.get(f"/api/export/{name}.zip?from=2020-01-01T00:00&to=2099-01-01T00:00&gap=60", headers=auth)
        assert resp.status_code == 200 and "KETERANGAN.txt" in __import__("zipfile").ZipFile(__import__("io").BytesIO(resp.get_data())).namelist(), name
