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
