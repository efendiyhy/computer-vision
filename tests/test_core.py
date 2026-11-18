import sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from emisisense_vision.analytics import Analytics, density_level
from emisisense_vision.config import Config, DEFAULT_STREAM_URL
from emisisense_vision.detector import Detection
from emisisense_vision.storage import Storage
from emisisense_vision.tracker import Tracker
from emisisense_vision.weather import parse_forecast, describe


def make_cfg(tmp_path):
    c = Config(Path(tmp_path) / "c.json")
    c.update({"log_dir": str(Path(tmp_path) / "data")}, save=False)
    return c


def make_an(cfg):
    return Analytics(cfg, storage=Storage(Path(cfg["log_dir"])))


def test_default_cctv_link_kept(tmp_path):
    assert make_cfg(tmp_path)["source"] == DEFAULT_STREAM_URL
    assert "cctvmalang.24hour.id" in DEFAULT_STREAM_URL


def test_tracker_counts_and_speed(tmp_path):
    cfg = make_cfg(tmp_path)
    an, tr = make_an(cfg), Tracker()
    W, H = 960, 540
    diag = (W * W + H * H) ** 0.5
    # dua kendaraan berbeda melintasi garis A (y=0.62*H) dari atas ke bawah
    for i in range(80):
        t = i / 20
        dets = [Detection(300, 100 + i * 6, 380, 150 + i * 6, .9, "car"),
                Detection(600, 120 + i * 5, 650, 160 + i * 5, .8, "motorbike")]
        tracks = tr.step(dets, t, diag)
        an.update(tracks, t, (W, H))
    s = an.snapshot()
    assert s["total"] == 2 and s["totals"]["car"] == 1 and s["totals"]["motorbike"] == 1
    assert s["lines"][0]["d1"] + s["lines"][0]["d2"] == 2
    assert s["speed"]["n"] == 2 and s["speed"]["avg"] > 0
    assert len({t["id"] for t in s["tracks"]}) == 2   # ID stabil


def test_no_double_count_on_jitter(tmp_path):
    cfg = make_cfg(tmp_path)
    an, tr = make_an(cfg), Tracker()
    W, H = 960, 540
    diag = (W * W + H * H) ** 0.5
    y = 0.62 * H
    for i in range(60):
        t = i / 20
        yy = y + (6 if i % 2 else -6)       # bergetar di sekitar garis
        an.update(tr.step([Detection(300, yy - 40, 380, yy + 10, .9, "car")], t, diag), t, (W, H))
    assert an.snapshot()["total"] <= 1


def test_density_levels():
    assert density_level(0)[1] == 0 and density_level(20)[1] == 4


def test_weather_parse_and_codes():
    js = {"current": {"time": "2026-11-18T10:00", "temperature_2m": 27.1, "weather_code": 61, "is_day": 1},
          "current_units": {"temperature_2m": "°C"},
          "hourly": {"time": [f"2026-11-18T{h:02d}:00" for h in range(8, 20)], "temperature_2m": [26] * 12,
                     "precipitation_probability": [40] * 12, "precipitation": [0.2] * 12, "weather_code": [3] * 12}}
    out = parse_forecast(js)
    assert out["current"]["desc"]["text"] == "Hujan ringan"
    assert out["hourly"][0]["time"].endswith("10:00")
    assert describe(0, 0)["icon"] == "clear_night"


def test_config_roundtrip(tmp_path):
    c = make_cfg(tmp_path)
    c.update({"confidence": 0.5, "lines": [{"id": "Z", "name": "Z", "p1": [0, 0], "p2": [1, 1]}]})
    c2 = make_cfg(tmp_path)
    assert c2["confidence"] == 0.5 and c2["lines"][0]["id"] == "Z"


def drive(an, tr, n=80, y0=100):
    W, H = 960, 540
    diag = (W * W + H * H) ** 0.5
    for i in range(n):
        t = i / 20
        an.update(tr.step([Detection(300, y0 + i * 6, 380, y0 + 50 + i * 6, .9, "car")], t, diag), t, (W, H))


def test_data_persisted_and_exported(tmp_path):
    cfg = make_cfg(tmp_path)
    an = make_an(cfg)
    drive(an, Tracker())
    an.flush()
    st = an.storage
    stats = st.stats()
    assert stats["events"] >= 1 and stats["minutes"] >= 1 and stats["errors"] == 0
    ev = st.events_csv().splitlines()
    assert ev[0].startswith("waktu,id_kendaraan") and len(ev) >= 2 and ",car," in ev[1]
    mn = st.minutes_csv().splitlines()
    assert mn[0].startswith("waktu_menit,car") and len(mn) >= 2
    hist = st.history(1, 300)
    assert sum(h["car"] for h in hist) == 1


def test_restart_continues_same_minute(tmp_path):
    cfg = make_cfg(tmp_path)
    an1 = make_an(cfg)
    drive(an1, Tracker())
    an1.flush()
    an1.storage.close()
    an2 = make_an(cfg)                    # "restart"
    drive(an2, Tracker())                 # kendaraan baru pada menit yang sama
    an2.flush()
    row = an2.storage.history(1, 300)
    assert sum(h["car"] for h in row) == 2   # dilanjutkan, tidak ditimpa


def test_weather_row_saved(tmp_path):
    st = Storage(tmp_path / "d")
    st.add_weather({"current": {"temperature_2m": 27.5, "weather_code": 3}, "air_quality": {"pm2_5": 12.0, "us_aqi": 50},
                    "location": {"lat": -7.9, "lon": 112.6, "name": "Malang"}})
    csv = st.weather_csv().splitlines()
    assert len(csv) == 2 and "27.5" in csv[1] and "Malang" in csv[1]
