#!/usr/bin/env bash
# EmisiSense Vision - pemasang Linux (clone dari git + lingkungan virtual sendiri).
#
#   curl -fsSL https://raw.githubusercontent.com/efendiyhy/computer-vision/main/install.sh | bash
#   curl -fsSL .../install.sh | bash -s -- --service        # + jalan otomatis saat boot (systemd)
#
# Opsi : --dir PATH (bawaan ~/emisisense-vision)  --port N (bawaan 5000)  --service  --password KATA  --no-start
# Env  : EMISISENSE_REPO (URL git)  EMISISENSE_DIR
set -euo pipefail

REPO="${EMISISENSE_REPO:-https://github.com/efendiyhy/computer-vision.git}"
DIR="${EMISISENSE_DIR:-$HOME/emisisense-vision}"
PORT=5000; SERVICE=0; PASSWORD=""; START=1

while [ $# -gt 0 ]; do
  case "$1" in
    --dir) DIR="$2"; shift 2;;
    --port) PORT="$2"; shift 2;;
    --service) SERVICE=1; shift;;
    --password) PASSWORD="$2"; shift 2;;
    --no-start) START=0; shift;;
    -h|--help) sed -n 2,10p "$0"; exit 0;;
    *) echo "Opsi tidak dikenal: $1"; exit 1;;
  esac
done

say()  { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m!! %s\033[0m\n' "$*"; }
die()  { printf '\033[1;31mXX %s\033[0m\n' "$*"; exit 1; }
SUDO=""; [ "$(id -u)" -ne 0 ] && command -v sudo >/dev/null 2>&1 && SUDO="sudo"

# ---- 1. Python 3.10+ dan modul venv
say "Memeriksa Python"
PY=""
for c in python3.13 python3.12 python3.11 python3.10 python3; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info>=(3,10) else 1)' 2>/dev/null; then PY="$c"; break; fi
done
if [ -z "$PY" ] && command -v apt-get >/dev/null 2>&1; then
  warn "Python 3.10+ belum ada, memasang lewat apt"; $SUDO apt-get update -y && $SUDO apt-get install -y python3 python3-venv python3-pip git
  PY=python3
fi
[ -n "$PY" ] || die "Butuh Python 3.10 atau lebih baru. Pasang dulu, lalu jalankan ulang."
if ! "$PY" -c 'import venv, ensurepip' 2>/dev/null; then
  command -v apt-get >/dev/null 2>&1 || die "Modul venv Python tidak ada. Pasang paket python3-venv (atau setara)."
  warn "Memasang python3-venv"; $SUDO apt-get install -y python3-venv python3-pip
fi
echo "Python: $($PY --version)"

# ---- 2. Ambil kode dari git (atau perbarui)
say "Mengambil kode ke $DIR"
if [ -d "$DIR/.git" ]; then
  git -C "$DIR" pull --ff-only || warn "git pull gagal; memakai versi yang ada"
elif command -v git >/dev/null 2>&1; then
  git clone --depth 1 "$REPO" "$DIR"
else
  command -v curl >/dev/null 2>&1 || die "Butuh git atau curl."
  mkdir -p "$DIR"; curl -fsSL "${REPO%.git}/archive/refs/heads/main.tar.gz" | tar -xz --strip-components=1 -C "$DIR"
fi
cd "$DIR"

# ---- 3. Lingkungan virtual sendiri (.venv) + dependensi
say "Membuat lingkungan virtual (.venv) dan memasang dependensi (beberapa menit)"
[ -d .venv ] || "$PY" -m venv .venv
.venv/bin/python -m pip install --quiet --upgrade pip wheel
.venv/bin/python -m pip install --quiet -r requirements.txt
.venv/bin/python - <<'PYEOF'
import cv2, flask, scipy, numpy
from emisisense_vision.detector import SSDDetector
SSDDetector()
print("Uji pemuatan: OK (OpenCV", cv2.__version__ + ", model SSD termuat)")
PYEOF

# ---- 4. Layanan systemd (opsional) / peluncur
EXTRA=""; [ -n "$PASSWORD" ] && EXTRA=" --password $PASSWORD"
if [ "$SERVICE" -eq 1 ]; then
  command -v systemctl >/dev/null 2>&1 || die "systemd tidak tersedia; jalankan manual dengan ./run.sh"
  say "Memasang layanan systemd (emisisense-vision)"
  UNIT=/etc/systemd/system/emisisense-vision.service
  $SUDO tee "$UNIT" >/dev/null <<EOF
[Unit]
Description=EmisiSense Vision (LAB AQHI - EK Instrumentation)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$(id -un)
WorkingDirectory=$DIR
ExecStart=$DIR/.venv/bin/python $DIR/run.py --no-browser --port $PORT$EXTRA
Restart=always
RestartSec=5
KillSignal=SIGTERM
TimeoutStopSec=15

[Install]
WantedBy=multi-user.target
EOF
  $SUDO systemctl daemon-reload
  $SUDO systemctl enable --now emisisense-vision
  if command -v ufw >/dev/null 2>&1 && $SUDO ufw status 2>/dev/null | grep -q "Status: active"; then
    $SUDO ufw allow "$PORT"/tcp >/dev/null && echo "Firewall ufw: port $PORT dibuka"
  fi
  sleep 3
  $SUDO systemctl --no-pager --lines=0 status emisisense-vision | head -4 || true
fi

# ---- 5. Tampilkan alamat akses
say "Selesai. Alamat akses dari jaringan lokal:"
.venv/bin/python - "$PORT" <<'PYEOF'
import sys
from emisisense_vision import netinfo
for u in netinfo.urls(int(sys.argv[1])): print("   ", u)
PYEOF
cat <<EOF

 Folder       : $DIR
 Jalankan     : cd $DIR && ./run.sh            (atau .venv/bin/python run.py)
 Perbarui     : jalankan ulang perintah pemasang (data & pengaturan tidak terhapus)
 Data deteksi : $DIR/data/emisisense.db (SQLite)
EOF
[ "$SERVICE" -eq 1 ] && echo " Layanan      : sudo systemctl status|restart|stop emisisense-vision   |  log: journalctl -u emisisense-vision -f"

if [ "$SERVICE" -eq 0 ] && [ "$START" -eq 1 ] && [ -t 1 ]; then
  say "Menjalankan sekarang (Ctrl+C untuk berhenti)"
  exec .venv/bin/python run.py --no-browser --port "$PORT"$EXTRA
fi
