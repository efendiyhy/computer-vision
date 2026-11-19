"""Arah mata angin dan mawar angin (windrose).

Konvensi meteorologi: arah angin = ARAH ASAL angin (angin dari utara bertiup ke selatan), derajat searah jarum jam dari utara.
"""
from __future__ import annotations

import math
import random
import time

ABBR = ["U", "UTL", "TL", "TTL", "T", "TTG", "TG", "STG", "S", "SBD", "BD", "BBD", "B", "BBL", "BL", "UBL"]
NAME = ["Utara", "Utara-timur laut", "Timur laut", "Timur-timur laut", "Timur", "Timur-tenggara", "Tenggara", "Selatan-tenggara",
        "Selatan", "Selatan-barat daya", "Barat daya", "Barat-barat daya", "Barat", "Barat-barat laut", "Barat laut", "Utara-barat laut"]
# kelas kecepatan angin (km/jam); di bawah CALM dianggap tenang (arah tidak bermakna)
CALM = 1.0
BIN_EDGES = [CALM, 5.0, 10.0, 20.0, 30.0]
BIN_LABELS = ["1–5", "5–10", "10–20", "20–30", "> 30"]


def sector(deg: float) -> int:
    return int(((deg % 360) + 11.25) // 22.5) % 16


def compass(deg) -> dict | None:
    if deg is None:
        return None
    i = sector(float(deg))
    return {"i": i, "abbr": ABBR[i], "name": NAME[i], "deg": round(float(deg) % 360)}


def _bin(speed: float) -> int:
    k = 0
    for e in BIN_EDGES[1:]:
        if speed >= e:
            k += 1
    return k


def windrose(samples: list[tuple[float, float]]) -> dict:
    """samples: daftar (kecepatan km/jam, arah derajat). Hasil: persentase per sektor 16 arah x kelas kecepatan."""
    n = len(samples)
    secs = [[0] * len(BIN_LABELS) for _ in range(16)]
    calm, ssum, smax = 0, 0.0, 0.0
    ux = uy = 0.0
    for sp, d in samples:
        ssum += sp; smax = max(smax, sp)
        if sp < CALM:
            calm += 1
            continue
        secs[sector(d)][_bin(sp)] += 1
        ux += sp * math.sin(math.radians(d)); uy += sp * math.cos(math.radians(d))
    moving = n - calm
    sectors = []
    for i in range(16):
        cnt = sum(secs[i])
        sectors.append({"i": i, "deg": i * 22.5, "abbr": ABBR[i], "name": NAME[i], "count": cnt,
                        "pct": round(100.0 * cnt / n, 2) if n else 0.0,
                        "bins": [round(100.0 * c / n, 2) if n else 0.0 for c in secs[i]]})
    prev = max(sectors, key=lambda s: s["count"]) if moving else None
    # arah resultan (rata-rata vektor) menunjukkan dari mana angin dominan datang
    mean_dir = (math.degrees(math.atan2(ux, uy)) % 360) if moving and (abs(ux) + abs(uy)) > 1e-9 else None
    return {"n": n, "calm_pct": round(100.0 * calm / n, 1) if n else 0.0, "sectors": sectors, "bins": BIN_LABELS,
            "mean_speed": round(ssum / n, 1) if n else None, "max_speed": round(smax, 1) if n else None,
            "prevailing": {"abbr": prev["abbr"], "name": prev["name"], "pct": prev["pct"]} if prev and prev["count"] else None,
            "mean_dir": compass(mean_dir)}


def demo_history(days: int = 30, now: float | None = None) -> list[tuple[int, float, float, float]]:
    """Riwayat angin contoh (angin tenggara dominan, berbalik barat laut saat sore) untuk mode demo."""
    now = int((now or time.time()) // 3600 * 3600)
    rnd = random.Random(7)
    out = []
    for h in range(days * 24, 0, -1):
        ts = now - h * 3600
        hour = (ts // 3600 + 7) % 24                      # kira-kira WIB
        base = 135 + (150 if 13 <= hour <= 18 else 0) + 30 * math.sin(ts / 86400 * 2 * math.pi)
        d = (base + rnd.gauss(0, 28)) % 360
        sp = max(0.0, 6 + 5 * math.sin((hour - 9) / 24 * 2 * math.pi) + rnd.gauss(0, 3) + (6 if 13 <= hour <= 18 else 0))
        out.append((ts, round(sp, 1), round(d, 0), round(sp * 1.7 + rnd.random() * 4, 1)))
    return out
