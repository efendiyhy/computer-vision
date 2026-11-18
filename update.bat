@echo off
rem Memperbarui EmisiSense Vision dari GitHub. Data (data\) dan pengaturan (config.json) tidak disentuh.
cd /d "%~dp0"
if not exist ".git" (echo Folder ini bukan hasil git clone. Pasang ulang dengan install.ps1. & pause & exit /b 1)
for /f %%i in ('git rev-parse HEAD') do set OLD=%%i
git fetch --quiet origin main || (echo Gagal menghubungi GitHub. & pause & exit /b 1)
for /f %%i in ('git rev-parse origin/main') do set NEW=%%i
if "%OLD%"=="%NEW%" (echo Sudah versi terbaru. & pause & exit /b 0)
echo Perubahan yang akan dipasang:
git log --pretty="  %%h %%s" %OLD%..origin/main
git pull --ff-only --quiet origin main || (echo Pembaruan gagal. Ada perubahan lokal pada kode? & pause & exit /b 1)
git diff --quiet %OLD% HEAD -- requirements.txt || (echo Memasang dependensi... & ".venv\Scripts\python.exe" -m pip install --quiet -r requirements.txt)
echo Selesai. Tutup aplikasi yang berjalan lalu jalankan lagi run.bat.
pause
