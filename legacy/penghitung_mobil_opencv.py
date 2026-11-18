import os
import time
from pathlib import Path

import cv2
import numpy as np


STREAM_URL = (
    "https://cctvmalang.24hour.id/twentyfourhourid/"
    "proxy.php?id=767576969564466612969572"
)
NAMA_JENDELA = "CCTV - Penghitung Mobil (Q untuk keluar)"
LEBAR_TAMPILAN = 960
TINGGI_TAMPILAN = 540
LEBAR_DASHBOARD = 1400
TINGGI_DASHBOARD = 640
VIDEO_X = 20
VIDEO_Y = 70
PANEL_X = 1000
PANEL_Y = 70
LEBAR_PANEL = 380
TINGGI_PANEL = 540
WARNA_TEKS = (0, 0, 255)
AMBANG_KEYAKINAN = 0.45
DETEKSI_SETIAP_N_FRAME = 2

DIREKTORI_PROGRAM = Path(__file__).resolve().parent
FILE_PROTOTXT = DIREKTORI_PROGRAM / "models" / "deploy.prototxt"
FILE_MODEL = DIREKTORI_PROGRAM / "models" / "mobilenet_iter_73000.caffemodel"

# Area deteksi awal. Geser bagian dalam kotak untuk memindahkannya.
# Tarik pegangan merah di kanan bawah untuk mengubah ukuran.
roi = {
    "x1": 160,
    "y1": 120,
    "x2": 800,
    "y2": 450,
    "mode": None,
    "offset_x": 0,
    "offset_y": 0,
}


def atur_kotak(event, x, y, _flags, _param):
    """Pindahkan atau ubah ukuran kotak deteksi menggunakan mouse."""
    # Koordinat mouse dashboard diubah menjadi koordinat lokal video.
    x -= VIDEO_X
    y -= VIDEO_Y

    if event == cv2.EVENT_LBUTTONUP:
        roi["mode"] = None
        return

    if event == cv2.EVENT_LBUTTONDOWN and not (
        0 <= x < LEBAR_TAMPILAN and 0 <= y < TINGGI_TAMPILAN
    ):
        return

    ukuran_handle = 18
    dekat_handle = (
        abs(x - roi["x2"]) <= ukuran_handle
        and abs(y - roi["y2"]) <= ukuran_handle
    )
    di_dalam_kotak = (
        roi["x1"] <= x <= roi["x2"] and roi["y1"] <= y <= roi["y2"]
    )

    if event == cv2.EVENT_LBUTTONDOWN:
        if dekat_handle:
            roi["mode"] = "resize"
        elif di_dalam_kotak:
            roi["mode"] = "move"
            roi["offset_x"] = x - roi["x1"]
            roi["offset_y"] = y - roi["y1"]

    elif event == cv2.EVENT_MOUSEMOVE:
        if roi["mode"] == "move":
            lebar = roi["x2"] - roi["x1"]
            tinggi = roi["y2"] - roi["y1"]
            x1_baru = max(0, min(LEBAR_TAMPILAN - lebar, x - roi["offset_x"]))
            y1_baru = max(0, min(TINGGI_TAMPILAN - tinggi, y - roi["offset_y"]))
            roi["x1"], roi["y1"] = x1_baru, y1_baru
            roi["x2"], roi["y2"] = x1_baru + lebar, y1_baru + tinggi

        elif roi["mode"] == "resize":
            roi["x2"] = max(roi["x1"] + 100, min(LEBAR_TAMPILAN - 1, x))
            roi["y2"] = max(roi["y1"] + 100, min(TINGGI_TAMPILAN - 1, y))

def titik_dalam_roi(cx, cy):
    return roi["x1"] <= cx <= roi["x2"] and roi["y1"] <= cy <= roi["y2"]


def deteksi_mobil(net, frame):
    """Deteksi kelas car (VOC class 7); motorbike tidak ikut diproses."""
    blob = cv2.dnn.blobFromImage(
        frame,
        scalefactor=0.007843,
        size=(300, 300),
        mean=127.5,
    )
    net.setInput(blob)
    hasil_dnn = net.forward()
    tinggi, lebar = frame.shape[:2]

    kotak = []
    keyakinan = []

    for indeks in range(hasil_dnn.shape[2]):
        confidence = float(hasil_dnn[0, 0, indeks, 2])
        kelas = int(hasil_dnn[0, 0, indeks, 1])

        # VOC: car = 7 dan motorbike = 14. Hanya kelas car yang diterima.
        if kelas != 7 or confidence < AMBANG_KEYAKINAN:
            continue

        x1, y1, x2, y2 = (
            hasil_dnn[0, 0, indeks, 3:7]
            * np.array([lebar, tinggi, lebar, tinggi])
        ).astype(int)
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(lebar - 1, x2), min(tinggi - 1, y2)

        if x2 <= x1 or y2 <= y1:
            continue

        kotak.append([x1, y1, x2 - x1, y2 - y1])
        keyakinan.append(confidence)

    if not kotak:
        return []

    # Hilangkan kotak ganda untuk mobil yang sama.
    indeks_terpilih = cv2.dnn.NMSBoxes(
        kotak,
        keyakinan,
        AMBANG_KEYAKINAN,
        0.3,
    )

    hasil = []
    for indeks in np.array(indeks_terpilih).flatten():
        x, y, w, h = kotak[int(indeks)]
        hasil.append((x, y, x + w, y + h, keyakinan[int(indeks)]))
    return hasil


class PelacakMobil:
    """Pelacak centroid sederhana agar satu mobil tidak dihitung setiap frame."""

    def __init__(self, jarak_maksimum=120, hilang_maksimum=12):
        self.berikutnya = 1
        self.objek = {}
        self.jarak_maksimum = jarak_maksimum
        self.hilang_maksimum = hilang_maksimum

    def _daftar(self, deteksi):
        x1, y1, x2, y2, confidence = deteksi
        self.objek[self.berikutnya] = {
            "centroid": ((x1 + x2) // 2, (y1 + y2) // 2),
            "kotak": (x1, y1, x2, y2),
            "confidence": confidence,
            "hilang": 0,
            "sudah_dihitung": False,
        }
        self.berikutnya += 1

    def _hapus_hilang(self):
        for id_mobil in list(self.objek):
            if self.objek[id_mobil]["hilang"] > self.hilang_maksimum:
                del self.objek[id_mobil]

    def perbarui(self, daftar_deteksi):
        if not daftar_deteksi:
            for data in self.objek.values():
                data["hilang"] += 1
            self._hapus_hilang()
            return self.objek

        centroid_baru = np.array(
            [
                ((x1 + x2) // 2, (y1 + y2) // 2)
                for x1, y1, x2, y2, _confidence in daftar_deteksi
            ]
        )

        if not self.objek:
            for deteksi in daftar_deteksi:
                self._daftar(deteksi)
            return self.objek

        daftar_id = list(self.objek)
        centroid_lama = np.array(
            [self.objek[id_mobil]["centroid"] for id_mobil in daftar_id]
        )
        jarak = np.linalg.norm(
            centroid_lama[:, np.newaxis] - centroid_baru[np.newaxis, :],
            axis=2,
        )

        urutan_baris = jarak.min(axis=1).argsort()
        pasangan_kolom = jarak.argmin(axis=1)[urutan_baris]
        baris_terpakai = set()
        kolom_terpakai = set()

        for baris, kolom in zip(urutan_baris, pasangan_kolom):
            if baris in baris_terpakai or kolom in kolom_terpakai:
                continue
            if jarak[baris, kolom] > self.jarak_maksimum:
                continue

            id_mobil = daftar_id[baris]
            x1, y1, x2, y2, confidence = daftar_deteksi[kolom]
            self.objek[id_mobil].update(
                centroid=tuple(centroid_baru[kolom]),
                kotak=(x1, y1, x2, y2),
                confidence=confidence,
                hilang=0,
            )
            baris_terpakai.add(baris)
            kolom_terpakai.add(kolom)

        for baris, id_mobil in enumerate(daftar_id):
            if baris not in baris_terpakai:
                self.objek[id_mobil]["hilang"] += 1

        for kolom, deteksi in enumerate(daftar_deteksi):
            if kolom not in kolom_terpakai:
                self._daftar(deteksi)

        self._hapus_hilang()
        return self.objek


def gambar_kartu(canvas, x, y, lebar, tinggi, judul, nilai):
    """Gambar satu kartu statistik pada panel samping."""
    cv2.rectangle(canvas, (x, y), (x + lebar, y + tinggi), (48, 48, 48), -1)
    cv2.rectangle(canvas, (x, y), (x + lebar, y + tinggi), (80, 80, 80), 1)
    cv2.putText(
        canvas,
        judul,
        (x + 12, y + 22),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.40,
        WARNA_TEKS,
        1,
    )
    cv2.putText(
        canvas,
        str(nilai),
        (x + 12, y + 57),
        cv2.FONT_HERSHEY_SIMPLEX,
        1.0,
        WARNA_TEKS,
        2,
    )


def gambar_histogram(canvas, x, y, lebar, tinggi, riwayat, menit_ini):
    """Gambar histogram menit selesai ditambah data menit yang sedang berjalan."""
    cv2.rectangle(canvas, (x, y), (x + lebar, y + tinggi), (38, 38, 38), -1)
    cv2.rectangle(canvas, (x, y), (x + lebar, y + tinggi), (80, 80, 80), 1)
    cv2.putText(
        canvas,
        "HISTOGRAM MOBIL / MENIT",
        (x + 12, y + 24),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.52,
        WARNA_TEKS,
        1,
    )

    data_lama = riwayat[-7:]
    data = data_lama + [menit_ini]
    label = [f"-{len(data_lama) - i}" for i in range(len(data_lama))] + ["NOW"]
    nilai_maksimum = max(max(data, default=0), 1)

    grafik_x1 = x + 35
    grafik_y1 = y + 42
    grafik_x2 = x + lebar - 12
    grafik_y2 = y + tinggi - 30
    tinggi_grafik = grafik_y2 - grafik_y1

    for bagian in range(3):
        posisi_y = grafik_y2 - round(tinggi_grafik * bagian / 2)
        nilai_y = round(nilai_maksimum * bagian / 2)
        cv2.line(
            canvas,
            (grafik_x1, posisi_y),
            (grafik_x2, posisi_y),
            (65, 65, 65),
            1,
        )
        cv2.putText(
            canvas,
            str(nilai_y),
            (x + 5, posisi_y + 4),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.35,
            WARNA_TEKS,
            1,
        )

    jumlah_batang = len(data)
    lebar_slot = max(1, (grafik_x2 - grafik_x1) // jumlah_batang)
    lebar_batang = max(8, int(lebar_slot * 0.58))

    for indeks, nilai in enumerate(data):
        tengah_x = grafik_x1 + indeks * lebar_slot + lebar_slot // 2
        tinggi_batang = round((nilai / nilai_maksimum) * (tinggi_grafik - 10))
        atas_y = grafik_y2 - tinggi_batang
        cv2.rectangle(
            canvas,
            (tengah_x - lebar_batang // 2, atas_y),
            (tengah_x + lebar_batang // 2, grafik_y2),
            (0, 0, 190),
            -1,
        )
        cv2.putText(
            canvas,
            str(nilai),
            (tengah_x - 7, max(grafik_y1 + 10, atas_y - 5)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.4,
            WARNA_TEKS,
            1,
        )
        cv2.putText(
            canvas,
            label[indeks],
            (tengah_x - 12, grafik_y2 + 18),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.35,
            WARNA_TEKS,
            1,
        )


def buat_dashboard(video_frame, menit_ini, menit_lalu, total, sisa, riwayat):
    """Gabungkan video dan panel statistik menjadi satu dashboard."""
    canvas = np.full(
        (TINGGI_DASHBOARD, LEBAR_DASHBOARD, 3),
        (18, 18, 18),
        dtype=np.uint8,
    )

    cv2.putText(
        canvas,
        "DASHBOARD DETEKSI MOBIL REAL-TIME",
        (20, 40),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.95,
        WARNA_TEKS,
        2,
    )

    canvas[
        VIDEO_Y : VIDEO_Y + TINGGI_TAMPILAN,
        VIDEO_X : VIDEO_X + LEBAR_TAMPILAN,
    ] = video_frame
    cv2.rectangle(
        canvas,
        (VIDEO_X - 2, VIDEO_Y - 2),
        (VIDEO_X + LEBAR_TAMPILAN + 2, VIDEO_Y + TINGGI_TAMPILAN + 2),
        (100, 100, 100),
        2,
    )

    cv2.rectangle(
        canvas,
        (PANEL_X, PANEL_Y),
        (PANEL_X + LEBAR_PANEL, PANEL_Y + TINGGI_PANEL),
        (28, 28, 28),
        -1,
    )
    cv2.rectangle(
        canvas,
        (PANEL_X, PANEL_Y),
        (PANEL_X + LEBAR_PANEL, PANEL_Y + TINGGI_PANEL),
        (80, 80, 80),
        2,
    )
    cv2.putText(
        canvas,
        "STATISTIK LALU LINTAS",
        (PANEL_X + 14, PANEL_Y + 30),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.68,
        WARNA_TEKS,
        2,
    )

    lebar_kartu = 108
    jarak = 10
    kartu_y = PANEL_Y + 47
    gambar_kartu(canvas, PANEL_X + 12, kartu_y, lebar_kartu, 68, "MENIT INI", menit_ini)
    gambar_kartu(
        canvas,
        PANEL_X + 12 + lebar_kartu + jarak,
        kartu_y,
        lebar_kartu,
        68,
        "MENIT LALU",
        menit_lalu,
    )
    gambar_kartu(
        canvas,
        PANEL_X + 12 + (lebar_kartu + jarak) * 2,
        kartu_y,
        lebar_kartu,
        68,
        "TOTAL SESI",
        total,
    )

    cv2.putText(
        canvas,
        f"Interval berikutnya: {sisa} detik",
        (PANEL_X + 14, PANEL_Y + 140),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.58,
        WARNA_TEKS,
        2,
    )
    cv2.putText(
        canvas,
        "Tarik ROI untuk pindah | pegangan merah: resize",
        (PANEL_X + 14, PANEL_Y + 166),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.42,
        WARNA_TEKS,
        1,
    )

    gambar_histogram(
        canvas,
        PANEL_X + 12,
        PANEL_Y + 185,
        LEBAR_PANEL - 24,
        TINGGI_PANEL - 200,
        riwayat,
        menit_ini,
    )
    return canvas


def main():
    if not FILE_PROTOTXT.exists() or not FILE_MODEL.exists():
        raise SystemExit("Model MobileNet-SSD tidak ditemukan di folder 'models'.")

    net = cv2.dnn.readNetFromCaffe(str(FILE_PROTOTXT), str(FILE_MODEL))

    os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "timeout;15000000"
    video = cv2.VideoCapture(STREAM_URL, cv2.CAP_FFMPEG)
    if not video.isOpened():
        raise SystemExit("Stream CCTV tidak dapat dibuka.")

    pelacak = PelacakMobil()
    nomor_frame = 0
    jumlah_menit_ini = 0
    jumlah_menit_lalu = 0
    jumlah_total = 0
    riwayat_per_menit = []
    awal_interval = time.monotonic()

    cv2.namedWindow(NAMA_JENDELA)
    cv2.setMouseCallback(NAMA_JENDELA, atur_kotak)

    while True:
        berhasil, frame = video.read()
        if not berhasil:
            print("Stream terputus atau frame tidak tersedia.")
            break

        frame = cv2.resize(frame, (LEBAR_TAMPILAN, TINGGI_TAMPILAN))
        nomor_frame += 1

        if nomor_frame % DETEKSI_SETIAP_N_FRAME == 0:
            daftar_deteksi = deteksi_mobil(net, frame)
            objek = pelacak.perbarui(daftar_deteksi)
        else:
            objek = pelacak.objek

        sekarang = time.monotonic()
        while sekarang - awal_interval >= 60:
            jumlah_menit_lalu = jumlah_menit_ini
            riwayat_per_menit.append(jumlah_menit_ini)
            riwayat_per_menit = riwayat_per_menit[-30:]
            jumlah_menit_ini = 0
            awal_interval += 60

        # Hitung setiap ID mobil satu kali ketika titik tengahnya masuk ROI.
        for data in objek.values():
            cx, cy = data["centroid"]
            if titik_dalam_roi(cx, cy) and not data["sudah_dihitung"]:
                data["sudah_dihitung"] = True
                jumlah_menit_ini += 1
                jumlah_total += 1

        hasil = frame.copy()

        # Hanya tampilkan mobil yang pusatnya sedang berada di dalam ROI.
        for id_mobil, data in objek.items():
            cx, cy = data["centroid"]
            if not titik_dalam_roi(cx, cy) or data["hilang"] > 0:
                continue

            x1, y1, x2, y2 = data["kotak"]
            confidence = data["confidence"]
            cv2.rectangle(hasil, (x1, y1), (x2, y2), (0, 255, 0), 2)
            cv2.circle(hasil, (cx, cy), 4, WARNA_TEKS, -1)
            cv2.putText(
                hasil,
                f"Mobil ID {id_mobil} ({confidence * 100:.0f}%)",
                (x1, max(20, y1 - 8)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                WARNA_TEKS,
                2,
            )

        # Kotak area penghitungan dan handle untuk resize.
        cv2.rectangle(
            hasil,
            (roi["x1"], roi["y1"]),
            (roi["x2"], roi["y2"]),
            (0, 255, 255),
            3,
        )
        cv2.rectangle(
            hasil,
            (roi["x2"] - 9, roi["y2"] - 9),
            (roi["x2"] + 9, roi["y2"] + 9),
            WARNA_TEKS,
            -1,
        )

        sisa_detik = max(0, 60 - int(sekarang - awal_interval))
        dashboard = buat_dashboard(
            hasil,
            jumlah_menit_ini,
            jumlah_menit_lalu,
            jumlah_total,
            sisa_detik,
            riwayat_per_menit,
        )
        cv2.imshow(NAMA_JENDELA, dashboard)

        if cv2.waitKey(1) & 0xFF == ord("q"):
            break

    video.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
