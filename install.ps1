# EmisiSense Vision - pemasang Windows (clone dari git + lingkungan virtual sendiri)
#
#   Satu baris (PowerShell):
#     irm https://raw.githubusercontent.com/efendiyhy/computer-vision/main/install.ps1 | iex
#   Dengan opsi:
#     & ([scriptblock]::Create((irm https://raw.githubusercontent.com/efendiyhy/computer-vision/main/install.ps1))) -Firewall -AutoStart
#   Atau unduh berkas ini lalu:
#     powershell -ExecutionPolicy Bypass -File install.ps1 [-Dir C:\EmisiSense] [-Port 5000] [-Firewall] [-AutoStart] [-Password kata] [-NoStart]
#
#   -Firewall  buka port di Windows Firewall agar bisa diakses dari jaringan lokal (butuh PowerShell "Run as administrator")
#   -AutoStart jalan otomatis saat login Windows (Task Scheduler)
param(
  [string]$Dir = "$env:USERPROFILE\EmisiSense-Vision",
  [int]$Port = 5000,
  [switch]$Firewall,
  [switch]$AutoStart,
  [string]$Password = "",
  [switch]$NoStart
)

$Repo = if ($env:EMISISENSE_REPO) { $env:EMISISENSE_REPO } else { 'https://github.com/efendiyhy/computer-vision.git' }
function Say($m)  { Write-Host ""; Write-Host "==> $m" -ForegroundColor Cyan }
function Warn($m) { Write-Host "!! $m" -ForegroundColor Yellow }
function Die($m)  { Write-Host "XX $m" -ForegroundColor Red; exit 1 }
$ErrorActionPreference = 'Continue'

# ---- 1. Python 3.10+
Say "Memeriksa Python"
$py = $null
foreach ($cand in @(@('py','-3'), @('python'), @('python3'))) {
  $exe = $cand[0]
  $pre = @(); if ($cand.Count -gt 1) { $pre = $cand[1..($cand.Count - 1)] }
  if (Get-Command $exe -ErrorAction SilentlyContinue) {
    try {
      $v = & $exe @pre -c "import sys; print(sys.version_info[0]*100+sys.version_info[1])" 2>$null
      if ([int]$v -ge 310) { $py = @($exe) + $pre; break }
    } catch { }
  }
}
if (-not $py) {
  Die "Python 3.10+ tidak ditemukan. Pasang dari https://www.python.org/downloads/ (centang 'Add python.exe to PATH') atau jalankan: winget install Python.Python.3.12 -- lalu buka PowerShell baru dan ulangi."
}
$pyExe = $py[0]; $pyPre = @(); if ($py.Count -gt 1) { $pyPre = $py[1..($py.Count - 1)] }
Write-Host ("Python: " + (& $pyExe @pyPre --version))

# ---- 2. Ambil kode dari git (atau perbarui)
Say "Mengambil kode ke $Dir"
$hasGit = [bool](Get-Command git -ErrorAction SilentlyContinue)
if (Test-Path (Join-Path $Dir '.git')) {
  git -C $Dir pull --ff-only
  if ($LASTEXITCODE -ne 0) { Warn "git pull gagal; memakai versi yang ada" }
} elseif ($hasGit) {
  git clone --depth 1 $Repo $Dir
  if ($LASTEXITCODE -ne 0) { Die "git clone gagal" }
} else {
  Warn "git tidak ditemukan, mengunduh arsip ZIP"
  $zip = Join-Path $env:TEMP 'emisisense.zip'; $tmp = Join-Path $env:TEMP 'emisisense_zip'
  if (Test-Path $tmp) { Remove-Item $tmp -Recurse -Force }
  Invoke-WebRequest (($Repo -replace '\.git$', '') + '/archive/refs/heads/main.zip') -OutFile $zip
  Expand-Archive $zip -DestinationPath $tmp -Force
  New-Item -ItemType Directory -Force -Path $Dir | Out-Null
  Copy-Item (Join-Path (Get-ChildItem $tmp | Select-Object -First 1).FullName '*') $Dir -Recurse -Force
}
Set-Location $Dir

# ---- 3. Lingkungan virtual sendiri (.venv) + dependensi
Say "Membuat lingkungan virtual (.venv) dan memasang dependensi (beberapa menit)"
$vpy = Join-Path $Dir '.venv\Scripts\python.exe'
if (-not (Test-Path $vpy)) {
  & $pyExe @pyPre -m venv .venv
  if ($LASTEXITCODE -ne 0 -or -not (Test-Path $vpy)) { Die "Gagal membuat lingkungan virtual" }
}
& $vpy -m pip install --quiet --upgrade pip
& $vpy -m pip install --quiet -r requirements.txt
if ($LASTEXITCODE -ne 0) { Die "Pemasangan dependensi gagal (cek koneksi internet)" }
& $vpy -c "import cv2, flask, scipy; from emisisense_vision.detector import SSDDetector; SSDDetector(); print('Uji pemuatan: OK (OpenCV ' + cv2.__version__ + ', model SSD termuat)')"
if ($LASTEXITCODE -ne 0) { Die "Uji pemuatan gagal" }

# ---- 4. Opsional: firewall, mulai otomatis, pintasan
$pwArgs = @(); if ($Password) { $pwArgs = @('--password', $Password) }
if ($Firewall) {
  $isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
  if ($isAdmin) {
    Remove-NetFirewallRule -DisplayName 'EmisiSense Vision' -ErrorAction SilentlyContinue
    New-NetFirewallRule -DisplayName 'EmisiSense Vision' -Direction Inbound -Protocol TCP -LocalPort $Port -Action Allow -Profile Private,Domain | Out-Null
    Write-Host "Firewall: port $Port dibuka untuk jaringan Private/Domain"
  } else {
    Warn "Untuk membuka firewall, jalankan ulang PowerShell sebagai Administrator dengan -Firewall"
    Warn "atau manual: New-NetFirewallRule -DisplayName 'EmisiSense Vision' -Direction Inbound -Protocol TCP -LocalPort $Port -Action Allow"
  }
}
try {
  $desk = [Environment]::GetFolderPath('Desktop')
  $lnk = (New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $desk 'EmisiSense Vision.lnk'))
  $lnk.TargetPath = (Join-Path $Dir 'run.bat'); $lnk.WorkingDirectory = $Dir; $lnk.Save()
  Write-Host "Pintasan 'EmisiSense Vision' dibuat di Desktop"
} catch { }
if ($AutoStart) {
  Say "Mendaftarkan mulai otomatis saat login"
  $argLine = "`"$Dir\run.py`" --no-browser --port $Port " + ($pwArgs -join ' ')
  $act = New-ScheduledTaskAction -Execute $vpy -Argument $argLine -WorkingDirectory $Dir
  $trg = New-ScheduledTaskTrigger -AtLogOn
  $set = New-ScheduledTaskSettingsSet -RestartCount 5 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero)
  Register-ScheduledTask -TaskName 'EmisiSenseVision' -Action $act -Trigger $trg -Settings $set -Force | Out-Null
  Start-ScheduledTask -TaskName 'EmisiSenseVision'
  Write-Host "Tugas terjadwal 'EmisiSenseVision' aktif (Task Scheduler)"
}

# ---- 5. Alamat akses
Say "Selesai. Alamat akses dari jaringan lokal:"
& $vpy -c "import sys; from emisisense_vision import netinfo; [print('    ' + u) for u in netinfo.urls(int(sys.argv[1]))]" $Port
Write-Host ""
Write-Host " Folder       : $Dir"
Write-Host " Jalankan     : klik dua kali pintasan di Desktop, atau $Dir\run.bat"
Write-Host " Perbarui     : jalankan ulang perintah pemasang (data & pengaturan tidak terhapus)"
Write-Host " Data deteksi : $Dir\data\emisisense.db (SQLite)"

if (-not $AutoStart -and -not $NoStart) {
  Say "Menjalankan sekarang (Ctrl+C untuk berhenti)"
  & $vpy run.py --port $Port @pwArgs
}
