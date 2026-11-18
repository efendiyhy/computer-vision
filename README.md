# EmisiSense Vision

Dasbor **visi komputer lalu lintas + cuaca waktu nyata** untuk penelitian *EmisiSense* (PDU 2026, Universitas Brawijaya). Sistem membaca video CCTV, mendeteksi dan melacak kendaraan, mengklasifikasikan jenisnya, memperkirakan kecepatan, menghitung arus per arah, dan menampilkannya bersama cuaca serta kualitas udara dari Open-Meteo dalam satu dasbor web interaktif. Seluruh hasil deteksi disimpan ke database SQLite.

![Dasbor (mode demo)](docs/dashboard-demo.png)

## Sumber CCTV acuan

Sumber bawaan adalah CCTV Kota Malang yang menjadi acuan penelitian:

```
https://cctvmalang.24hour.id/twentyfourhourid/proxy.php?id=767576969564466612969572
```

Tautan ini tersimpan sebagai nilai bawaan (`emisisense_vision/config.py`). Sumber dan lokasi cuaca dapat diganti kapan saja dari dasbor (kartu **Sumber video & lokasi cuaca**); tombol **CCTV Malang (acuan)** mengembalikannya.

## Pemasangan

Prasyarat: Python 3.10+ dan akses internet (untuk memasang paket). Pemasang membuat **lingkungan virtual `.venv` sendiri** di dalam folder proyek, sehingga tidak mengganggu Python sistem.

### Linux (satu baris, clone dari git)

```bash
curl -fsSL https://raw.githubusercontent.com/efendiyhy/computer-vision/main/install.sh | bash
```

Untuk server (jalan otomatis saat boot, firewall `ufw` dibuka bila aktif):

```bash
curl -fsSL https://raw.githubusercontent.com/efendiyhy/computer-vision/main/install.sh | bash -s -- --service
# opsi lain: --dir /opt/emisisense  --port 8080  --password KATASANDI
```

Saat selesai, pemasang mencetak alamat akses jaringan lokal, mis. `http://192.168.1.20:5000`. Kelola layanan: `sudo systemctl status|restart|stop emisisense-vision`, log: `journalctl -u emisisense-vision -f`.

### Windows (PowerShell)

```powershell
irm https://raw.githubusercontent.com/efendiyhy/computer-vision/main/install.ps1 | iex
```

Dengan firewall + mulai otomatis saat login (jalankan PowerShell **sebagai Administrator**):

```powershell
& ([scriptblock]::Create((irm https://raw.githubusercontent.com/efendiyhy/computer-vision/main/install.ps1))) -Firewall -AutoStart
```

Pemasang membuat pintasan **EmisiSense Vision** di Desktop dan mencetak alamat akses jaringan lokal. Jika `irm | iex` diblokir kebijakan eksekusi: `powershell -ExecutionPolicy Bypass -File install.ps1`.

### Manual (buat env sendiri dulu)

```bash
git clone https://github.com/efendiyhy/computer-vision.git
cd computer-vision
python3 -m venv .venv                  # Windows: py -3 -m venv .venv
source .venv/bin/activate              # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python run.py
```

Pakai conda? `conda create -n emisisense python=3.11 && conda activate emisisense && pip install -r requirements.txt`.

### Memperbarui

Jalankan ulang perintah pemasang. Kode ditarik dari git (`git pull`); folder `data/` dan `config.json` (data deteksi dan pengaturan) tidak ikut terhapus. Untuk layanan systemd: `sudo systemctl restart emisisense-vision` setelah pembaruan.

## Menjalankan

```bash
./run.sh            # Linux/macOS      (Windows: run.bat)
python run.py                         # CCTV acuan, dasbor di port 5000
python run.py --demo                  # simulasi lalu lintas tanpa CCTV
python run.py --source video.mp4      # berkas / URL / rtsp:// / 0 (kamera USB)
python run.py --port 8080 --password KATASANDI
python run.py --local                 # hanya dari komputer ini
```

Saat dijalankan, server **menampilkan alamat IP jaringan lokal** (dan menampilkannya juga di footer dasbor), sehingga dasbor bisa dibuka dari laptop/HP lain di jaringan yang sama:

```
  Buka dari perangkat mana pun di jaringan yang sama:
     http://192.168.1.20:5000
     http://localhost:5000
```

Bawaannya mendengarkan di semua antarmuka (`0.0.0.0`). Di jaringan bersama, pakai `--password` (atau variabel `EMISISENSE_PASSWORD`); pengaturan dasbor dapat diubah oleh siapa pun yang bisa mengaksesnya. Bila tidak terjangkau dari perangkat lain, periksa firewall server (port 5000/TCP).

## Fitur

| Fitur | Keterangan |
|---|---|
| Deteksi & jenis | Mobil, motor, bus, sepeda (MobileNet-SSD bawaan); truk bila memakai YOLO. Deteksi dua lintasan (frame penuh + zona diperbesar) agar kendaraan kecil/jauh tertangkap. |
| Pelacakan | Filter Kalman + asosiasi Hungarian, voting jenis agar label stabil, ID konsisten untuk banyak kendaraan sekaligus. |
| Hitung & arah | Garis hitung bebas digeser di atas video; hitungan per arah dan per jenis; satu kendaraan dihitung satu kali. |
| Kecepatan | Skala otomatis dari ukuran khas jenis kendaraan, atau **kalibrasi manual** (klik dua titik + panjang nyata). **Hanya estimasi.** |
| Kepadatan | Jumlah dan SMP di zona pengamatan, level Lengang sampai Sangat padat (indikatif). |
| Cuaca & udara | Open-Meteo: suhu, kelembapan, angin, hujan, prakiraan 12 jam, US AQI, PM2.5, PM10, NO₂, CO, SO₂, O₃. |
| **Sumber & lokasi** | Ubah sumber video (URL/RTSP/berkas/kamera USB, unggah video, tes koneksi) dan lokasi Open-Meteo (cari nama tempat atau isi koordinat) langsung dari web. |
| **Data tersimpan** | Lihat di bawah. |

## Penyimpanan data

Semua data ditulis otomatis ke `data/emisisense.db` (SQLite, mode WAL; mode `--demo` memakai `emisisense_demo.db` sehingga data demo tidak bercampur):

| Tabel | Isi |
|---|---|
| `events` | satu baris per kendaraan yang melintasi garis: waktu, ID, jenis, garis, arah, kecepatan, sumber video |
| `minutes` | agregat per menit: jumlah per jenis, total, SMP, kecepatan rata-rata, plus suhu, RH, hujan, angin, PM2.5, PM10, CO, NO₂, US AQI pada menit itu |
| `weather` | rekaman cuaca & kualitas udara tiap pembaruan Open-Meteo (dengan koordinat dan nama lokasi) |

- Kejadian ditulis langsung; agregat menit di-flush tiap beberapa detik dan saat aplikasi berhenti (Ctrl+C / `systemctl stop`). Bila aplikasi dihidupkan ulang pada menit yang sama, hitungan **dilanjutkan**, bukan ditimpa.
- Setiap menit yang diamati tercatat, termasuk yang berisi 0 kendaraan. Menit yang tidak ada barisnya berarti sistem tidak berjalan atau tidak ada frame.
- Tombol **Reset tampilan hitungan** hanya mengosongkan angka di layar; data di database tidak dihapus.
- Dari dasbor (kartu *Data tersimpan*): unduh CSV kejadian, per menit, cuaca & udara dengan rentang tanggal, atau salin seluruh database (`.db`). Grafik *Riwayat tersimpan* menampilkan 6 jam sampai 30 hari.
- Cadangkan cukup dengan menyalin folder `data/`. Untuk analisis: `sqlite3 data/emisisense.db "select * from minutes limit 10"` atau buka CSV di Excel/Python.

## Detektor YOLO (opsional)

```bash
.venv/bin/pip install ultralytics      # Windows: .venv\Scripts\pip install ultralytics
```
Lalu pilih **YOLO** di Pengaturan (bobot `yolov8n.pt` terunduh otomatis saat pertama dipakai). Lebih akurat dan mengenali truk, tetapi lebih berat.

## Struktur

```
install.sh / install.ps1    # pemasang Linux / Windows (clone git + .venv)
run.py  run.sh  run.bat     # peluncur
emisisense_vision/
  config.py                 # konfigurasi + tautan CCTV acuan
  detector.py  tracker.py   # MobileNet-SSD / YOLO ; Kalman + Hungarian
  analytics.py              # hitung, kecepatan, kepadatan
  storage.py                # SQLite: events, minutes, weather + ekspor CSV
  weather.py                # Open-Meteo (cuaca + kualitas udara)
  pipeline.py  simulator.py # video -> deteksi -> overlay MJPEG ; mode demo
  server.py  netinfo.py     # Flask + API ; alamat IP jaringan lokal
  web/                      # index.html, app.css, app.js (tanpa CDN)
models/  legacy/  tests/    # model SSD ; skrip awal ; pytest
```

API ringkas: `GET /api/state`, `GET /api/stream` (SSE), `GET|POST /api/config`, `POST /api/source/test`, `GET /api/geocode?q=`, `GET /api/history?hours=24`, `GET /api/storage`, `GET /api/export/{events,minutes,weather}.csv?from=YYYY-MM-DD&to=YYYY-MM-DD`, `GET /api/export/database`.

## Catatan keterbatasan

- Kecepatan dan SMP adalah **perkiraan**; untuk pelaporan, kalibrasi dengan jarak nyata di lokasi dan validasi dengan pengukuran lapangan.
- Akurasi bergantung pada sudut kamera, resolusi, dan cahaya; MobileNet-SSD kurang baik untuk kendaraan sangat kecil atau terhalang.
- Peningkatan akurasi: pakai YOLO, kecilkan "deteksi tiap N frame", sempitkan zona pengamatan pada jalan.
- Uji: `pip install pytest && pytest`.

---
Dikembangkan oleh **LAB AQHI** dan **EK Instrumentation**.
Model MobileNet-SSD mengikuti lisensi sumber aslinya (chuanqi305/MobileNet-SSD).
