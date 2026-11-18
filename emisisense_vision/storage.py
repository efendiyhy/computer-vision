"""Penyimpanan data deteksi: SQLite (mode WAL) di folder ``data/``.

Tabel
  events   - satu baris per kendaraan yang melintasi garis (waktu, jenis, garis, arah, kecepatan)
  minutes  - agregat per menit (jumlah per jenis, SMP, kecepatan) + cuaca/kualitas udara pada menit itu
  weather  - rekaman cuaca & kualitas udara dari Open-Meteo (tiap pembaruan)

Semua penulisan langsung di-commit; agregat menit di-flush berkala dan saat berhenti, serta dilanjutkan
(bukan ditimpa) bila aplikasi dihidupkan ulang pada menit yang sama.
"""
from __future__ import annotations

import csv
import io
import sqlite3
import threading
import time
from datetime import datetime
from pathlib import Path

CLASSES = ["car", "motorbike", "bus", "truck", "bicycle"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS events(
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, track_id INTEGER, cls TEXT, line TEXT, direction TEXT,
  speed_kmh REAL, is_first INTEGER, source TEXT);
CREATE INDEX IF NOT EXISTS ix_events_ts ON events(ts);
CREATE TABLE IF NOT EXISTS minutes(
  minute INTEGER PRIMARY KEY, car INTEGER DEFAULT 0, motorbike INTEGER DEFAULT 0, bus INTEGER DEFAULT 0,
  truck INTEGER DEFAULT 0, bicycle INTEGER DEFAULT 0, total INTEGER DEFAULT 0, pcu REAL DEFAULT 0,
  sp_sum REAL DEFAULT 0, sp_n INTEGER DEFAULT 0,
  temp REAL, rh REAL, rain REAL, wind REAL, pm2_5 REAL, pm10 REAL, co REAL, no2 REAL, us_aqi REAL, source TEXT);
CREATE TABLE IF NOT EXISTS weather(
  ts INTEGER PRIMARY KEY, temp REAL, rh REAL, apparent REAL, rain REAL, code INTEGER, cloud REAL, pressure REAL,
  wind REAL, wind_dir REAL, gust REAL, us_aqi REAL, pm2_5 REAL, pm10 REAL, co REAL, no2 REAL, so2 REAL, o3 REAL,
  lat REAL, lon REAL, location TEXT);
"""


def _iso(ts: float, secs=True) -> str:
    return datetime.fromtimestamp(ts).astimezone().isoformat(timespec="seconds" if secs else "minutes")


class Storage:
    def __init__(self, directory: Path, filename: str = "emisisense.db"):
        self.dir = Path(directory)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.path = self.dir / filename
        self._lock = threading.RLock()
        self._db = sqlite3.connect(str(self.path), check_same_thread=False, timeout=15)
        self._db.row_factory = sqlite3.Row
        with self._lock:
            self._db.execute("PRAGMA journal_mode=WAL")
            self._db.execute("PRAGMA synchronous=NORMAL")
            self._db.executescript(SCHEMA)
            self._db.commit()
        self.last_write = None
        self.errors = 0
        self._stats_cache = (0.0, {})

    # ------------------------------------------------------------ tulis
    def _exec(self, sql: str, args=()):
        try:
            with self._lock:
                self._db.execute(sql, args)
                self._db.commit()
            self.last_write = time.time()
            return True
        except sqlite3.Error:
            self.errors += 1
            return False

    def add_event(self, ev: dict, source: str = ""):
        self._exec("INSERT INTO events(ts,track_id,cls,line,direction,speed_kmh,is_first,source) VALUES(?,?,?,?,?,?,?,?)",
                   (ev["t"], ev["id"], ev["cls"], ev["line"], ev["dir"], ev["speed"], int(ev["first"]), source))

    def get_minute(self, minute: int) -> dict | None:
        with self._lock:
            r = self._db.execute("SELECT * FROM minutes WHERE minute=?", (minute,)).fetchone()
        return dict(r) if r else None

    def upsert_minute(self, m: dict, wx: dict | None, source: str = ""):
        cur, aq = (wx or {}).get("current") or {}, (wx or {}).get("air_quality") or {}
        vals = [m["t"]] + [m.get(c, 0) for c in CLASSES]
        total = sum(m.get(c, 0) for c in CLASSES)
        vals += [total, round(m["pcu"], 3), round(m["sp_sum"], 2), m["sp_n"], cur.get("temperature_2m"), cur.get("relative_humidity_2m"),
                 cur.get("precipitation"), cur.get("wind_speed_10m"), aq.get("pm2_5"), aq.get("pm10"), aq.get("carbon_monoxide"),
                 aq.get("nitrogen_dioxide"), aq.get("us_aqi"), source]
        self._exec("INSERT OR REPLACE INTO minutes(minute,car,motorbike,bus,truck,bicycle,total,pcu,sp_sum,sp_n,temp,rh,rain,wind,"
                   "pm2_5,pm10,co,no2,us_aqi,source) VALUES(" + ",".join("?" * 20) + ")", vals)

    def add_weather(self, data: dict):
        cur, aq, loc = data.get("current") or {}, data.get("air_quality") or {}, data.get("location") or {}
        if not cur:
            return
        self._exec("INSERT OR REPLACE INTO weather VALUES(" + ",".join("?" * 21) + ")",
                   (int(time.time() // 60 * 60), cur.get("temperature_2m"), cur.get("relative_humidity_2m"), cur.get("apparent_temperature"),
                    cur.get("precipitation"), cur.get("weather_code"), cur.get("cloud_cover"), cur.get("pressure_msl"),
                    cur.get("wind_speed_10m"), cur.get("wind_direction_10m"), cur.get("wind_gusts_10m"), aq.get("us_aqi"),
                    aq.get("pm2_5"), aq.get("pm10"), aq.get("carbon_monoxide"), aq.get("nitrogen_dioxide"), aq.get("sulphur_dioxide"),
                    aq.get("ozone"), loc.get("lat"), loc.get("lon"), loc.get("name")))

    # ------------------------------------------------------------ baca
    def stats(self) -> dict:
        now = time.time()
        if now - self._stats_cache[0] < 8 and self._stats_cache[1]:
            return {**self._stats_cache[1], "last_write": self.last_write and _iso(self.last_write), "errors": self.errors}
        with self._lock:
            ev = self._db.execute("SELECT COUNT(*) n, MIN(ts) a, MAX(ts) b FROM events").fetchone()
            mi = self._db.execute("SELECT COUNT(*) n, MIN(minute) a, MAX(minute) b FROM minutes").fetchone()
            we = self._db.execute("SELECT COUNT(*) n FROM weather").fetchone()
        size = sum(p.stat().st_size for p in self.dir.glob(self.path.name + "*") if p.exists())
        s = {"path": str(self.path), "events": ev["n"], "minutes": mi["n"], "weather": we["n"], "size_kb": round(size / 1024, 1),
             "first": _iso(min(x for x in (ev["a"], mi["a"]) if x)) if (ev["a"] or mi["a"]) else None,
             "last": _iso(max(x for x in (ev["b"], mi["b"]) if x)) if (ev["b"] or mi["b"]) else None}
        self._stats_cache = (now, s)
        return {**s, "last_write": self.last_write and _iso(self.last_write), "errors": self.errors}

    def history(self, hours: float, bucket: int) -> list[dict]:
        t1 = int(time.time() // bucket * bucket) + bucket
        t0 = t1 - int(hours * 3600 // bucket) * bucket
        with self._lock:
            rows = self._db.execute(
                "SELECT (minute/?)*? b, SUM(car) car, SUM(motorbike) motorbike, SUM(bus) bus, SUM(truck) truck, SUM(bicycle) bicycle, "
                "SUM(pcu) pcu, SUM(sp_sum) sp_sum, SUM(sp_n) sp_n, AVG(temp) temp, AVG(pm2_5) pm2_5, AVG(us_aqi) aqi "
                "FROM minutes WHERE minute>=? AND minute<? GROUP BY b", (bucket, bucket, t0, t1)).fetchall()
        by = {r["b"]: r for r in rows}
        out = []
        for b in range(t0, t1, bucket):
            r = by.get(b)
            d = {"t": b, **{c: (r[c] or 0) if r else 0 for c in CLASSES}, "pcu": round(r["pcu"] or 0, 2) if r else 0.0,
                 "speed": round(r["sp_sum"] / r["sp_n"], 1) if r and r["sp_n"] else None,
                 "temp": round(r["temp"], 1) if r and r["temp"] is not None else None,
                 "pm2_5": round(r["pm2_5"], 1) if r and r["pm2_5"] is not None else None,
                 "aqi": round(r["aqi"]) if r and r["aqi"] is not None else None}
            out.append(d)
        return out

    def _csv(self, header, rows) -> str:
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(header)
        w.writerows(rows)
        return buf.getvalue()

    def events_csv(self, t0=None, t1=None) -> str:
        with self._lock:
            rows = self._db.execute("SELECT ts,track_id,cls,line,direction,speed_kmh,is_first FROM events WHERE ts>=? AND ts<? ORDER BY ts",
                                    (t0 or 0, t1 or 4e9)).fetchall()
        return self._csv(["waktu", "id_kendaraan", "jenis", "garis", "arah", "kecepatan_kmh", "kendaraan_unik"],
                         [(_iso(r["ts"]), r["track_id"], r["cls"], r["line"], r["direction"], r["speed_kmh"], r["is_first"]) for r in rows])

    def minutes_csv(self, t0=None, t1=None) -> str:
        with self._lock:
            rows = self._db.execute("SELECT * FROM minutes WHERE minute>=? AND minute<? ORDER BY minute", (t0 or 0, t1 or 4e9)).fetchall()
        head = ["waktu_menit", *CLASSES, "total", "smp", "kecepatan_rata_kmh", "suhu_c", "rh_persen", "hujan_mm", "angin_kmh",
                "pm2_5", "pm10", "co", "no2", "us_aqi"]
        return self._csv(head, [(_iso(r["minute"], False), *[r[c] for c in CLASSES], r["total"], r["pcu"],
                                 round(r["sp_sum"] / r["sp_n"], 1) if r["sp_n"] else "", r["temp"], r["rh"], r["rain"], r["wind"],
                                 r["pm2_5"], r["pm10"], r["co"], r["no2"], r["us_aqi"]) for r in rows])

    def weather_csv(self, t0=None, t1=None) -> str:
        with self._lock:
            rows = self._db.execute("SELECT * FROM weather WHERE ts>=? AND ts<? ORDER BY ts", (t0 or 0, t1 or 4e9)).fetchall()
        head = ["waktu", "suhu_c", "rh_persen", "terasa_c", "hujan_mm", "kode_cuaca", "awan_persen", "tekanan_hpa", "angin_kmh",
                "arah_angin", "hembusan_kmh", "us_aqi", "pm2_5", "pm10", "co", "no2", "so2", "o3", "lat", "lon", "lokasi"]
        return self._csv(head, [(_iso(r["ts"], False), *[r[k] for k in ("temp", "rh", "apparent", "rain", "code", "cloud", "pressure", "wind",
                                 "wind_dir", "gust", "us_aqi", "pm2_5", "pm10", "co", "no2", "so2", "o3", "lat", "lon", "location")]) for r in rows])

    def backup_to(self, dest: Path):
        dst = sqlite3.connect(str(dest))
        try:
            with self._lock:
                self._db.backup(dst)
        finally:
            dst.close()

    def close(self):
        try:
            with self._lock:
                self._db.commit()
                self._db.close()
        except sqlite3.Error:
            pass
