#!/usr/bin/env bash
# Memperbarui EmisiSense Vision dari GitHub. Data (data/) dan pengaturan (config.json) tidak disentuh.
# Pakai: ./update.sh        (cek, tarik, pasang dependensi, mulai ulang layanan bila ada)
set -e
cd "$(dirname "$0")"
[ -d .git ] || { echo "Folder ini bukan hasil git clone. Pasang ulang dengan install.sh."; exit 1; }
git diff --quiet -- . ':!data' ':!config.json' || { echo "Ada perubahan lokal pada kode. Simpan dulu (git stash) lalu ulangi."; exit 1; }
hotspot_hint() {   # panel Wi-Fi di halaman Sistem hanya aktif bila pengatur jaringan terpasang
  if [ -f hotspot/install-hotspot.sh ] && [ ! -x /usr/local/bin/emisisense-net ]; then
    echo; echo "Pengatur Wi-Fi/hotspot belum terpasang, jadi pengaturan Wi-Fi belum muncul di halaman Sistem."
    echo "Pasang sekali dengan:  sudo ./hotspot/install-hotspot.sh"
  elif [ -x /usr/local/bin/emisisense-net ] && ! cmp -s hotspot/emisisense-net /usr/local/bin/emisisense-net; then
    echo; echo "Pengatur Wi-Fi/hotspot di sistem versi lama. Perbarui dengan:  sudo ./hotspot/install-hotspot.sh --no-start"
  fi
}
OLD=$(git rev-parse HEAD)
git fetch --quiet origin main
if [ "$OLD" = "$(git rev-parse origin/main)" ]; then echo "Sudah versi terbaru ($(git rev-parse --short HEAD))."; hotspot_hint; exit 0; fi
echo "Perubahan yang akan dipasang:"; git log --pretty='  %h %s' "$OLD"..origin/main
git pull --ff-only --quiet origin main
if ! git diff --quiet "$OLD" HEAD -- requirements.txt; then
  echo "requirements.txt berubah, memasang dependensi..."
  .venv/bin/python -m pip install --quiet -r requirements.txt
fi
if command -v systemctl >/dev/null 2>&1 && systemctl is-active --quiet emisisense 2>/dev/null; then
  echo "Memulai ulang layanan emisisense..."; sudo systemctl restart emisisense
else
  echo "Selesai. Jika aplikasi sedang berjalan, mulai ulang (atau pakai tombol Perbarui di halaman Sistem)."
fi
echo "Versi sekarang: $(git rev-parse --short HEAD)"
hotspot_hint
