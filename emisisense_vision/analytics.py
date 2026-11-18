"""Analitik lalu lintas: hitung kendaraan unik, arah, kecepatan, kepadatan zona, agregat per menit, dan penyimpanan.

Aturan hitung (satu kendaraan = satu hitungan):
  1. Bila trek melintasi sebuah garis hitung -> dihitung saat melintas (cara "garis"), lengkap dengan arah garis itu.
  2. Bila belum melintasi garis tetapi sudah terbukti bergerak (jarak tempuh >= ukuran kendaraan) atau trek
     berakhir setelah bergerak -> dihitung (cara "lacak"), arah dari vektor gerak.
Dengan begitu hitungan tetap masuk walaupun garis tidak tepat di jalur kendaraan.
"""
from __future__ import annotations

import math
import threading
import time
from collections import Counter, defaultdict, deque
from datetime import datetime

import cv2
import numpy as np

from .config import CLASS_LABEL, Config
from .storage import Storage
from .tracker import Track

SIZE_M = {"car": 3.0, "motorbike": 1.5, "bus": 6.0, "truck": 5.0, "bicycle": 1.4, "other": 3.0}   # ukuran khas (akar luas siluet)
SPEED_BINS = [0, 10, 20, 30, 40, 50, 60, 70, 80]
MINUTES_KEPT = 120
FREE_LINE = {"id": "_free", "name": "Di luar garis", "dir1": "Mendekat", "dir2": "Menjauh"}


def point_side(p, a, b) -> float:
    return (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0])


def density_level(pcu: float) -> tuple[str, int]:
    if pcu < 1.5: return "Lengang", 0
    if pcu < 4: return "Lancar", 1
    if pcu < 8: return "Ramai", 2
    if pcu < 13: return "Padat", 3
    return "Sangat padat", 4


class Analytics:
    def __init__(self, cfg: Config, weather_cb=None, storage: Storage | None = None):
        self.cfg = cfg
        self.weather_cb = weather_cb
        self.storage = storage
        self.lock = threading.RLock()
        self._dirty: set[int] = set()
        self._last_flush = 0.0
        self.reset()

    # ------------------------------------------------------------------ keadaan
    def reset(self):
        with self.lock:
            if hasattr(self, "minutes"):
                self.flush()
            self.totals: Counter = Counter()
            self.line_counts: dict = defaultdict(Counter)
            self.seen_ids: set[int] = set()
            self.counted_ids: set[int] = set()
            self.events: deque = deque(maxlen=5000)
            self.minutes: dict[int, dict] = {}
            self.speed_samples: deque = deque(maxlen=800)
            self.overspeed = 0
            self.t_start = time.time()
            self.cur_tracks: list[dict] = []
            self.zone_counts: Counter = Counter()
            self.zone_pcu = 0.0
            self.peak_zone = 0
            self._dirty.clear()

    # ------------------------------------------------------------------ pembaruan per siklus deteksi
    def update(self, tracks: list[Track], dead: list[Track], t: float, size: tuple[int, int]):
        cfg = self.cfg.get()
        W, H = size
        lines = cfg["lines"]
        roi = np.array([[p[0] * W, p[1] * H] for p in cfg["roi"]], np.float32)
        cal = cfg["calibration"].get("m_per_px")
        pcu_w = cfg["pcu"]
        limit = cfg["speed_limit_kmh"]
        rows, zone, zone_pcu = [], Counter(), 0.0
        with self.lock:
            for tr in tracks:
                if not tr.confirmed:
                    continue
                self._update_speed(tr, cal)
                fx, fy = tr.foot
                inside = cv2.pointPolygonTest(roi, (float(fx), float(fy - tr.x[3] * 0.25)), False) >= 0
                tr.in_roi = inside
                self.seen_ids.add(tr.id)
                fresh = (t - tr.last_t) <= 1.2
                if inside and fresh:
                    zone[tr.cls] += 1
                    zone_pcu += pcu_w.get(tr.cls, 1.0)
                if fresh:
                    for ln in lines:
                        self._check_line(tr, ln, W, H, t, limit, pcu_w)
                    self._check_motion(tr, t, limit, pcu_w)
                rows.append({
                    "id": tr.id, "cls": tr.cls, "label": CLASS_LABEL.get(tr.cls, tr.cls),
                    "speed": None if tr.speed_kmh is None else round(tr.speed_kmh, 1),
                    "conf": round(float(tr.conf), 2), "in_roi": bool(inside), "coasting": not fresh,
                    "age": round(t - tr.t0, 1), "counted": tr.id in self.counted_ids,
                })
            for tr in dead:                         # trek yang berakhir: hitung bila terbukti bergerak
                self._check_motion(tr, t, limit, pcu_w, final=True)
            self.cur_tracks = rows
            self.zone_counts, self.zone_pcu = zone, zone_pcu
            self.peak_zone = max(self.peak_zone, sum(zone.values()))
            self._rollover(time.time())

    def _update_speed(self, tr: Track, m_per_px):
        pts = [p for p in tr.trail if tr.last_t - p[0] <= 2.5]
        if len(pts) < 2:
            return
        span = pts[-1][0] - pts[0][0]
        if span < 0.35:
            return
        dist = math.hypot(pts[-1][1] - pts[0][1], pts[-1][2] - pts[0][2])
        scale = m_per_px if m_per_px else SIZE_M.get(tr.cls, 3.0) / max(8.0, math.sqrt(max(tr.x[2] * tr.x[3], 1.0)))
        v = 0.0 if dist < max(2.5, 0.05 * tr.size) else dist * scale / span * 3.6
        v = min(v, 130.0)
        tr.speed_kmh = v if tr.speed_kmh is None else 0.6 * tr.speed_kmh + 0.4 * v
        tr.max_speed = max(tr.max_speed, tr.speed_kmh)

    # ------------------------------------------------------------------ penghitungan
    def _check_line(self, tr: Track, ln: dict, W: int, H: int, t: float, limit: float, pcu_w: dict):
        a = (ln["p1"][0] * W, ln["p1"][1] * H); b = (ln["p2"][0] * W, ln["p2"][1] * H)
        foot = (tr.foot[0], tr.foot[1] - tr.x[3] * 0.25)
        s = point_side(foot, a, b)
        sign = 1 if s > 0 else -1
        prev = tr.side.get(ln["id"])
        tr.side[ln["id"]] = sign
        if prev is None or prev == sign:
            return
        ab = np.array(b) - np.array(a)
        u = float(np.dot(np.array(foot) - np.array(a), ab) / (np.dot(ab, ab) + 1e-9))
        if not -0.08 <= u <= 1.08:
            return
        direction = 1 if prev < 0 and sign > 0 else 2
        key = (ln["id"], direction)
        if key in tr.counted:
            return
        tr.counted.add(key)
        self._register(tr, ln, direction, "garis", limit, pcu_w)

    def _check_motion(self, tr: Track, t: float, limit: float, pcu_w: dict, final: bool = False):
        if tr.id in self.counted_ids:
            return
        thr = max(18.0, tr.size * (2.0 if tr.cls == "other" else 1.1))
        need_hits = 5 if tr.cls == "other" else 3
        age = (tr.trail[-1][0] - tr.t0) if tr.trail else 0.0
        enough = tr.displacement >= thr and tr.hits >= need_hits
        if not enough or (not final and age < 1.0):
            return
        vx, vy = tr.direction_vec
        fy = tr.foot[1] - tr.first_foot[1]
        direction = 1 if (fy if abs(fy) > 1 else vy) > 0 else 2
        self._register(tr, FREE_LINE, direction, "lacak", limit, pcu_w)

    def _register(self, tr: Track, ln: dict, direction: int, via: str, limit: float, pcu_w: dict):
        cls = tr.cls
        self.line_counts[ln["id"]][f"d{direction}:{cls}"] += 1
        first = tr.id not in self.counted_ids
        if first:
            self.counted_ids.add(tr.id)
            self.totals[cls] += 1
        ev = {"t": time.time(), "id": tr.id, "cls": cls, "line": ln["name"],
              "dir": ln.get("dir1" if direction == 1 else "dir2", f"Arah {direction}"),
              "speed": None if tr.speed_kmh is None else round(tr.speed_kmh, 1), "first": first, "via": via, "d": direction}
        self.events.append(ev)
        if first:
            m = self._minute(ev["t"])
            m[cls] += 1
            m["pcu"] += pcu_w.get(cls, 1.0)
            if tr.speed_kmh is not None:
                m["sp_sum"] += tr.speed_kmh
                m["sp_n"] += 1
                self.speed_samples.append(tr.speed_kmh)
                if tr.speed_kmh > limit:
                    self.overspeed += 1
            self._dirty.add(m["t"])
        if self.storage and self.cfg["log_events"]:
            self.storage.add_event(ev, self.cfg["source"])

    # ------------------------------------------------------------------ agregat per menit
    def _minute(self, ts: float) -> dict:
        k = int(ts // 60) * 60
        if k not in self.minutes:
            m = {"t": k, "pcu": 0.0, "sp_sum": 0.0, "sp_n": 0, **{c: 0 for c in CLASS_LABEL}}
            old_row = self.storage.get_minute(k) if self.storage else None   # lanjutkan bila aplikasi restart di menit yang sama
            if old_row:
                m.update({c: old_row.get(c) or 0 for c in CLASS_LABEL}); m["pcu"] = old_row["pcu"] or 0.0
                m["sp_sum"], m["sp_n"] = old_row["sp_sum"] or 0.0, old_row["sp_n"] or 0
            self.minutes[k] = m
            for old in sorted(self.minutes)[:-MINUTES_KEPT]:
                del self.minutes[old]
        return self.minutes[k]

    def _rollover(self, now: float):
        self._dirty.add(self._minute(now)["t"])          # menit teramati selalu tercatat (0 kendaraan != sistem mati)
        if self._dirty and now - self._last_flush >= 5.0:
            self.flush()

    def flush(self):
        with self.lock:
            self._last_flush = time.time()
            if not self.storage or not self._dirty:
                self._dirty.clear()
                return
            wx = self.weather_cb() if self.weather_cb else {}
            src = self.cfg["source"]
            for k in sorted(self._dirty):
                if k in self.minutes:
                    self.storage.upsert_minute(self.minutes[k], wx, src)
            self._dirty.clear()

    # ------------------------------------------------------------------ keluaran
    def snapshot(self) -> dict:
        cfg = self.cfg.get()
        with self.lock:
            now = time.time()
            cur_min = int(now // 60) * 60
            series = []
            for k in range(cur_min - 29 * 60, cur_min + 60, 60):
                m = self.minutes.get(k)
                series.append({"t": k, **{c: (m[c] if m else 0) for c in CLASS_LABEL}, "pcu": round(m["pcu"], 2) if m else 0.0})
            cm = self.minutes.get(cur_min, {})
            sp = list(self.speed_samples)
            hist = [0] * len(SPEED_BINS)
            for v in sp:
                hist[min(len(SPEED_BINS) - 1, int(v // 10))] += 1
            moving = [t["speed"] for t in self.cur_tracks if t["speed"] and not t["coasting"]]
            total = sum(self.totals.values())
            elapsed = max(now - self.t_start, 1.0)
            lvl, lvl_i = density_level(self.zone_pcu)
            lines = []
            for ln in list(cfg["lines"]) + [FREE_LINE]:
                c = self.line_counts.get(ln["id"], Counter())
                d1 = {k.split(":")[1]: v for k, v in c.items() if k.startswith("d1:")}
                d2 = {k.split(":")[1]: v for k, v in c.items() if k.startswith("d2:")}
                if ln["id"] == "_free" and not (d1 or d2):
                    continue
                lines.append({"id": ln["id"], "name": ln["name"], "dir1": ln.get("dir1", "Arah 1"), "dir2": ln.get("dir2", "Arah 2"),
                              "d1": sum(d1.values()), "d2": sum(d2.values()), "d1_by": d1, "d2_by": d2, "free": ln["id"] == "_free"})
            return {
                "totals": {c: self.totals.get(c, 0) for c in CLASS_LABEL}, "total": total,
                "unique_seen": len(self.seen_ids),
                "per_minute": series,
                "this_minute": sum(cm.get(c, 0) for c in CLASS_LABEL) if cm else 0,
                "rate_per_hour": round(total / elapsed * 3600),
                "pcu_total": round(sum(self.totals.get(c, 0) * cfg["pcu"].get(c, 1.0) for c in CLASS_LABEL), 1),
                "speed": {"avg": round(sum(sp) / len(sp), 1) if sp else None, "max": round(max(sp), 1) if sp else None,
                          "p85": round(float(np.percentile(sp, 85)), 1) if len(sp) >= 5 else None,
                          "now_avg": round(sum(moving) / len(moving), 1) if moving else None,
                          "hist": hist, "bins": SPEED_BINS, "overspeed": self.overspeed, "limit": cfg["speed_limit_kmh"], "n": len(sp)},
                "zone": {"count": sum(self.zone_counts.values()), "by": dict(self.zone_counts), "pcu": round(self.zone_pcu, 2),
                         "level": lvl, "level_i": lvl_i, "peak": self.peak_zone},
                "lines": lines,
                "tracks": sorted(self.cur_tracks, key=lambda t: -t["age"])[:40],
                "recent": [{**e, "ts": e["t"], "t": datetime.fromtimestamp(e["t"]).strftime("%H:%M:%S")} for e in list(self.events)[-14:]][::-1],
                "ticker": [{"ts": e["t"], "cls": e["cls"], "d": e.get("d", 1)} for e in self.events if e["first"] and now - e["t"] <= 120][-80:],
                "since": datetime.fromtimestamp(self.t_start).astimezone().isoformat(timespec="seconds"),
                "storage": self.storage.stats() if self.storage else None,
            }
