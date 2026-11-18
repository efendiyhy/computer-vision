# EmisiSense Vision

Dasbor **visi komputer lalu lintas + cuaca waktu nyata** untuk penelitian *EmisiSense* (PDU 2026, Lab AQHI, Universitas Brawijaya). Sistem membaca video CCTV, mendeteksi dan melacak kendaraan, mengklasifikasikan jenisnya, memperkirakan kecepatan, menghitung arus per arah, dan menampilkannya bersama cuaca serta kualitas udara dari Open-Meteo dalam satu dasbor web interaktif.

![Dasbor (mode demo)](docs/dashboard-demo.png)

## Sumber CCTV acuan

Sumber bawaan adalah CCTV Kota Malang yang menjadi acuan penelitian:

```
https://cctvmalang.24hour.id/twentyfourhourid/proxy.php?id=767576969564466612969572
```

Tautan ini tersimpan sebagai nilai bawaan (`emisisense_vision/config.py`) dan tombol **Pakai CCTV acuan** di pengaturan selalu mengembalikannya.

## Menjalankan

Butuh Python 3.10+.

```bash
# Windows: klik dua kali run.bat   |   Linux/macOS: ./run.sh
# atau manual:
pip install -r requirements.txt
python run.py                   # CCTV acuan, buka http://localhost:5000
python run.py --demo            # simulasi lalu lintas, tanpa CCTV/internet
python run.py --source video.mp4
python run.py --source rtsp://...  --port 8080 --host 0.0.0.0
```

`run.bat`/`run.sh` membuat lingkungan virtual dan memasang dependensi pada peluncuran pertama.

## Fitur

| Fitur | Keterangan |
|---|---|
| Deteksi & jenis | Mobil, motor, bus, sepeda (MobileNet-SSD bawaan); truk bila memakai YOLO. Deteksi dua lintasan (frame penuh + zona diperbesar) agar kendaraan kecil/jauh tertangkap. |
| Pelacakan | Filter Kalman + asosiasi Hungarian (IoU + jarak pusat), voting jenis agar label stabil, ID konsisten untuk banyak kendaraan sekaligus. |
| Hitung & arah | Garis hitung bebas digeser; hitungan per arah dan per jenis; satu kendaraan dihitung satu kali (tahan getar di garis). |
| Kecepatan | Perpindahan titik kontak tanah, dihaluskan. Skala otomatis dari ukuran khas jenis kendaraan, atau **kalibrasi manual** (klik dua titik + panjang nyata). **Hanya estimasi.** |
| Kepadatan | Jumlah dan SMP di zona pengamatan, level Lengang–Sangat padat (indikatif). |
| Cuaca & udara | Open-Meteo (suhu, kelembapan, angin, hujan, prakiraan 12 jam, US AQI, PM2.5, PM10, NO₂, CO, SO₂, O₃), diambil server tiap 60 detik. |
| Interaktif | Atur garis, zona, kalibrasi langsung di atas video; ganti sumber, detektor, ambang, lokasi cuaca, bobot SMP; tampilkan/sembunyikan lapisan; foto; reset. |
| Data | Log CSV otomatis di `data/` (kejadian lintas + agregat per menit lengkap dengan cuaca & AQI), serta unduhan CSV dari dasbor. |

## Menyesuaikan lokasi

Koordinat bawaan cuaca adalah pusat Kota Malang. Isi koordinat titik CCTV yang sebenarnya di **Pengaturan → Lokasi cuaca**. Pengaturan disimpan di `config.json`.

## Detektor YOLO (opsional)

```bash
pip install ultralytics
```
Lalu pilih **YOLO** di Pengaturan (bobot `yolov8n.pt` terunduh otomatis saat pertama dipakai). Lebih akurat dan mengenali truk, tetapi lebih berat.

## Struktur

```
run.py                      # peluncur
emisisense_vision/
  config.py                 # konfigurasi + tautan CCTV acuan
  detector.py               # MobileNet-SSD / YOLO
  tracker.py                # Kalman + Hungarian
  analytics.py              # hitung, kecepatan, kepadatan, log CSV
  weather.py                # Open-Meteo (cuaca + kualitas udara)
  pipeline.py               # grab -> deteksi -> lacak -> overlay -> MJPEG
  simulator.py              # mode demo
  server.py                 # Flask: /video, /api/stream (SSE), /api/*
  web/                      # index.html, app.css, app.js (tanpa CDN)
models/                     # model MobileNet-SSD (Caffe)
legacy/                     # skrip penghitung mobil versi awal
tests/                      # pytest
```

API ringkas: `GET /api/state`, `GET /api/stream` (SSE), `GET|POST /api/config`, `POST /api/calibrate`, `GET /api/export/events.csv`, `GET /api/export/minutes.csv`.

## Catatan keterbatasan

- Kecepatan dan SMP adalah **perkiraan**; untuk pelaporan, lakukan kalibrasi dengan jarak nyata di lokasi dan validasi dengan pengukuran lapangan.
- Akurasi bergantung pada sudut kamera, resolusi, dan cahaya; MobileNet-SSD kurang baik untuk kendaraan sangat kecil atau terhalang.
- Peningkatan akurasi: pakai YOLO, kecilkan "deteksi tiap N frame", sempitkan zona pengamatan pada jalan.
- Uji: `pip install pytest && pytest`.

Lisensi model MobileNet-SSD mengikuti sumber aslinya (chuanqi305/MobileNet-SSD).
