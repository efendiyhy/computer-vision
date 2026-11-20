"""Penerima data sensor PM (partikulat) dan Gas dari dua ESP32 (dilebur dari proyek pmgas-merge).

Dua alat ESP32 mengirim paket ~1 Hz ke ``POST /api/ingest`` (format sama dengan laptop server EK Air Quality Hub):
``device_type`` = ``pm`` atau ``gas``, ``event_id`` unik, ``timestamp`` waktu ukur (UTC), ``measurements`` berisi nilai sensor.

Penyimpanan (SQLite ``pmgas.db`` di folder data)
  readings    - setiap paket unik apa adanya (data mentah), lengkap dengan detik ukur (``sec``) dan nama sesi/label saat diterima
  minute_agg  - jumlah dan banyaknya pembacaan per menit, untuk rata-rata per menit dan grafik riwayat yang cepat
  meta        - nama sesi dan label yang sedang aktif

Penggabungan (sinkronisasi) dilakukan menurut WAKTU UKUR sensor, bukan waktu paket diterima. Bila pada suatu detik salah satu alat
tidak punya pembacaan, atau satu nilai kosong, nilai itu diisi dengan nilai valid terakhir sebelumnya (maksimal ``gap`` detik,
bawaan 300) dan kolomnya ditandai pada ``filled_columns``. Tanpa nilai sebelumnya dalam batas itu, sel tetap kosong.
"""
from __future__ import annotations

import json
import math
import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

PM_FIELDS = ["pm1_pms1", "pm25_pms1", "pm10_pms1", "pm1_pms2", "pm25_pms2", "pm10_pms2", "suhu", "kelembapan"]
GAS_FIELDS = ["co_ppm", "co2_ppm", "no2_ppm", "suhu_c", "rh_pct", "red_v", "nox_v", "red_ratio", "nox_ratio"]
FIELDS = {"pm": PM_FIELDS, "gas": GAS_FIELDS}
RAW_COLS = (["received_at", "timestamp", "event_id", "device_id", "device_type", "sample_name", "uptime_ms"]
            + PM_FIELDS + GAS_FIELDS + ["session_name", "label"])
MERGED_COLS = (["waktu_wib", "waktu_utc", "session_name", "label", "sync_status", "time_basis"]
               + ["pm1_avg", "pm25_avg", "pm10_avg", "co_ppm", "co2_ppm", "no2_ppm"]
               + PM_FIELDS + ["gas_" + k for k in GAS_FIELDS[3:]]
               + ["pm_sample_name", "gas_sample_name", "pm_uptime_ms", "gas_uptime_ms", "filled_columns"])
# kolom bernilai yang boleh diisi dari nilai sebelumnya (kolom teks/identitas tidak)
MERGED_VALUE_COLS = (["pm1_avg", "pm25_avg", "pm10_avg", "co_ppm", "co2_ppm", "no2_ppm"] + PM_FIELDS
                     + ["gas_" + k for k in GAS_FIELDS[3:]])
# metrik per menit (rata-rata dari semua pembacaan dalam menit itu)
METRICS = ["pm1", "pm25", "pm10", "co", "co2", "no2", "temp", "rh"]
FILL_GAP_DEFAULT = 300
ONLINE_WITHIN = 10.0          # detik: alat dianggap tersambung bila paket terakhir sebaru ini


def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _mean(vals):
    v = [x for x in vals if _num(x)]
    return round(sum(v) / len(v), 3) if v else None


def _utc(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _wib(ts: float) -> str:
    return datetime.fromtimestamp(ts).astimezone().isoformat(timespec="seconds")


def sensor_second(received_ts: float, timestamp) -> tuple[int, str]:
    """(detik UTC, asal). Waktu sensor dipakai bila sah; bila kosong/tidak sah (mis. jam alat belum disetel) dipakai waktu terima."""
    if isinstance(timestamp, str) and timestamp:
        try:
            v = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            v = v if v.tzinfo else v.replace(tzinfo=timezone.utc)
            if v.year >= 2020:
                return int(v.timestamp()), "SENSOR"
        except (ValueError, OverflowError, OSError):
            pass
    return int(received_ts), "RECEIVED"


def validate(p) -> dict:
    """Periksa paket ESP32; ValueError bila tidak sah."""
    if not isinstance(p, dict) or p.get("device_type") not in FIELDS:
        raise ValueError("device_type harus pm atau gas")
    for k in ("event_id", "device_id", "sample_name"):
        if not isinstance(p.get(k), str) or not 1 <= len(p[k]) <= 100:
            raise ValueError("Invalid " + k)
    values = p.get("measurements")
    if not isinstance(values, dict):
        raise ValueError("measurements harus objek JSON")
    out = {}
    for k in FIELDS[p["device_type"]]:
        v = values.get(k)
        if v is None:
            out[k] = None
        elif _num(v):
            out[k] = float(v)
        else:
            raise ValueError("Invalid sensor value " + k)
    ts = p.get("timestamp")
    if ts is not None and (not isinstance(ts, str) or len(ts) > 50):
        raise ValueError("Invalid timestamp")
    up = p.get("uptime_ms")
    if up is not None and (not isinstance(up, int) or isinstance(up, bool) or up < 0):
        raise ValueError("Invalid uptime_ms")
    return {"event_id": p["event_id"], "device_id": p["device_id"], "device_type": p["device_type"],
            "sample_name": p["sample_name"], "timestamp": ts, "uptime_ms": up, "measurements": out}


def reading_metrics(kind: str, m: dict) -> dict:
    """Nilai per pembacaan yang dipakai untuk rata-rata menit (PM: rata-rata dua sensor PMS)."""
    if kind == "pm":
        return {"pm1": _mean([m.get("pm1_pms1"), m.get("pm1_pms2")]), "pm25": _mean([m.get("pm25_pms1"), m.get("pm25_pms2")]),
                "pm10": _mean([m.get("pm10_pms1"), m.get("pm10_pms2")]), "temp": m.get("suhu"), "rh": m.get("kelembapan")}
    return {"co": m.get("co_ppm"), "co2": m.get("co2_ppm"), "no2": m.get("no2_ppm"), "temp": m.get("suhu_c"), "rh": m.get("rh_pct")}


def locf(rows, cols, gap, tkey):
    """Isi nilai kosong dengan nilai valid sebelumnya (last observation carried forward), maksimal ``gap`` detik.

    rows: urut waktu; tiap elemen dict dengan ``rows[i]['v']`` (kolom -> nilai) dan ``rows[i][tkey]`` (detik). Menambah ``filled`` (daftar kolom)."""
    last: dict = {}
    for r in rows:
        r["filled"] = []
        for c in cols:
            v = r["v"].get(c)
            if _num(v):
                last[c] = (v, r[tkey])
            elif c in last and r[tkey] - last[c][1] <= gap:
                r["v"][c] = last[c][0]
                r["filled"].append(c)
    return rows


class PmGasStore:
    def __init__(self, directory: Path, filename: str = "pmgas.db"):
        self.dir = Path(directory)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.path = self.dir / filename
        self._lock = threading.RLock()
        self._db = sqlite3.connect(str(self.path), check_same_thread=False, timeout=15)
        self._db.row_factory = sqlite3.Row
        with self._lock:
            self._db.execute("PRAGMA journal_mode=WAL")
            self._db.execute("PRAGMA synchronous=NORMAL")
            self._db.executescript(
                "CREATE TABLE IF NOT EXISTS readings(event_id TEXT PRIMARY KEY, device_id TEXT NOT NULL, device_type TEXT NOT NULL,"
                " received_at REAL NOT NULL, timestamp TEXT, sec INTEGER NOT NULL, basis TEXT NOT NULL, uptime_ms INTEGER,"
                " sample_name TEXT NOT NULL, measurements TEXT NOT NULL, session TEXT NOT NULL DEFAULT '', label TEXT NOT NULL DEFAULT '');"
                "CREATE INDEX IF NOT EXISTS ix_pg_sec ON readings(sec);"
                "CREATE INDEX IF NOT EXISTS ix_pg_type ON readings(device_type, received_at);"
                "CREATE TABLE IF NOT EXISTS minute_agg(minute INTEGER PRIMARY KEY, n_pm INTEGER DEFAULT 0, n_gas INTEGER DEFAULT 0, "
                + ", ".join(f"s_{m} REAL DEFAULT 0, n_{m} INTEGER DEFAULT 0" for m in METRICS) + ");"
                "CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT);")
            self._db.commit()
        self.errors = 0
        self.last_ingest = None

    # ------------------------------------------------------------------ meta
    def get_meta(self) -> dict:
        with self._lock:
            d = {r["k"]: r["v"] for r in self._db.execute("SELECT k,v FROM meta")}
        return {"session": d.get("session", ""), "label": d.get("label", "")}

    def set_meta(self, session=None, label=None) -> dict:
        with self._lock:
            for k, v in (("session", session), ("label", label)):
                if v is not None:
                    self._db.execute("INSERT OR REPLACE INTO meta(k,v) VALUES(?,?)", (k, str(v).strip()[:120]))
            self._db.commit()
        return self.get_meta()

    # ------------------------------------------------------------------ tulis
    def ingest(self, payload, now: float | None = None) -> dict:
        rec = validate(payload)
        now = now or time.time()
        sec, basis = sensor_second(now, rec["timestamp"])
        meta = self.get_meta()
        with self._lock:
            cur = self._db.execute(
                "INSERT OR IGNORE INTO readings(event_id,device_id,device_type,received_at,timestamp,sec,basis,uptime_ms,sample_name,"
                "measurements,session,label) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (rec["event_id"], rec["device_id"], rec["device_type"], now, rec["timestamp"], sec, basis, rec["uptime_ms"],
                 rec["sample_name"], json.dumps(rec["measurements"]), meta["session"], meta["label"]))
            fresh = cur.rowcount > 0
            if fresh:
                mt = reading_metrics(rec["device_type"], rec["measurements"])
                minute = sec // 60 * 60
                self._db.execute("INSERT OR IGNORE INTO minute_agg(minute) VALUES(?)", (minute,))
                sets, args = [f"n_{rec['device_type']}=n_{rec['device_type']}+1"], []
                for m, v in mt.items():
                    if _num(v):
                        sets.append(f"s_{m}=s_{m}+?"); sets.append(f"n_{m}=n_{m}+1"); args.append(v)
                self._db.execute(f"UPDATE minute_agg SET {', '.join(sets)} WHERE minute=?", (*args, minute))
            self._db.commit()
        self.last_ingest = now
        return {"duplicate": not fresh, "recording": bool(meta["session"] or meta["label"])}

    # ------------------------------------------------------------------ baca
    def latest(self, now: float | None = None) -> dict:
        now = now or time.time()
        out = {}
        with self._lock:
            for kind in FIELDS:
                r = self._db.execute("SELECT * FROM readings WHERE device_type=? ORDER BY received_at DESC LIMIT 1", (kind,)).fetchone()
                if not r:
                    out[kind] = {"online": False, "age": None, "values": None}
                    continue
                age = max(0.0, now - r["received_at"])
                m = json.loads(r["measurements"])
                out[kind] = {"online": age <= ONLINE_WITHIN, "age": round(age, 1), "device_id": r["device_id"], "sample": r["sample_name"],
                             "values": {**m, **reading_metrics(kind, m)}, "time": _wib(r["sec"])}
        return out

    def recent_series(self, seconds: int = 1800, bucket: int = 30, now: float | None = None) -> list[dict]:
        """Deret waktu nyata untuk grafik Pemantauan: rata-rata per ``bucket`` detik dari data mentah beberapa menit terakhir."""
        now = now or time.time()
        t0 = int(now) - seconds
        with self._lock:
            rows = self._db.execute("SELECT device_type, sec, measurements FROM readings WHERE sec>=? ORDER BY sec", (t0,)).fetchall()
        acc: dict = {}
        for r in rows:
            b = (r["sec"] - t0) // bucket
            mt = reading_metrics(r["device_type"], json.loads(r["measurements"]))
            d = acc.setdefault(b, {})
            for k, v in mt.items():
                if _num(v):
                    d.setdefault(k, []).append(v)
        return [{"t": t0 + b * bucket, **{k: (_mean(acc[b].get(k, [])) if b in acc else None) for k in METRICS}}
                for b in range(0, seconds // bucket + 1)]

    def history(self, t0: int, t1: int, bucket: int) -> list[dict]:
        """Rata-rata per ``bucket`` detik dari agregat menit (untuk Riwayat)."""
        with self._lock:
            rows = self._db.execute("SELECT * FROM minute_agg WHERE minute>=? AND minute<?", (t0, t1)).fetchall()
        acc: dict = {}
        for r in rows:
            b = (r["minute"] - t0) // bucket
            d = acc.setdefault(b, {m: [0.0, 0] for m in METRICS})
            for m in METRICS:
                d[m][0] += r[f"s_{m}"]; d[m][1] += r[f"n_{m}"]
        return [{"t": t0 + b * bucket, **{m: (round(acc[b][m][0] / acc[b][m][1], 2) if b in acc and acc[b][m][1] else None) for m in METRICS}}
                for b in range(0, max(1, (t1 - t0) // bucket))]

    def stats(self) -> dict:
        with self._lock:
            n = {k: self._db.execute("SELECT COUNT(*) FROM readings WHERE device_type=?", (k,)).fetchone()[0] for k in FIELDS}
            a = self._db.execute("SELECT MIN(sec) a, MAX(sec) b FROM readings").fetchone()
        size = sum(p.stat().st_size for p in self.dir.glob(self.path.name + "*") if p.exists())
        return {"pm": n["pm"], "gas": n["gas"], "first": a["a"] and _wib(a["a"]), "last": a["b"] and _wib(a["b"]),
                "size_kb": round(size / 1024, 1), "errors": self.errors, "path": str(self.path)}

    # ------------------------------------------------------------------ ekspor
    def _select(self, lo, hi, kind=None):
        q, args = "SELECT * FROM readings WHERE 1=1", []
        if lo is not None:
            q += " AND sec>=?"; args.append(int(lo))
        if hi is not None:
            q += " AND sec<?"; args.append(int(hi))
        if kind in FIELDS:
            q += " AND device_type=?"; args.append(kind)
        with self._lock:
            return self._db.execute(q + " ORDER BY sec, received_at, rowid", args).fetchall()

    def raw_rows(self, t0=None, t1=None, kind=None) -> list[list]:
        out = []
        for r in self._select(t0, t1, kind):
            m = json.loads(r["measurements"])
            base = {"received_at": _utc(r["received_at"]), "timestamp": r["timestamp"], "event_id": r["event_id"], "device_id": r["device_id"],
                    "device_type": r["device_type"], "sample_name": r["sample_name"], "uptime_ms": r["uptime_ms"],
                    "session_name": r["session"], "label": r["label"], **m}
            out.append([base.get(c) for c in RAW_COLS])
        return out

    def merged(self, t0=None, t1=None, gap: int = FILL_GAP_DEFAULT, fill: bool = True) -> list[list]:
        """Baris gabungan PM+Gas per detik ukur; nilai kosong diisi nilai sebelumnya (maks ``gap`` detik) bila ``fill``."""
        lo = None if t0 is None else t0 - (gap if fill else 0)
        buckets: dict = {}
        for r in self._select(lo, t1):
            buckets.setdefault((r["sec"], r["basis"]), {"pm": [], "gas": []})[r["device_type"]].append(r)
        rows = []
        for (sec, basis) in sorted(buckets):
            g = buckets[(sec, basis)]
            for i in range(max(len(g["pm"]), len(g["gas"]))):
                pm = g["pm"][i] if i < len(g["pm"]) else None
                gas = g["gas"][i] if i < len(g["gas"]) else None
                pv = json.loads(pm["measurements"]) if pm else {}
                gv = json.loads(gas["measurements"]) if gas else {}
                pl, gl = (pm["label"] if pm else ""), (gas["label"] if gas else "")
                label = f"{pl} | {gl}" if pl and gl and pl != gl else (pl or gl)
                status = "LABEL_BERBEDA" if pl and gl and pl != gl else ("LENGKAP" if pm and gas else "HANYA_PM" if pm else "HANYA_GAS")
                v = {"pm1_avg": _mean([pv.get("pm1_pms1"), pv.get("pm1_pms2")]), "pm25_avg": _mean([pv.get("pm25_pms1"), pv.get("pm25_pms2")]),
                     "pm10_avg": _mean([pv.get("pm10_pms1"), pv.get("pm10_pms2")]),
                     **{k: gv.get(k) for k in GAS_FIELDS[:3]}, **{k: pv.get(k) for k in PM_FIELDS},
                     **{"gas_" + k: gv.get(k) for k in GAS_FIELDS[3:]}}
                s = pm or gas
                rows.append({"sec": sec, "v": v, "pre": [_wib(sec), _utc(sec), s["session"], label, status, basis],
                             "post": [pm["sample_name"] if pm else None, gas["sample_name"] if gas else None,
                                      pm["uptime_ms"] if pm else None, gas["uptime_ms"] if gas else None]})
        if fill:
            locf(rows, MERGED_VALUE_COLS, gap, "sec")
        else:
            for r in rows:
                r["filled"] = []
        return [[*r["pre"], *[r["v"].get(c) for c in MERGED_VALUE_COLS[:6]], *[r["v"].get(c) for c in MERGED_VALUE_COLS[6:]],
                 *r["post"], ";".join(r["filled"])] for r in rows if t0 is None or r["sec"] >= t0]

    def minute_series(self, minutes: list[int], gap: int = FILL_GAP_DEFAULT, fill: bool = True) -> dict[int, dict]:
        """Rata-rata per menit (dari semua pembacaan dalam menit itu) untuk menit-menit yang diminta, mis. menit pencatatan kendaraan.

        Menit tanpa pembacaan diisi dengan nilai menit sebelumnya (maks ``gap`` detik) dan ditandai pada ``filled``."""
        if not minutes:
            return {}
        lo, hi = min(minutes) - (gap if fill else 0), max(minutes) + 60
        with self._lock:
            agg = {r["minute"]: r for r in self._db.execute("SELECT * FROM minute_agg WHERE minute>=? AND minute<?", (lo, hi))}
        want = set(minutes)
        seq = []
        for mn in sorted(set(agg) | want):
            a = agg.get(mn)
            v = {m: (round(a[f"s_{m}"] / a[f"n_{m}"], 3) if a and a[f"n_{m}"] else None) for m in METRICS}
            seq.append({"minute": mn, "v": v, "n_pm": a["n_pm"] if a else 0, "n_gas": a["n_gas"] if a else 0})
        if fill:
            locf(seq, METRICS, gap, "minute")
        else:
            for r in seq:
                r["filled"] = []
        return {r["minute"]: r for r in seq if r["minute"] in want}

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


def start_demo_feed(store: PmGasStore, stop: threading.Event | None = None) -> threading.Thread:
    """Mode demo: kirim data PM dan Gas tiruan 1 Hz, sesekali salah satu alat 'putus' beberapa detik agar pengisian data kosong terlihat."""
    import random
    stop = stop or threading.Event()

    def run():
        n, base, gas, rnd = 0, 22.0, 0.8, random.Random(7)
        while not stop.is_set():
            n += 1
            base = max(4.0, min(70.0, base + rnd.uniform(-1.2, 1.3)))
            gas = max(0.1, min(5.0, gas + rnd.uniform(-0.12, 0.13)))
            ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            try:
                if (n // 40) % 5 != 4 or n % 40 > 7:           # alat PM putus ~8 detik tiap ~200 detik
                    store.ingest({"device_type": "pm", "event_id": f"demo-pm-{n}-{int(time.time())}", "device_id": "demo-pm", "sample_name": "demo",
                                  "timestamp": ts, "uptime_ms": n * 1000, "measurements": {
                                      "pm1_pms1": base * .55, "pm25_pms1": base, "pm10_pms1": base * 1.4, "pm1_pms2": base * .58,
                                      "pm25_pms2": base * 1.05, "pm10_pms2": base * 1.45, "suhu": 29.5 + rnd.uniform(-.2, .2), "kelembapan": 66 + rnd.uniform(-1, 1)}})
                if (n // 40) % 5 != 2 or n % 40 > 5:           # alat Gas putus ~6 detik
                    store.ingest({"device_type": "gas", "event_id": f"demo-gas-{n}-{int(time.time())}", "device_id": "demo-gas", "sample_name": "demo",
                                  "timestamp": ts, "uptime_ms": n * 1000, "measurements": {
                                      "co_ppm": gas, "co2_ppm": 420 + gas * 60 + rnd.uniform(-8, 8), "no2_ppm": gas * .05, "suhu_c": 30.1, "rh_pct": 64.0,
                                      "red_v": 1.2, "nox_v": 0.9, "red_ratio": 1.1, "nox_ratio": 0.95}})
            except Exception:
                pass
            stop.wait(1.0)
    t = threading.Thread(target=run, daemon=True, name="pmgas-demo")
    t.start()
    return t
