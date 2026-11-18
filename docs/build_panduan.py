"""Membangun docs/panduan-kalibrasi.pdf (jalankan: python docs/build_panduan.py)."""
from pathlib import Path
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (BaseDocTemplate, Frame, CondPageBreak, Image, KeepTogether, PageBreak, PageTemplate, Paragraph,
                                Spacer, Table, TableStyle, Flowable)
from reportlab.graphics.shapes import Drawing, Line, Polygon, Rect, String, Circle

HERE = Path(__file__).resolve().parent
IMG = HERE / "panduan"
FD = "/usr/share/fonts/truetype/dejavu/"
pdfmetrics.registerFont(TTFont("S", FD + "DejaVuSans.ttf"))
pdfmetrics.registerFont(TTFont("SB", FD + "DejaVuSans-Bold.ttf"))
pdfmetrics.registerFont(TTFont("SI", FD + "DejaVuSans-Oblique.ttf"))
pdfmetrics.registerFont(TTFont("M", FD + "DejaVuSansMono.ttf"))
pdfmetrics.registerFontFamily("S", normal="S", bold="SB", italic="SI", boldItalic="SB")

INK, MUTED, ACC, LINE = colors.HexColor("#1b2530"), colors.HexColor("#5b6773"), colors.HexColor("#1a56db"), colors.HexColor("#d5dbe2")
WARN_BG, WARN_BD = colors.HexColor("#fff4d6"), colors.HexColor("#e0a800")
TIP_BG, TIP_BD = colors.HexColor("#e8f1ff"), colors.HexColor("#1a56db")
BAD_BG, BAD_BD = colors.HexColor("#fde8e8"), colors.HexColor("#c62828")

body = ParagraphStyle("body", fontName="S", fontSize=10, leading=15.5, textColor=INK, spaceAfter=6, alignment=TA_LEFT)
small = ParagraphStyle("small", parent=body, fontSize=8.6, leading=12, textColor=MUTED, spaceAfter=3)
cell = ParagraphStyle("cell", parent=body, fontSize=8.8, leading=12.2, spaceAfter=0)
cellb = ParagraphStyle("cellb", parent=cell, fontName="SB")
h1 = ParagraphStyle("h1", fontName="SB", fontSize=17, leading=22, textColor=INK, spaceBefore=4, spaceAfter=8)
h2 = ParagraphStyle("h2", fontName="SB", fontSize=12.5, leading=17, textColor=INK, spaceBefore=12, spaceAfter=5)
h3 = ParagraphStyle("h3", fontName="SB", fontSize=10.5, leading=15, textColor=ACC, spaceBefore=8, spaceAfter=3)
cap = ParagraphStyle("cap", parent=small, spaceBefore=3, spaceAfter=9)
code = ParagraphStyle("code", fontName="M", fontSize=8.8, leading=12.5, textColor=INK, backColor=colors.HexColor("#f1f4f7"),
                      borderPadding=(5, 6, 5, 6), spaceBefore=4, spaceAfter=10, leftIndent=6, rightIndent=6)
li = ParagraphStyle("li", parent=body, leftIndent=14, bulletIndent=2, spaceAfter=3)
num = ParagraphStyle("num", parent=body, leftIndent=18, bulletIndent=0, spaceAfter=4)

W = A4[0] - 4 * cm


def P(t, s=body): return Paragraph(t, s)
def bullets(items): return [Paragraph(t, li, bulletText="•") for t in items]
def steps(items): return [Paragraph(t, num, bulletText=f"{i}.") for i, t in enumerate(items, 1)]


def box(title, text, kind="tip"):
    bg, bd = {"tip": (TIP_BG, TIP_BD), "warn": (WARN_BG, WARN_BD), "bad": (BAD_BG, BAD_BD)}[kind]
    inner = [Paragraph(f"<b>{title}</b>", ParagraphStyle("bt", parent=cell, fontSize=9.2, spaceAfter=2))]
    inner += [Paragraph(x, cell) for x in (text if isinstance(text, list) else [text])]
    t = Table([[inner]], colWidths=[W])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), bg), ("LINEBEFORE", (0, 0), (0, -1), 3, bd), ("LEFTPADDING", (0, 0), (-1, -1), 10),
                           ("RIGHTPADDING", (0, 0), (-1, -1), 8), ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 7)]))
    return KeepTogether([t, Spacer(1, 9)])


def tbl(rows, widths, head=True, zebra=True):
    data = [[Paragraph(str(c), cellb if (head and r == 0) else cell) for c in row] for r, row in enumerate(rows)]
    t = Table(data, colWidths=widths, repeatRows=1 if head else 0)
    st = [("VALIGN", (0, 0), (-1, -1), "TOP"), ("LINEBELOW", (0, 0), (-1, -1), 0.4, LINE), ("TOPPADDING", (0, 0), (-1, -1), 4),
          ("BOTTOMPADDING", (0, 0), (-1, -1), 4), ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5)]
    if head:
        st += [("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eaf0f7")), ("LINEBELOW", (0, 0), (-1, 0), 1, INK)]
    t.setStyle(TableStyle(st))
    return t


def fig(name, caption, width=W * 0.8):
    from PIL import Image as PI
    w, h = PI.open(IMG / name).size
    return KeepTogether([Image(str(IMG / name), width=width, height=width * h / w), P(caption, cap)])


# ---------------------------------------------------------------- gambar bantu
def flow():
    labels = ["Sumber\ntersambung", "Zona\npengamatan", "Garis\nhitung", "Kalibrasi\nkecepatan", "Validasi\n& catat"]
    d = Drawing(W, 62)
    bw, gap = (W - 4 * 14) / 5, 14
    for i, l in enumerate(labels):
        x = i * (bw + gap)
        d.add(Rect(x, 8, bw, 46, rx=6, ry=6, fillColor=colors.HexColor("#eaf0f7"), strokeColor=ACC, strokeWidth=1))
        d.add(Circle(x + 12, 46, 8, fillColor=ACC, strokeColor=None))
        d.add(String(x + 12, 43, str(i + 1), fontName="SB", fontSize=9, fillColor=colors.white, textAnchor="middle"))
        a, b = l.split("\n")
        d.add(String(x + bw / 2 + 6, 30, a, fontName="SB", fontSize=8.6, fillColor=INK, textAnchor="middle"))
        d.add(String(x + bw / 2 + 6, 19, b, fontName="SB", fontSize=8.6, fillColor=INK, textAnchor="middle"))
        if i < 4:
            d.add(Line(x + bw + 1, 31, x + bw + gap - 3, 31, strokeColor=MUTED, strokeWidth=1.2))
            d.add(Polygon([x + bw + gap - 3, 34, x + bw + gap + 1, 31, x + bw + gap - 3, 28], fillColor=MUTED, strokeColor=None))
    return d


def perspective():
    d = Drawing(W, 150)
    cx = 120
    d.add(Polygon([cx - 22, 144, cx + 22, 144, cx + 110, 6, cx - 110, 6], fillColor=colors.HexColor("#4a5560"), strokeColor=None))
    d.add(Line(cx, 144, cx, 6, strokeColor=colors.white, strokeWidth=1.4, strokeDashArray=[7, 6]))
    Y = colors.HexColor("#f5b800")
    for x0, y0, y1, ty, t1, t2 in ((cx + 30, 12, 62, 38, "Segmen 4 m di dekat kamera", "tampak panjang: ±50 piksel"),
                                   (cx + 11, 104, 118, 111, "Segmen 4 m yang sama di kejauhan", "tampak pendek: ±14 piksel")):
        d.add(Line(x0, y0, x0, y1, strokeColor=Y, strokeWidth=4))
        d.add(Line(x0 + 4, ty, 262, ty, strokeColor=MUTED, strokeWidth=0.6))
        d.add(String(262, ty + 1, t1, fontName="SB", fontSize=8.6, fillColor=INK))
        d.add(String(262, ty - 10, t2, fontName="S", fontSize=8.6, fillColor=MUTED))
    d.add(String(262, 138, "Satu kalibrasi = satu skala (m/piksel),", fontName="SB", fontSize=8.6, fillColor=INK))
    d.add(String(262, 127, "paling tepat di kedalaman tempat Anda mengukur.", fontName="S", fontSize=8.6, fillColor=INK))
    return d


# ---------------------------------------------------------------- halaman
def deco(c, doc):
    c.saveState()
    c.setFont("S", 8); c.setFillColor(MUTED)
    if doc.page > 1:
        c.drawString(2 * cm, A4[1] - 1.2 * cm, "EmisiSense Vision 2.0  ·  Panduan garis, zona, dan kalibrasi kecepatan")
        c.setStrokeColor(LINE); c.line(2 * cm, A4[1] - 1.4 * cm, A4[0] - 2 * cm, A4[1] - 1.4 * cm)
        c.drawString(2 * cm, 1.1 * cm, "Dikembangkan oleh LAB AQHI dan EK Instrumentation")
        c.drawRightString(A4[0] - 2 * cm, 1.1 * cm, f"Halaman {doc.page}")
    c.restoreState()


def cover():
    s = []
    s.append(Spacer(1, 2.2 * cm))
    s.append(P("EmisiSense Vision 2.0", ParagraphStyle("c0", fontName="S", fontSize=12, textColor=ACC, spaceAfter=6)))
    s.append(P("Panduan menentukan garis hitung, zona pengamatan, dan kalibrasi kecepatan",
               ParagraphStyle("c1", fontName="SB", fontSize=26, leading=33, textColor=INK, spaceAfter=14)))
    s.append(P("Langkah demi langkah, dari memasang kamera sampai memastikan angka kecepatan dapat dipercaya.",
               ParagraphStyle("c2", fontName="S", fontSize=12.5, leading=19, textColor=MUTED, spaceAfter=30)))
    s.append(Image(str(IMG / "a_awal.png"), width=W * 0.7, height=W * 0.7 * 1143 / 1224))
    s.append(P("Tangkapan layar memakai mode demo (simulasi lalu lintas). Tampilan di kamera nyata akan berbeda, langkahnya sama.", small))
    s.append(Spacer(1, 0.8 * cm))
    s.append(P("Disusun untuk penelitian PDU 2026, Universitas Brawijaya<br/>LAB AQHI dan EK Instrumentation  ·  18 November 2026", small))
    s.append(PageBreak())
    return s


def build(out):
    doc = BaseDocTemplate(str(out), pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm, topMargin=2 * cm, bottomMargin=1.8 * cm,
                          title="Panduan garis, zona, dan kalibrasi kecepatan - EmisiSense Vision", author="LAB AQHI dan EK Instrumentation")
    doc.addPageTemplates([PageTemplate(id="p", frames=[Frame(2 * cm, 1.8 * cm, W, A4[1] - 3.8 * cm, id="f", leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)], onPage=deco)])
    s = cover()

    # ---------------- 1
    s += [P("1. Gambaran alur", h1),
          P("Agar jumlah kendaraan dan kecepatan yang tampil di dasbor bisa dipertanggungjawabkan, ada lima hal yang dilakukan berurutan. "
            "Bagian 1 dan 2 menentukan <b>apa yang dihitung</b> (zona dan garis); bagian 3 menentukan <b>seberapa cepat</b> (kalibrasi); "
            "bagian 4 membuktikan angkanya benar."), flow(), Spacer(1, 8),
          tbl([["Langkah", "Fungsinya", "Mempengaruhi"],
               ["1. Sumber tersambung", "Memastikan video lancar dan sudut kamera tetap", "Semua hasil"],
               ["2. Zona pengamatan", "Membatasi area pencarian dan area penghitung kepadatan", "Deteksi, kepadatan"],
               ["3. Garis hitung", "Penanda tempat kendaraan dihitung, per arah", "Jumlah kendaraan, arah"],
               ["4. Kalibrasi kecepatan", "Mengubah piksel di layar menjadi meter di jalan", "Kecepatan, jumlah pelanggar batas"],
               ["5. Validasi dan catat", "Membandingkan dengan kecepatan sebenarnya, lalu mencatat hasilnya", "Kepercayaan data"]],
              [4.1 * cm, 8.6 * cm, W - 12.7 * cm]), Spacer(1, 8)]
    s.append(box("Yang perlu diketahui sejak awal",
                 ["Kecepatan dari video selalu <b>perkiraan</b>. Kalibrasi menekan galatnya, tetapi tidak meniadakannya. Karena itu langkah 5 (validasi) wajib bila angka kecepatan akan dilaporkan.",
                  "Jumlah kendaraan <b>tidak bergantung pada kalibrasi</b>. Bila Anda hanya butuh hitungan, cukup langkah 1 sampai 3."], "warn"))
    s += [P("Yang perlu disiapkan", h2)] + bullets([
        "Akses ke dasbor (alamat IP yang tampil di footer, misalnya <font name='M'>http://192.168.1.20:5000</font>) dari laptop atau ponsel.",
        "<b>Satu panjang acuan yang benar-benar diukur</b> di jalan: meteran gulung 20 sampai 50 m, atau jarak dari peta/gambar teknis bila jalan tidak bisa dijangkau.",
        "Untuk validasi: stopwatch atau ponsel dengan aplikasi GPS speedometer, dan satu kendaraan uji (opsional bila memakai video rekaman).",
        "Lembar catatan di Lampiran B dan C (boleh dicetak)."])
    s.append(CondPageBreak(10 * cm))

    # ---------------- 2
    s += [P("2. Langkah 1: pastikan sumber siap", h1),
          P("Kalibrasi hanya berlaku untuk satu posisi kamera dan satu ukuran gambar. Pastikan kedua hal itu sudah mantap <b>sebelum</b> mengatur apa pun."),
          ] + steps([
        "Buka menu <b>Sumber &amp; lokasi</b>, tempel alamat video, tekan <b>Tes koneksi</b>, lalu <b>Terapkan sumber</b>. Catat hasil tes: jenis aliran, resolusi, dan frame per detik.",
        "Buka menu <b>Pemantauan</b>. Pastikan lencana di kanan atas berwarna hijau (Langsung) dan video bergerak.",
        "Periksa <b>frame per detik</b> sumber. Di bawah 3 fps, kecepatan kurang teliti karena posisi kendaraan hanya diketahui sedikit kali per detik. Hasil tetap bisa dipakai tetapi galatnya lebih besar.",
        "Buka menu <b>Deteksi</b> dan tentukan <b>Lebar frame proses</b> (bawaan 800 piksel). <b>Jangan ubah lagi</b> setelah kalibrasi."])
    s.append(box("Dua hal yang membatalkan kalibrasi",
                 ["<b>Kamera bergeser atau berputar.</b> Kamera PTZ yang berpindah preset, tiang yang bergoyang, atau kamera yang diputar petugas mengubah skala. Kalibrasi ulang setiap posisi kamera berubah.",
                  "<b>Lebar frame proses diubah.</b> Skala disimpan dalam meter per piksel pada ukuran frame saat kalibrasi. Bila lebar frame diganti (misalnya 800 menjadi 640), kalibrasi lama menjadi salah. Ulangi kalibrasi."], "bad"))

    # ---------------- 3 zona
    s += [P("3. Langkah 2: zona pengamatan", h1),
          P("Zona adalah poligon di atas jalan. Di dalam zona itulah kepadatan dihitung dan pencarian kendaraan difokuskan, sehingga kendaraan di trotoar, parkiran, atau pantulan kaca tidak ikut terdeteksi."),
          fig("c_zona.png", "Gambar 1. Mengatur zona. (1)–(4) titik sudut yang bisa diseret; (5) tombol Selesai.")]
    s += steps([
        "Di bawah video, tekan <b>Atur zona</b>. Tombol menjadi gelap dan titik biru muncul di sudut zona. Petunjuk pengaturan tampil di panel di bawah video.",
        "<b>Seret</b> tiap titik biru ke tepi badan jalan. Zona boleh tidak persegi: tarik titik atas ke arah jalan yang menyempit di kejauhan.",
        "Tekan <b>Selesai</b> (atau tombol Esc). Perubahan tersimpan otomatis. <b>Kembalikan bawaan</b> bila ingin mengulang."])
    s += [P("Aturan praktis", h3)] + bullets([
        "Tutup <b>badan jalan saja</b>. Sisakan sedikit margin agar kendaraan di tepi tetap masuk.",
        "Jangan sertakan langit, gedung, dan bahu jalan dengan banyak pejalan kaki.",
        "Bagian atas zona jangan terlalu jauh. Kendaraan yang hanya tampak beberapa piksel sulit dikenali dan menghasilkan kecepatan acak. Hentikan zona sebelum kendaraan tampak terlalu kecil (kira-kira di bawah 12 piksel).",
        "Zona terlalu kecil membuat kendaraan hilang saat melintasi tepinya. Buat sedikit lebih lebar dari lajur yang dihitung."])
    s.append(CondPageBreak(10 * cm))

    # ---------------- 4 garis
    s += [P("4. Langkah 3: garis hitung", h1),
          P("Kendaraan dihitung <b>satu kali</b> saat titik dekat bagian bawah kendaraan melewati garis. Arah lewatnya menentukan masuk ke baris arah yang mana (misalnya Mendekat atau Menjauh)."),
          fig("b_garis.png", "Gambar 2. Mengatur garis. (1) dan (2) ujung garis; (3) pilih garis; (4) tukar arah; (5) Selesai. Panah kuning di video menunjukkan arah pertama.")]
    s += steps([
        "Tekan <b>Atur garis</b>. Garis kuning dengan dua titik di ujungnya muncul.",
        "<b>Seret kedua titik ujung</b> hingga garis melintang di jalan, tegak lurus arah kendaraan, dari tepi jalan sisi kiri ke tepi sisi kanan.",
        "Periksa <b>panah arah</b>. Tulisan di sebelah panah (misalnya “→ Mendekat”) adalah arah pertama. Bila terbalik dengan yang Anda inginkan, tekan <b>Tukar arah</b>.",
        "Ubah kolom <b>nama garis</b> serta <b>nama arah 1 dan 2</b> menjadi istilah lapangan (misalnya “Simpang Kayutangan”, “Ke utara”, “Ke selatan”). Nama tampil di tabel dan ekspor data.",
        "Tambahkan garis lain dengan <b>Tambah garis</b> bila perlu menghitung di dua penampang (misalnya sebelum dan sesudah simpang). Pilih garis dari daftar untuk mengubahnya. <b>Hapus garis ini</b> menghapus yang dipilih.",
        "Tekan <b>Selesai</b>."])
    s += [P("Di mana garis sebaiknya ditaruh", h3), tbl([
        ["Lakukan", "Hindari"],
        ["Di bagian tengah gambar, saat kendaraan tampak cukup besar dan utuh.", "Terlalu dekat tepi atas (kendaraan kecil) atau tepi bawah (kendaraan terpotong)."],
        ["Garis membentang <b>seluruh lebar jalan</b>, ujungnya sedikit melewati tepi aspal.", "Garis pendek yang hanya menutup satu lajur, kecuali memang hanya satu lajur yang dihitung."],
        ["Di ruas yang kendaraannya <b>bergerak lancar</b>.", "Tepat di lampu merah atau antrean. Kendaraan yang berhenti di garis bisa terhitung tidak tepat."],
        ["Tegak lurus arah gerak kendaraan.", "Garis miring: kendaraan bisa menyentuh garis dari samping."],
        ["Jauh dari pohon, tiang, atau papan yang menutupi kendaraan.", "Tempat yang sering terhalang bus atau truk."]],
        [W / 2, W / 2])]
    s.append(Spacer(1, 8))
    s.append(box("Bila garis kurang tepat, hitungan tetap masuk",
                 "Kendaraan yang jelas bergerak tetapi tidak melewati garis manapun tetap dihitung di baris <b>Di luar garis</b>. Bila baris itu terisi banyak, garis Anda belum menutup jalur kendaraan: periksa letaknya. "
                 "Kecepatan dan kalibrasi tidak terpengaruh oleh letak garis.", "tip"))
    s.append(CondPageBreak(10 * cm))

    # ---------------- 5 kalibrasi
    s += [P("5. Langkah 4: kalibrasi kecepatan", h1),
          P("Video hanya tahu jarak dalam <b>piksel</b>. Kalibrasi memberi tahu aplikasi berapa meter di jalan yang sama dengan satu piksel di layar (skala, m/piksel). Kecepatan dihitung dari perpindahan kendaraan dalam beberapa detik terakhir:"),
          P("kecepatan (km/jam) = jarak (piksel) × skala (m/piksel) ÷ waktu (detik) × 3,6", code)]
    s += [P("Contoh hitungan", h3),
          P("Anda mengukur marka jalan sepanjang <b>12 m</b> dan di layar panjangnya <b>240 piksel</b>. Skalanya 12 ÷ 240 = <b>0,05 m/piksel</b> (5 cm per piksel). "
            "Sebuah mobil bergeser 200 piksel dalam 1,5 detik: 200 × 0,05 ÷ 1,5 = 6,67 m/detik, atau 6,67 × 3,6 = <b>24 km/jam</b>.")]
    s += [P("5.1 Memilih panjang acuan", h2),
          P("Panjang acuan adalah dua titik di <b>permukaan jalan</b> yang jaraknya Anda ketahui pasti. Makin baik acuannya, makin baik kecepatannya."),
          tbl([["Acuan", "Cocok?", "Catatan"],
               ["Marka putus-putus: ujung garis pertama sampai ujung garis ke-3 atau ke-4", "<b>Terbaik</b>", "Sejajar arah kendaraan dan di bidang jalan. Ukur dengan meteran; jangan hanya mengandalkan angka standar karena panjangnya berbeda per jalan."],
               ["Dua patok, tiang, atau tanda yang Anda pasang dan ukur (kapur, cone)", "<b>Terbaik</b>", "Pasang di tepi jalan sejajar arah kendaraan; ukur dengan meteran. Perlu izin dan keselamatan, lihat 5.2."],
               ["Jarak dari peta satelit atau gambar teknis (bila CCTV tidak bisa dijangkau)", "Cukup", "Ukur antara dua objek yang jelas di peta dan di video (ujung zebra cross, tepi persimpangan). Perhatikan, ketelitian peta ikut menjadi galat."],
               ["Lebar lajur atau zebra cross yang melintang", "Kurang", "Arah melintang berskala beda dari arah memanjang pada kamera yang menyerong. Hindari bila bisa."],
               ["Panjang kendaraan (misalnya mobil 4 m)", "Jangan", "Ukurannya beragam dan titik ujungnya tidak jelas."]],
              [6.2 * cm, 2.0 * cm, W - 8.2 * cm]), Spacer(1, 8)]
    s += [P("5.2 Mengukur di lapangan dengan aman", h2)] + bullets([
        "Ukur saat jalan <b>sepi</b> atau minta tutup sementara; pakai rompi, cone, dan satu orang pengawas.",
        "Bila ingin menandai titik, pakai kapur atau stiker pada tepi jalan, bukan benda yang menghalangi kendaraan.",
        "Ukur <b>dua kali</b> dan ambil rata-ratanya. Catat panjangnya ke 0,01 m di Lampiran B.",
        "Panjang acuan sebaiknya <b>10 m atau lebih</b> (lihat 5.4). Untuk jalan yang tidak mungkin diukur langsung, pakai peta."])
    s.append(CondPageBreak(10 * cm))

    s += [P("5.3 Mengisi kalibrasi di dasbor", h2),
          fig("d_kalibrasi.png", "Gambar 3. Kalibrasi. (1) dan (2) dua titik acuan di jalan; (3) panjang nyata dalam meter; (4) Terapkan."),
          ] + steps([
        "Pada <b>Pemantauan</b>, tekan <b>Kalibrasi</b> di bawah video.",
        "Klik <b>titik pertama</b> pada ujung acuan, tepat di permukaan jalan. Perbesar layar (tombol Layar penuh) agar klik lebih teliti.",
        "Klik <b>titik kedua</b> pada ujung acuan yang lain. Garis kuning menghubungkan keduanya. Bila salah klik, klik lagi: titik pertama dan kedua diulang dari awal.",
        "Isi <b>panjang nyata</b> antara kedua titik dalam meter (misalnya 12), lalu tekan <b>Terapkan</b>.",
        "Buka menu <b>Deteksi</b> dan lihat kartu <b>Kalibrasi kecepatan</b>. Status menjadi <b>aktif</b> dan menampilkan skala serta acuan yang dipakai."])
    s.append(fig("e_deteksi.png", "Gambar 4. Kartu kalibrasi di menu Deteksi. Pada contoh demo: 6,0 m = 307 piksel, skala 1,95 cm per piksel.", width=W * 0.7))
    s.append(P("<b>Hapus kalibrasi</b> mengembalikan skala otomatis dari ukuran khas tiap jenis kendaraan (mobil 3 m, motor 1,5 m, dan seterusnya). Cara itu kasar dan hanya cocok untuk gambaran awal.", body))
    s.append(CondPageBreak(10 * cm))

    s += [P("5.4 Ketelitian yang bisa diharapkan", h2),
          P("Beberapa hal membatasi ketelitian. Pahami agar tidak menyimpulkan lebih dari yang bisa didukung data."),
          tbl([["Sumber galat", "Besarnya", "Cara menekan"],
               ["Klik titik acuan meleset", "Galat relatif ≈ meleset ÷ panjang acuan dalam piksel. Meleset 3 piksel pada acuan 300 piksel ≈ 1%; pada acuan 60 piksel ≈ 5%.", "Pilih acuan panjang; klik di layar penuh."],
               ["Perspektif kamera", "Skala berbeda di dekat dan jauh dari kamera, terutama pada kamera yang rendah atau menyerong.", "Kalibrasi di kedalaman tempat kendaraan melewati garis hitung (lihat Gambar 5)."],
               ["Frame rate rendah", "Posisi kendaraan hanya diketahui sedikit kali per detik; kecepatan berfluktuasi.", "Pakai sumber di atas 3 fps bila ada."],
               ["Kotak deteksi bergetar", "Kotak membesar atau mengecil antar frame sehingga titik pelacak bergeser.", "Kecepatan dihaluskan; lihat rata-rata banyak kendaraan, bukan satu kendaraan."],
               ["Panjang acuan salah ukur", "Langsung menjadi galat sistematis pada semua kecepatan.", "Ukur dua kali; verifikasi di langkah 5."]],
              [4.0 * cm, 7.6 * cm, W - 11.6 * cm]), Spacer(1, 8),
          perspective(), P("Gambar 5. Panjang nyata yang sama tampak berbeda panjangnya di layar menurut jaraknya dari kamera.", cap)]
    s.append(box("Cara memilih tempat kalibrasi",
                 ["Pilih acuan di sekitar <b>garis hitung</b> dan di jalur yang dilalui kebanyakan kendaraan. Kecepatan paling teliti di kedalaman itu, dan makin menyimpang bila kendaraan jauh lebih dekat atau lebih jauh dari kamera.",
                  "Aplikasi memakai <b>satu skala</b> untuk seluruh gambar. Jangan menyimpulkan kecepatan yang tinggi akurasinya di bagian gambar yang sangat jauh."], "tip"))
    s.append(CondPageBreak(10 * cm))

    # ---------------- 6 validasi
    s += [P("6. Langkah 5: validasi dan pencatatan", h1),
          P("Kalibrasi baru boleh dipercaya setelah dibandingkan dengan kecepatan yang sebenarnya. Pilih salah satu cara; cara A paling meyakinkan, cara B tidak butuh kendaraan uji."),
          P("Cara A: kendaraan uji dengan kecepatan diketahui", h2)] + steps([
        "Siapkan satu kendaraan dan satu ponsel dengan aplikasi GPS speedometer (atau speedometer kendaraan yang sudah diperiksa).",
        "Lintaskan kendaraan di jalur yang dipantau pada kecepatan <b>konstan</b>, misalnya 20, 30, dan 40 km/jam. Ulangi <b>3 kali</b> tiap kecepatan.",
        "Setiap lintasan, catat kecepatan acuan dan kecepatan yang tampil pada label kendaraan (atau tabel Kendaraan terlacak).",
        "Hitung galat tiap lintasan: <font name='M'>galat % = (terbaca − acuan) ÷ acuan × 100</font>. Catat di Lampiran C."])
    s += [P("Cara B: dua tanda dan stopwatch pada video", h2)] + steps([
        "Pilih dua tanda di jalan yang jaraknya <b>D</b> meter sudah Anda ukur (bukan acuan kalibrasi yang sama, agar uji ini bebas).",
        "Putar ulang video (atau gunakan rekaman), catat waktu <b>t</b> detik kendaraan menempuh kedua tanda itu. Putar ulang dan pakai pemutar yang menampilkan waktu per frame untuk ketelitian.",
        "Kecepatan acuan = D ÷ t × 3,6 km/jam. Bandingkan dengan yang ditampilkan aplikasi untuk kendaraan yang sama. Contoh: D = 20 m, t = 2,4 detik → 30 km/jam."])
    s += [P("Menilai hasil", h2),
          tbl([["Hasil uji", "Arti", "Tindakan"],
               ["Rata-rata |galat| ≤ 10%", "Layak untuk gambaran kecepatan rata-rata dan sebaran. (Batas ini saran praktis, bukan standar; tentukan sesuai kebutuhan penelitian.)", "Catat hasil di Lampiran C."],
               ["Galat searah (selalu lebih tinggi atau selalu lebih rendah)", "Ada galat sistematis: biasanya panjang acuan salah atau titik acuan tidak di bidang jalan.", "Ulangi kalibrasi dengan acuan lebih panjang. Atau koreksi: panjang baru = panjang lama ÷ k, dengan k = kecepatan terbaca ÷ acuan."],
               ["Galat acak (kadang tinggi, kadang rendah)", "Biasanya frame rate rendah atau kotak deteksi bergetar.", "Gunakan rata-rata banyak kendaraan; naikkan presisi di menu Deteksi."],
               ["Galat membesar saat kendaraan jauh atau dekat", "Efek perspektif.", "Batasi analisis pada kedalaman tempat kalibrasi (sekitar garis hitung)."]],
              [4.2 * cm, 7.3 * cm, W - 11.5 * cm]), Spacer(1, 8)]
    s.append(box("Menyimpan hasil kalibrasi",
                 ["Kalibrasi tersimpan di <font name='M'>config.json</font> dan terbawa saat pembaruan. Salin berkas itu sebagai cadangan, misalnya <font name='M'>cp config.json config-kalibrasi-2026-11-18.json</font>.",
                  "Catat tanggal, posisi kamera, lebar frame proses, panjang acuan, dan hasil uji di Lampiran B. Dengan catatan itu orang lain dapat mengulang atau menilai kalibrasi."], "tip"))
    s.append(CondPageBreak(10 * cm))

    # ---------------- 7 masalah
    s += [P("7. Bila ada masalah", h1),
          tbl([["Gejala", "Penyebab umum", "Yang dilakukan"],
               ["Kecepatan selalu “–”", "Kendaraan belum terlacak cukup lama (butuh sekitar 0,35 detik), atau kendaraan diam, atau frame rate sangat rendah.", "Tunggu kendaraan bergerak melewati zona; periksa fps sumber di menu Sistem."],
               ["Semua kecepatan terlalu tinggi", "Panjang acuan terlalu panjang, atau titik acuan tidak di bidang jalan (misalnya di atap kendaraan).", "Ukur ulang; kalibrasi ulang dengan titik di permukaan jalan."],
               ["Semua kecepatan terlalu rendah", "Panjang acuan terlalu pendek, atau skala acuan di dekat kamera dipakai untuk kendaraan jauh.", "Ukur ulang; kalibrasi di sekitar garis hitung."],
               ["Kecepatan berubah-ubah drastis", "Frame rate rendah, kotak deteksi bergetar, atau kendaraan terhalang.", "Naikkan presisi; pakai rata-rata banyak kendaraan."],
               ["Kalibrasi hilang atau tidak cocok setelah mengubah pengaturan", "Lebar frame proses atau sumber diganti, atau kamera bergeser.", "Ulangi kalibrasi (Bagian 5.3)."],
               ["Banyak kendaraan masuk “Di luar garis”", "Garis tidak menutup jalur kendaraan atau salah tempat.", "Atur ulang garis (Bagian 4)."],
               ["Satu kendaraan terhitung dua kali", "Garis di tempat kendaraan berhenti atau antre.", "Pindahkan garis ke ruas lancar."],
               ["Kendaraan tidak terhitung", "Zona terlalu sempit, ambang keyakinan terlalu tinggi, atau kendaraan terlalu kecil di layar.", "Lebarkan zona; turunkan ambang di menu Deteksi; nyalakan “Deteksi mentah” di bawah video untuk melihat apa yang ditemukan."]],
              [4.2 * cm, 6.6 * cm, W - 10.8 * cm])]
    s.append(CondPageBreak(10 * cm))

    # ---------------- lampiran A
    s += [P("Lampiran A. Daftar periksa ringkas", h1)]
    chk = [["", "Langkah", "Selesai"],
           ["Sumber", "Tes koneksi berhasil; fps dan resolusi dicatat; lencana hijau.", "☐"],
           ["Sumber", "Lebar frame proses ditetapkan dan tidak diubah lagi.", "☐"],
           ["Zona", "Titik biru menutup badan jalan saja, tidak sampai kendaraan yang terlalu kecil.", "☐"],
           ["Garis", "Garis melintang seluruh lebar jalan di ruas lancar, bagian tengah gambar.", "☐"],
           ["Garis", "Nama garis dan nama arah sesuai istilah lapangan; panah arah benar.", "☐"],
           ["Kalibrasi", "Panjang acuan diukur dua kali (≥ 10 m bila mungkin), titik di permukaan jalan.", "☐"],
           ["Kalibrasi", "Terapkan; kartu di menu Deteksi menunjukkan status aktif dan skala masuk akal.", "☐"],
           ["Validasi", "Cara A atau B dilakukan; galat dihitung dan dicatat di Lampiran C.", "☐"],
           ["Arsip", "config.json dicadangkan; Lampiran B diisi.", "☐"]]
    t = tbl(chk, [2.4 * cm, W - 4.4 * cm, 2.0 * cm]); s += [t]
    s += [Spacer(1, 12), P("Rumus yang dipakai", h2),
          P("skala (m/piksel) = panjang nyata (m) ÷ panjang di layar (piksel)<br/>"
            "kecepatan (km/jam) = jarak (piksel) × skala ÷ waktu (detik) × 3,6<br/>"
            "galat (%) = (terbaca − acuan) ÷ acuan × 100<br/>"
            "faktor koreksi k = kecepatan terbaca ÷ kecepatan acuan; panjang baru = panjang lama ÷ k", code)]
    s.append(CondPageBreak(10 * cm))

    # ---------------- lampiran B, C
    blank = lambda n: [[""] * n]
    s += [P("Lampiran B. Lembar catatan kalibrasi", h1)]
    fields = [["Lokasi / nama kamera", ""], ["Tanggal dan petugas", ""], ["Sumber video (alamat)", ""], ["Resolusi sumber dan fps (dari Tes koneksi)", ""],
              ["Lebar frame proses (menu Deteksi)", ""], ["Titik acuan 1 (deskripsi, misalnya “ujung marka #1”)", ""], ["Titik acuan 2", ""],
              ["Panjang nyata terukur (m), ukur 1 / ukur 2 / rata-rata", ""], ["Panjang di layar (piksel) / skala (m/piksel) dari kartu Deteksi", ""],
              ["Letak garis hitung (uraian)", ""], ["Catatan lain (cuaca, gangguan kamera)", ""]]
    ft = Table([[Paragraph(a, cell), ""] for a, _ in fields], colWidths=[7.4 * cm, W - 7.4 * cm], rowHeights=[1.05 * cm] * len(fields))
    ft.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, LINE), ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f4f7fa")), ("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
    s += [ft, Spacer(1, 22), P("Lampiran C. Lembar uji validasi", h1),
          P("Isi satu baris per lintasan. Galat % = (terbaca − acuan) ÷ acuan × 100. Hitung rata-rata |galat| di baris terakhir.", small)]
    rows = [["No", "Jenis", "Acuan (km/jam)", "Terbaca (km/jam)", "Galat (%)"]] + [[str(i), "", "", "", ""] for i in range(1, 11)] + [["", "Rata-rata |galat|", "", "", ""]]
    vt = Table([[Paragraph(c, cellb if r == 0 else cell) for c in row] for r, row in enumerate(rows)],
               colWidths=[1.2 * cm, 4.3 * cm, 3.7 * cm, 3.9 * cm, W - 13.1 * cm], rowHeights=[0.85 * cm] + [0.78 * cm] * 11)
    vt.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, LINE), ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eaf0f7")), ("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
    s += [vt, Spacer(1, 10), P("Hasil: ☐ layak (rata-rata |galat| ≤ 10%)   ☐ perlu kalibrasi ulang   Tanda tangan: ____________________", small)]
    doc.build(s)


if __name__ == "__main__":
    out = HERE / "panduan-kalibrasi.pdf"
    build(out)
    print(out)
