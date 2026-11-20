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

CLASSES = ["car", "motorbike", "bus", "truck", "bicycle", "other", "person"]
VEHICLE_CLASSES = [c for c in CLASSES if c != "person"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS events(
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, track_id INTEGER, cls TEXT, line TEXT, direction TEXT,
  speed_kmh REAL, is_first INTEGER, source TEXT, via TEXT);
CREATE INDEX IF NOT EXISTS ix_events_ts ON events(ts);
CREATE TABLE IF NOT EXISTS minutes(
  minute INTEGER PRIMARY KEY, car INTEGER DEFAULT 0, motorbike INTEGER DEFAULT 0, bus INTEGER DEFAULT 0,
  truck INTEGER DEFAULT 0, bicycle INTEGER DEFAULT 0, other INTEGER DEFAULT 0, person INTEGER DEFAULT 0, total INTEGER DEFAULT 0, pcu REAL DEFAULT 0,
  sp_sum REAL DEFAULT 0, sp_n INTEGER DEFAULT 0,
  temp REAL, rh REAL, rain REAL, wind REAL, pm2_5 REAL, pm10 REAL, co REAL, no2 REAL, us_aqi REAL, source TEXT);
CREATE TABLE IF NOT EXISTS weather(
  ts INTEGER PRIMARY KEY, temp REAL, rh REAL, apparent REAL, rain REAL, code INTEGER, cloud REAL, pressure REAL,
  wind REAL, wind_dir REAL, gust REAL, us_aqi REAL, pm2_5 REAL, pm10 REAL, co REAL, no2 REAL, so2 REAL, o3 REAL,
  lat REAL, lon REAL, location TEXT);
CREATE TABLE IF NOT EXISTS wind_hourly(
  ts INTEGER, loc TEXT, speed REAL, dir REAL, gust REAL, PRIMARY KEY(ts, loc));
"""


def _compass(deg) -> str:
    from .wind import compass
    c = compass(deg)
    return f"{c['abbr']} ({c['name']})" if c else ""


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
            self._migrate()
            self._db.commit()
        self.last_write = None
        self.errors = 0
        self._stats_cache = (0.0, {})

    def _migrate(self):
        """Tambahkan kolom baru pada database lama (pembaruan aplikasi tidak menghapus data)."""
        def cols(t):
            return {r[1] for r in self._db.execute(f"PRAGMA table_info({t})")}
        if "other" not in cols("minutes"):
            self._db.execute("ALTER TABLE minutes ADD COLUMN other INTEGER DEFAULT 0")
        if "person" not in cols("minutes"):
            self._db.execute("ALTER TABLE minutes ADD COLUMN person INTEGER DEFAULT 0")
        if "wind_dir" not in cols("minutes"):
            self._db.execute("ALTER TABLE minutes ADD COLUMN wind_dir REAL")
        if "wx_sync" not in cols("minutes"):
            self._db.execute("ALTER TABLE minutes ADD COLUMN wx_sync INTEGER DEFAULT 0")   # 1 = cuaca diisi belakangan lewat sinkronisasi (per jam)
        if "via" not in cols("events"):
            self._db.execute("ALTER TABLE events ADD COLUMN via TEXT")

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

    def _exec_many(self, sql: str, rows):
        try:
            with self._lock:
                self._db.executemany(sql, rows)
                self._db.commit()
            self.last_write = time.time()
            return True
        except sqlite3.Error:
            self.errors += 1
            return False

    def add_event(self, ev: dict, source: str = ""):
        self._exec("INSERT INTO events(ts,track_id,cls,line,direction,speed_kmh,is_first,source,via) VALUES(?,?,?,?,?,?,?,?,?)",
                   (ev["t"], ev["id"], ev["cls"], ev["line"], ev["dir"], ev["speed"], int(ev["first"]), source, ev.get("via", "garis")))

    def get_minute(self, minute: int) -> dict | None:
        with self._lock:
            r = self._db.execute("SELECT * FROM minutes WHERE minute=?", (minute,)).fetchone()
        return dict(r) if r else None

    def upsert_minute(self, m: dict, wx: dict | None, source: str = ""):
        cur, aq = (wx or {}).get("current") or {}, (wx or {}).get("air_quality") or {}
        vals = [m["t"]] + [m.get(c, 0) for c in CLASSES]
        total = sum(m.get(c, 0) for c in VEHICLE_CLASSES)        # total = kendaraan saja; pejalan kaki di kolom sendiri
        vals += [total, round(m["pcu"], 3), round(m["sp_sum"], 2), m["sp_n"], cur.get("temperature_2m"), cur.get("relative_humidity_2m"),
                 cur.get("precipitation"), cur.get("wind_speed_10m"), aq.get("pm2_5"), aq.get("pm10"), aq.get("carbon_monoxide"),
                 aq.get("nitrogen_dioxide"), aq.get("us_aqi"), source, cur.get("wind_direction_10m")]
        self._exec("INSERT OR REPLACE INTO minutes(minute,car,motorbike,bus,truck,bicycle,other,person,total,pcu,sp_sum,sp_n,temp,rh,rain,wind,"
                   "pm2_5,pm10,co,no2,us_aqi,source,wind_dir) VALUES(" + ",".join("?" * 23) + ")", vals)

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
        if cur.get("wind_speed_10m") is not None and cur.get("wind_direction_10m") is not None and loc.get("lat") is not None:
            self.upsert_wind([(int(time.time() // 3600 * 3600), cur["wind_speed_10m"], cur["wind_direction_10m"], cur.get("wind_gusts_10m"))], loc)

    # ------------------------------------------------------------ sinkronisasi cuaca (data diambil offline, cuaca menyusul)
    NO_WX = "temp IS NULL AND rh IS NULL AND wind IS NULL AND pm2_5 IS NULL AND us_aqi IS NULL"

    def wx_pending(self) -> dict:
        """Jumlah menit yang sudah tercatat tetapi belum punya data cuaca, beserta rentang waktunya."""
        with self._lock:
            r = self._db.execute(f"SELECT COUNT(*) n, MIN(minute) a, MAX(minute) b FROM minutes WHERE {self.NO_WX}").fetchone()
        return {"minutes": r["n"], "first": r["a"], "last": r["b"]}

    def backfill_weather(self, hourly: dict, loc: dict) -> dict:
        """hourly: {ts_jam: {kunci: nilai}} dari Open-Meteo. Mengisi menit yang kosong dengan nilai jam tersebut
        (tidak menimpa data waktu nyata), menambah rekaman cuaca per jam, dan riwayat angin."""
        filled = hours_used = 0
        with self._lock:
            try:
                for ts in sorted(hourly):
                    h = hourly[ts]
                    cur = self._db.execute(
                        f"UPDATE minutes SET temp=?, rh=?, rain=?, wind=?, wind_dir=?, pm2_5=?, pm10=?, co=?, no2=?, us_aqi=?, wx_sync=1 "
                        f"WHERE minute>=? AND minute<? AND {self.NO_WX}",
                        (h.get("temperature_2m"), h.get("relative_humidity_2m"), h.get("precipitation"), h.get("wind_speed_10m"),
                         h.get("wind_direction_10m"), h.get("pm2_5"), h.get("pm10"), h.get("carbon_monoxide"), h.get("nitrogen_dioxide"),
                         h.get("us_aqi"), ts, ts + 3600))
                    if cur.rowcount:
                        filled += cur.rowcount; hours_used += 1
                        if not self._db.execute("SELECT 1 FROM weather WHERE ts>=? AND ts<?", (ts, ts + 3600)).fetchone():
                            self._db.execute("INSERT OR IGNORE INTO weather VALUES(" + ",".join("?" * 21) + ")",
                                (ts, h.get("temperature_2m"), h.get("relative_humidity_2m"), h.get("apparent_temperature"), h.get("precipitation"),
                                 h.get("weather_code"), h.get("cloud_cover"), h.get("pressure_msl"), h.get("wind_speed_10m"),
                                 h.get("wind_direction_10m"), h.get("wind_gusts_10m"), h.get("us_aqi"), h.get("pm2_5"), h.get("pm10"),
                                 h.get("carbon_monoxide"), h.get("nitrogen_dioxide"), h.get("sulphur_dioxide"), h.get("ozone"),
                                 loc.get("lat"), loc.get("lon"), loc.get("name")))
                self._db.commit()
            except sqlite3.Error:
                self._db.rollback(); self.errors += 1
                raise
        self._stats_cache = (0.0, {})
        return {"minutes_filled": filled, "hours_used": hours_used}

    # ------------------------------------------------------------ angin
    @staticmethod
    def loc_key(loc: dict) -> str:
        return f"{float(loc['lat']):.2f},{float(loc['lon']):.2f}"

    def upsert_wind(self, rows, loc: dict):
        """rows: (ts_jam, kecepatan km/jam, arah derajat, hembusan). Satu sampel per jam per lokasi."""
        key = self.loc_key(loc)
        self._exec_many("INSERT OR REPLACE INTO wind_hourly(ts,loc,speed,dir,gust) VALUES(?,?,?,?,?)",
                        [(int(t), key, sp, d, g) for t, sp, d, g in rows if sp is not None and d is not None])

    def windrose(self, hours: float, loc: dict) -> dict:
        from .wind import windrose
        t0 = int(time.time() - hours * 3600)
        with self._lock:
            rows = self._db.execute("SELECT speed, dir FROM wind_hourly WHERE loc=? AND ts>=?", (self.loc_key(loc), t0)).fetchall()
        out = windrose([(r["speed"], r["dir"]) for r in rows])
        out["hours"] = hours
        return out

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
        s = {"path": str(self.path), "wx_pending": self.wx_pending()["minutes"], "events": ev["n"], "minutes": mi["n"], "weather": we["n"], "size_kb": round(size / 1024, 1),
             "first": _iso(min(x for x in (ev["a"], mi["a"]) if x)) if (ev["a"] or mi["a"]) else None,
             "last": _iso(max(x for x in (ev["b"], mi["b"]) if x)) if (ev["b"] or mi["b"]) else None}
        self._stats_cache = (now, s)
        return {**s, "last_write": self.last_write and _iso(self.last_write), "errors": self.errors}

    def history(self, hours: float, bucket: int) -> list[dict]:
        t1 = int(time.time() // bucket * bucket) + bucket
        t0 = t1 - int(hours * 3600 // bucket) * bucket
        with self._lock:
            rows = self._db.execute(
                "SELECT (minute/?)*? b, SUM(car) car, SUM(motorbike) motorbike, SUM(bus) bus, SUM(truck) truck, SUM(bicycle) bicycle, SUM(other) other, SUM(person) person, "
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
            rows = self._db.execute("SELECT ts,track_id,cls,line,direction,speed_kmh,is_first,via FROM events WHERE ts>=? AND ts<? ORDER BY ts",
                                    (t0 or 0, t1 or 4e9)).fetchall()
        return self._csv(["waktu", "id_kendaraan", "jenis", "garis", "arah", "kecepatan_kmh", "kendaraan_unik", "cara_hitung"],
                         [(_iso(r["ts"]), r["track_id"], r["cls"], r["line"], r["direction"], r["speed_kmh"], r["is_first"], r["via"]) for r in rows])

    def minutes_rows(self, t0=None, t1=None) -> list:
        with self._lock:
            return self._db.execute("SELECT * FROM minutes WHERE minute>=? AND minute<? ORDER BY minute", (t0 or 0, t1 or 4e9)).fetchall()

    def minutes_csv(self, t0=None, t1=None) -> str:
        with self._lock:
            rows = self._db.execute("SELECT * FROM minutes WHERE minute>=? AND minute<? ORDER BY minute", (t0 or 0, t1 or 4e9)).fetchall()
        head = ["waktu_menit", *CLASSES, "total", "smp", "kecepatan_rata_kmh", "suhu_c", "rh_persen", "hujan_mm", "angin_kmh",
                "arah_angin_derajat", "arah_mata_angin", "pm2_5", "pm10", "co", "no2", "us_aqi", "cuaca_sinkron"]
        return self._csv(head, [(_iso(r["minute"], False), *[r[c] for c in CLASSES], r["total"], r["pcu"],
                                 round(r["sp_sum"] / r["sp_n"], 1) if r["sp_n"] else "", r["temp"], r["rh"], r["rain"], r["wind"],
                                 r["wind_dir"], _compass(r["wind_dir"]),
                                 r["pm2_5"], r["pm10"], r["co"], r["no2"], r["us_aqi"], r["wx_sync"] or 0) for r in rows])

    def weather_csv(self, t0=None, t1=None) -> str:
        with self._lock:
            rows = self._db.execute("SELECT * FROM weather WHERE ts>=? AND ts<? ORDER BY ts", (t0 or 0, t1 or 4e9)).fetchall()
        head = ["waktu", "suhu_c", "rh_persen", "terasa_c", "hujan_mm", "kode_cuaca", "awan_persen", "tekanan_hpa", "angin_kmh",
                "arah_angin_derajat", "arah_mata_angin", "hembusan_kmh", "us_aqi", "pm2_5", "pm10", "co", "no2", "so2", "o3", "lat", "lon", "lokasi"]
        return self._csv(head, [(_iso(r["ts"], False), *[r[k] for k in ("temp", "rh", "apparent", "rain", "code", "cloud", "pressure", "wind",
                                 "wind_dir")], _compass(r["wind_dir"]), *[r[k] for k in ("gust", "us_aqi", "pm2_5", "pm10", "co", "no2", "so2", "o3", "lat", "lon", "location")]) for r in rows])

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
