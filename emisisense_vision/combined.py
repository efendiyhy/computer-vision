"""Dokumen sinkron: hitungan kendaraan (vision) per menit + rata-rata sensor PM dan Gas lokal per menit + cuaca Open-Meteo.

Vision mencatat per menit, maka sensor PM dan Gas juga dirata-ratakan per menit (khusus dokumen ini). Satu baris = satu menit
pencatatan vision. Menit tanpa pembacaan sensor diisi dari menit sebelumnya (maks ``gap`` detik) dan ditandai di ``sensor_terisi``.
Data mentah sensor tetap tersedia lewat unduhan tersendiri.
"""
from __future__ import annotations

import csv
import io
from datetime import datetime

from .pmgas import METRICS, PmGasStore

CLASSES = ["car", "motorbike", "bus", "truck", "bicycle", "other", "person"]
SENSOR_COLS = [("pm1", "pm1_ugm3"), ("pm25", "pm25_ugm3"), ("pm10", "pm10_ugm3"), ("co", "co_ppm"), ("co2", "co2_ppm"), ("no2", "no2_ppm"),
               ("temp", "suhu_sensor_c"), ("rh", "rh_sensor_persen")]
HEAD = (["waktu_menit", *CLASSES, "total", "smp", "kecepatan_rata_kmh"] + [h for _, h in SENSOR_COLS] + ["n_pm", "n_gas", "sensor_terisi"]
        + ["suhu_openmeteo_c", "rh_openmeteo_persen", "hujan_openmeteo_mm", "angin_openmeteo_kmh", "arah_angin_openmeteo_derajat",
           "pm2_5_openmeteo", "pm10_openmeteo", "no2_openmeteo", "co_openmeteo", "us_aqi_openmeteo"])


def combined_rows(vision_rows, pg: PmGasStore, gap: int):
    mins = [r["minute"] for r in vision_rows]
    sens = pg.minute_series(mins, gap=gap, fill=gap > 0)
    out = []
    for r in vision_rows:
        s = sens.get(r["minute"])
        sv = s["v"] if s else {}
        out.append([datetime.fromtimestamp(r["minute"]).astimezone().isoformat(timespec="minutes"),
                    *[r[c] for c in CLASSES], r["total"], r["pcu"], round(r["sp_sum"] / r["sp_n"], 1) if r["sp_n"] else None,
                    *[sv.get(k) for k, _ in SENSOR_COLS], s["n_pm"] if s else 0, s["n_gas"] if s else 0,
                    ";".join(h for (k, h) in SENSOR_COLS if k in (s["filled"] if s else [])),
                    r["temp"], r["rh"], r["rain"], r["wind"], r["wind_dir"], r["pm2_5"], r["pm10"], r["no2"], r["co"], r["us_aqi"]])
    return out


def to_csv(head, rows) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(head)
    w.writerows(rows)
    return buf.getvalue()
