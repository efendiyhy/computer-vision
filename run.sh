#!/usr/bin/env bash
# Menjalankan EmisiSense Vision memakai lingkungan virtual .venv (dibuat otomatis bila belum ada).
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
  echo "Membuat lingkungan virtual .venv ..."
  python3 -m venv .venv && .venv/bin/python -m pip install --upgrade pip && .venv/bin/python -m pip install -r requirements.txt || exit 1
fi
exec .venv/bin/python run.py "$@"
