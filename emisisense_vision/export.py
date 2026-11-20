"""Bantuan unduhan: rentang waktu (tanggal + jam), paket ZIP berisi CSV dan keterangan data, serta kamus kolom.

Setiap unduhan berupa ZIP berisi:
  <nama>.csv         data (UTF-8 dengan BOM, langsung terbuka di Excel)
  KETERANGAN.txt     data apa ini, rentang waktu, jumlah baris, cara pengolahan, dan arti tiap kolom beserta satuan
"""
from __future__ import annotations

import io
import re
import zipfile
from datetime import datetime, timedelta

from flask import Response

# ----------------------------------------------------------------------------- rentang waktu
_FORMATS = (("%Y-%m-%dT%H:%M:%S", 1), ("%Y-%m-%dT%H:%M", 60), ("%Y-%m-%d %H:%M:%S", 1), ("%Y-%m-%d %H:%M", 60), ("%Y-%m-%d", None))


def _parse(v: str | None, end: bool):
    if not v:
        return None
    v = v.strip()
    for fmt, step in _FORMATS:
        try:
            d = datetime.strptime(v, fmt)
        except ValueError:
            continue
        if step is None:                       # tanggal saja: tanggal akhir ikut penuh
            return (d + timedelta(days=1)).timestamp() if end else d.timestamp()
        return d.timestamp() + (step if end else 0)   # jam akhir ikut sampai menit/detik itu selesai
    return None


def parse_range(args) -> tuple[float | None, float | None]:
    """?from=...&to=... (waktu setempat WIB). Dapat berupa tanggal (YYYY-MM-DD) atau tanggal+jam (YYYY-MM-DDTHH:MM)."""
    return _parse(args.get("from"), False), _parse(args.get("to"), True)


def range_text(t0, t1) -> str:
    f = lambda t: datetime.fromtimestamp(t).astimezone().strftime("%Y-%m-%d %H:%M:%S WIB")
    if t0 is None and t1 is None:
        return "semua data yang tersimpan"
    return f"{f(t0) if t0 is not None else 'awal data'} sampai {f(t1) if t1 is not None else 'data terakhir'} (batas akhir tidak ikut)"


def range_tag(t0, t1) -> str:
    if t0 is None and t1 is None:
        return "semua"
    f = lambda t: datetime.fromtimestamp(t).strftime("%Y%m%d-%H%M")
    return f"{f(t0) if t0 is not None else 'awal'}_{f(t1) if t1 is not None else 'akhir'}"


# ----------------------------------------------------------------------------- keterangan + ZIP
def keterangan(title: str, about: str, columns: list[tuple[str, str]], t0, t1, rows: int, notes: list[str] = (), version: str = "") -> str:
    L = [title.upper(), "=" * len(title), "", "DATA APA INI", about, "", "RENTANG WAKTU", range_text(t0, t1),
         "", f"JUMLAH BARIS DATA: {rows}", "", "ZONA WAKTU", "Waktu setempat WIB (UTC+7) kecuali kolom yang bernama *_utc.", ""]
    if notes:
        L += ["CATATAN PENGOLAHAN"] + [f"- {n}" for n in notes] + [""]
    L += ["ARTI KOLOM"] + [f"- {c}: {d}" for c, d in columns] + [""]
    L += [f"Dibuat: {datetime.now().astimezone():%Y-%m-%d %H:%M:%S %z}", f"Sumber: EmisiSense Vision {version} (LAB AQHI dan EK Instrumentation)".strip()]
    return "\n".join(L) + "\n"


def zip_response(base: str, csv_text: str, info: str, t0=None, t1=None) -> Response:
    base = re.sub(r"[^A-Za-z0-9_-]+", "_", base).strip("_") or "data"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(f"{base}.csv", "﻿" + csv_text)
        z.writestr("KETERANGAN.txt", "﻿" + info)
    name = f"{base}_{range_tag(t0, t1)}.zip"
    return Response(buf.getvalue(), mimetype="application/zip", headers={"Content-Disposition": f'attachment; filename="{name}"'})


def zip_file_response(path, base: str, info: str, download_name: str) -> Response:
    """ZIP untuk berkas besar (mis. database) + KETERANGAN.txt."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(path, base)
        z.writestr("KETERANGAN.txt", "﻿" + info)
    return Response(buf.getvalue(), mimetype="application/zip", headers={"Content-Disposition": f'attachment; filename="{download_name}"'})


# ----------------------------------------------------------------------------- kamus kolom
CLS = [("car", "mobil"), ("motorbike", "sepeda motor"), ("bus", "bus"), ("truck", "truk"), ("bicycle", "sepeda"), ("other", "kendaraan lain"), ("person", "pejalan kaki")]

COL_EVENTS = [("waktu", "Waktu kendaraan melewati garis hitung (ISO 8601, WIB)"), ("id_kendaraan", "Nomor pelacak kendaraan (unik selama pelacakan)"),
              ("jenis", "Jenis kendaraan: car, motorbike, bus, truck, bicycle, other, person"), ("garis", "Nama garis hitung yang dilewati"),
              ("arah", "Arah yang dihitung garis tersebut"), ("kecepatan_kmh", "Perkiraan kecepatan (km/jam); kosong bila belum dapat diukur"),
              ("kendaraan_unik", "1 = kejadian pertama kendaraan itu, 0 = melintas lagi"), ("cara_hitung", "Cara kendaraan terhitung (melewati garis atau di luar garis)")]

COL_MINUTES = ([("waktu_menit", "Awal menit pencatatan (ISO 8601, WIB)")] + [(c, f"Jumlah {n} yang terhitung pada menit itu") for c, n in CLS] +
               [("total", "Jumlah semua kendaraan (tanpa pejalan kaki)"), ("smp", "Volume dalam satuan mobil penumpang (SMP/PCU)"),
                ("kecepatan_rata_kmh", "Kecepatan rata-rata kendaraan pada menit itu (km/jam)"),
                ("suhu_c", "Suhu udara dari Open-Meteo (°C)"), ("rh_persen", "Kelembapan relatif dari Open-Meteo (%)"), ("hujan_mm", "Curah hujan dari Open-Meteo (mm)"),
                ("angin_kmh", "Kecepatan angin dari Open-Meteo (km/jam)"), ("arah_angin_derajat", "Arah ANGIN DATANG dari Open-Meteo (derajat, 0 = utara)"),
                ("arah_mata_angin", "Arah angin datang dalam mata angin"), ("pm2_5", "PM2,5 dari Open-Meteo (µg/m³) — model, bukan sensor lokal"),
                ("pm10", "PM10 dari Open-Meteo (µg/m³)"), ("co", "CO dari Open-Meteo (µg/m³)"), ("no2", "NO₂ dari Open-Meteo (µg/m³)"),
                ("us_aqi", "Indeks kualitas udara US AQI dari Open-Meteo"),
                ("cuaca_sinkron", "1 = cuaca diisi belakangan lewat tombol Sinkronisasi (nilai per jam); 0 = diambil saat itu")])

COL_WEATHER = [("waktu", "Waktu rekaman cuaca (ISO 8601, WIB)"), ("suhu_c", "Suhu udara (°C)"), ("rh_persen", "Kelembapan relatif (%)"), ("terasa_c", "Suhu terasa (°C)"),
               ("hujan_mm", "Curah hujan (mm)"), ("kode_cuaca", "Kode cuaca WMO"), ("awan_persen", "Tutupan awan (%)"), ("tekanan_hpa", "Tekanan permukaan laut (hPa)"),
               ("angin_kmh", "Kecepatan angin (km/jam)"), ("arah_angin_derajat", "Arah angin DATANG (derajat, 0 = utara)"), ("arah_mata_angin", "Arah angin datang (mata angin)"),
               ("hembusan_kmh", "Hembusan angin (km/jam)"), ("us_aqi", "Indeks kualitas udara US AQI"), ("pm2_5", "PM2,5 (µg/m³)"), ("pm10", "PM10 (µg/m³)"),
               ("co", "CO (µg/m³)"), ("no2", "NO₂ (µg/m³)"), ("so2", "SO₂ (µg/m³)"), ("o3", "O₃ (µg/m³)"), ("lat", "Lintang lokasi"), ("lon", "Bujur lokasi"), ("lokasi", "Nama lokasi")]

COL_PM_MERGED = [("waktu_wib", "Waktu UKUR sensor (ISO 8601, WIB), ketelitian 1 detik"), ("waktu_utc", "Waktu ukur yang sama dalam UTC"),
                 ("session_name", "Nama sesi sampling yang aktif saat data diterima"), ("label", "Label kondisi/eksperimen yang aktif saat data diterima"),
                 ("sync_status", "LENGKAP = PM dan Gas ada pada detik itu; HANYA_PM / HANYA_GAS = salah satu alat tidak mengirim pada detik itu (nilainya diisi, lihat filled_columns); LABEL_BERBEDA = label kedua alat berbeda"),
                 ("time_basis", "SENSOR = memakai jam sensor; RECEIVED = jam sensor tidak sah sehingga memakai waktu terima"),
                 ("pm1_avg", "PM1 rata-rata dua sensor PMS (µg/m³)"), ("pm25_avg", "PM2,5 rata-rata dua sensor PMS (µg/m³)"), ("pm10_avg", "PM10 rata-rata dua sensor PMS (µg/m³)"),
                 ("co_ppm", "Karbon monoksida (ppm)"), ("co2_ppm", "Karbon dioksida (ppm)"), ("no2_ppm", "Nitrogen dioksida (ppm)"),
                 ("pm1_pms1 … pm10_pms2", "PM1, PM2,5, PM10 mentah sensor PMS nomor 1 dan 2 (µg/m³)"), ("suhu", "Suhu dari modul PM (°C)"), ("kelembapan", "Kelembapan dari modul PM (%)"),
                 ("gas_suhu_c", "Suhu dari modul Gas (°C)"), ("gas_rh_pct", "Kelembapan dari modul Gas (%)"), ("gas_red_v, gas_nox_v", "Tegangan sensor gas RED dan NOx (V)"),
                 ("gas_red_ratio, gas_nox_ratio", "Rasio Rs/R0 sensor gas RED dan NOx"), ("pm_sample_name, gas_sample_name", "Nama sampel dari firmware tiap alat"),
                 ("pm_uptime_ms, gas_uptime_ms", "Waktu hidup alat sejak menyala (ms)"),
                 ("filled_columns", "Daftar kolom pada baris itu yang KOSONG lalu diisi dari nilai valid sebelumnya; kosong = semua nilai asli hasil ukur")]

COL_PM_RAW = [("received_at", "Waktu paket diterima server (UTC)"), ("timestamp", "Waktu ukur menurut jam sensor (UTC)"), ("event_id", "ID unik paket"),
              ("device_id", "ID perangkat ESP32"), ("device_type", "pm = alat partikulat, gas = alat gas"), ("sample_name", "Nama sampel dari firmware"),
              ("uptime_ms", "Waktu hidup alat sejak menyala (ms)"), ("pm1_pms1 … pm10_pms2", "PM1, PM2,5, PM10 mentah sensor PMS 1 dan 2 (µg/m³)"),
              ("suhu, kelembapan", "Suhu (°C) dan kelembapan (%) dari modul PM"), ("co_ppm, co2_ppm, no2_ppm", "CO, CO₂, NO₂ (ppm)"),
              ("suhu_c, rh_pct", "Suhu (°C) dan kelembapan (%) dari modul Gas"), ("red_v, nox_v, red_ratio, nox_ratio", "Tegangan (V) dan rasio Rs/R0 sensor gas"),
              ("session_name, label", "Nama sesi dan label yang aktif saat paket diterima")]

COL_COMBINED = ([("waktu_menit", "Awal menit (ISO 8601, WIB). Satu baris = satu menit pencatatan kendaraan oleh vision")] +
                [(c, f"Jumlah {n} yang terhitung pada menit itu") for c, n in CLS] +
                [("total", "Jumlah semua kendaraan (tanpa pejalan kaki)"), ("smp", "Volume dalam SMP/PCU"), ("kecepatan_rata_kmh", "Kecepatan rata-rata kendaraan (km/jam)"),
                 ("pm1_ugm3, pm25_ugm3, pm10_ugm3", "RATA-RATA PER MENIT PM dari sensor lokal (rata-rata dua sensor PMS), µg/m³"),
                 ("co_ppm, co2_ppm, no2_ppm", "RATA-RATA PER MENIT gas dari sensor lokal, ppm"),
                 ("suhu_sensor_c, rh_sensor_persen", "Rata-rata per menit suhu dan kelembapan dari modul PM dan Gas"),
                 ("n_pm, n_gas", "Banyaknya pembacaan PM dan Gas yang dirata-ratakan pada menit itu (≈60 bila alat mengirim 1 Hz)"),
                 ("sensor_terisi", "Kolom sensor yang kosong lalu diisi dari menit sebelumnya; kosong = semua nilai asli hasil rata-rata"),
                 ("suhu_openmeteo_c, rh_openmeteo_persen, hujan_openmeteo_mm", "Cuaca Open-Meteo pada menit itu (bukan sensor lokal)"),
                 ("angin_openmeteo_kmh, arah_angin_openmeteo_derajat", "Angin Open-Meteo; arah = arah angin DATANG (derajat, 0 = utara)"),
                 ("pm2_5_openmeteo, pm10_openmeteo, no2_openmeteo, co_openmeteo, us_aqi_openmeteo", "Kualitas udara model Open-Meteo (µg/m³; AQI tanpa satuan)")])

COL_DB = [("emisisense.db", "Basis data SQLite lalu lintas: tabel events (kejadian), minutes (agregat per menit), weather, wind_hourly"),
          ("pmgas.db (bila ada)", "Basis data SQLite sensor PM dan Gas: readings (data mentah), minute_agg, meta")]
