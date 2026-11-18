@echo off
rem Menjalankan EmisiSense Vision memakai lingkungan virtual .venv (dibuat otomatis bila belum ada).
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Membuat lingkungan virtual .venv ...
  where py >nul 2>nul && (py -3 -m venv .venv) || (python -m venv .venv)
  if not exist ".venv\Scripts\python.exe" (echo Python 3.10+ belum terpasang. & pause & exit /b 1)
  ".venv\Scripts\python.exe" -m pip install --upgrade pip
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt || (pause & exit /b 1)
)
".venv\Scripts\python.exe" run.py %*
pause
