@echo off
cd /d "%~dp0"
if not exist .venv (
  echo Membuat lingkungan Python...
  python -m venv .venv
  .venv\Scripts\python -m pip install --upgrade pip
  .venv\Scripts\pip install -r requirements.txt
)
.venv\Scripts\python run.py %*
