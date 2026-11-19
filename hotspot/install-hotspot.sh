#!/usr/bin/env bash
# EmisiSense Vision - pemasang hotspot Orange Pi.
# Orange Pi memancarkan hotspot sendiri (bawaan), lalu dari aplikasi/web Anda bisa memilih
# tetap memakai hotspot atau menyambungkannya ke Wi-Fi lain.
#
#   cd ~/emisisense-vision && sudo ./hotspot/install-hotspot.sh
#   sudo ./hotspot/install-hotspot.sh --ssid LabAQHI --password rahasia123
#
# Opsi: --ssid NAMA  --password KATA(8-63)  --user PENGGUNA(layanan web)  --no-start  --force
set -euo pipefail

SSID=""; PASS=""; RUNUSER="${SUDO_USER:-$(id -un)}"; START=1; FORCE=0
while [ $# -gt 0 ]; do
  case "$1" in
    --ssid) SSID="$2"; shift 2;;
    --password) PASS="$2"; shift 2;;
    --user) RUNUSER="$2"; shift 2;;
    --no-start) START=0; shift;;
    --force) FORCE=1; shift;;
    -h|--help) sed -n 2,10p "$0"; exit 0;;
    *) echo "Opsi tidak dikenal: $1"; exit 1;;
  esac
done

say()  { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m!! %s\033[0m\n' "$*"; }
die()  { printf '\033[1;31mXX %s\033[0m\n' "$*"; exit 1; }
[ "$(id -u)" -eq 0 ] || die "Jalankan dengan sudo:  sudo $0"
[ -z "$PASS" ] || { [ ${#PASS} -ge 8 ] && [ ${#PASS} -le 63 ] || die "Kata sandi hotspot harus 8-63 karakter."; }
id "$RUNUSER" >/dev/null 2>&1 || die "Pengguna '$RUNUSER' tidak ada (pakai --user)."

HERE="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd || echo /nonexistent)"
RAW="https://raw.githubusercontent.com/efendiyhy/computer-vision/main/hotspot"

say "Memeriksa NetworkManager"
if ! command -v nmcli >/dev/null 2>&1; then
  command -v apt-get >/dev/null 2>&1 || die "NetworkManager tidak ada dan apt tidak tersedia."
  warn "NetworkManager belum terpasang; memasang (ini dapat memutus jaringan yang sedang dipakai)."
  [ "$FORCE" -eq 1 ] || die "Pasang manual 'sudo apt install network-manager' dari konsol langsung/kabel, atau ulangi dengan --force."
  apt-get update -y && apt-get install -y network-manager
fi
systemctl is-active --quiet NetworkManager || { systemctl enable --now NetworkManager || die "NetworkManager tidak bisa dijalankan."; }
nmcli -t -f TYPE dev | grep -qx wifi || die "Tidak ada perangkat Wi-Fi. Periksa adaptor/driver Wi-Fi Orange Pi (nmcli dev)."
command -v python3 >/dev/null 2>&1 || apt-get install -y python3
command -v rfkill >/dev/null 2>&1 || apt-get install -y rfkill >/dev/null 2>&1 || true

say "Memasang pengatur jaringan"
if [ -f "$HERE/emisisense-net" ]; then
  install -m 0755 -o root -g root "$HERE/emisisense-net" /usr/local/bin/emisisense-net
else
  curl -fsSL "$RAW/emisisense-net" -o /usr/local/bin/emisisense-net && chmod 0755 /usr/local/bin/emisisense-net
fi
mkdir -p /etc/emisisense
if [ -n "$SSID" ] || [ -n "$PASS" ] || [ ! -f /etc/emisisense/net.json ]; then
  python3 - "$SSID" "$PASS" <<'PYEOF'
import json, os, sys
p = "/etc/emisisense/net.json"
try: c = json.load(open(p))
except Exception: c = {}
c.setdefault("mode", "hotspot")
if sys.argv[1]: c["ssid"] = sys.argv[1]
if sys.argv[2]: c["password"] = sys.argv[2]
json.dump(c, open(p, "w"), indent=1); os.chmod(p, 0o600)
PYEOF
fi

say "Mengizinkan layanan web memakai pengatur jaringan"
SUDOERS=/etc/sudoers.d/emisisense-net
echo "$RUNUSER ALL=(root) NOPASSWD: /usr/local/bin/emisisense-net" > "$SUDOERS.tmp"
chmod 0440 "$SUDOERS.tmp"
visudo -cf "$SUDOERS.tmp" >/dev/null || { rm -f "$SUDOERS.tmp"; die "Berkas sudoers tidak valid."; }
mv "$SUDOERS.tmp" "$SUDOERS"

say "Memasang layanan boot (emisisense-net)"
cat > /etc/systemd/system/emisisense-net.service <<'UNIT'
[Unit]
Description=EmisiSense hotspot / Wi-Fi saat boot
After=NetworkManager.service
Wants=NetworkManager.service
Before=emisisense-vision.service

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/local/bin/emisisense-net boot
TimeoutStartSec=300

[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable emisisense-net.service >/dev/null

# jam: zona waktu WIB (GMT+7)
command -v timedatectl >/dev/null 2>&1 && timedatectl set-timezone Asia/Jakarta 2>/dev/null || true

CFGSSID=$(python3 -c "import json;print(json.load(open('/etc/emisisense/net.json')).get('ssid') or '')")
[ -n "$CFGSSID" ] || CFGSSID="EmisiSense-xxxx (nama dibuat otomatis dari MAC)"
CFGPASS=$(python3 -c "import json;print(json.load(open('/etc/emisisense/net.json')).get('password'))")

if [ "$START" -eq 1 ]; then
  say "Menyalakan hotspot dalam 10 detik"
  warn "Bila Anda sedang SSH lewat Wi-Fi, sesi akan terputus. Sambungkan ponsel/laptop ke hotspot di bawah lalu SSH ke 10.42.0.1."
  nohup bash -c 'sleep 10; /usr/local/bin/emisisense-net hotspot </dev/null >/dev/null 2>&1' >/dev/null 2>&1 &
fi

cat <<EOT

 Selesai.
   Hotspot      : $CFGSSID
   Kata sandi   : $CFGPASS
   Alamat web   : http://10.42.0.1:5000   (setelah tersambung ke hotspot)
   SSH          : ssh $RUNUSER@10.42.0.1
   Pilih Wi-Fi  : buka web -> Sistem -> Jaringan (atau: echo '{"ssid":"NAMA","password":"SANDI"}' | sudo emisisense-net connect)
   Kembali ke hotspot : web -> Sistem -> Jaringan -> Gunakan hotspot  (atau: sudo emisisense-net hotspot)
EOT
