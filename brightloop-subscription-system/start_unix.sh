#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
if [ ! -x ".venv/bin/python" ]; then
  python3 -m venv .venv
fi
source .venv/bin/activate
if [ ! -f ".env" ]; then cp .env.example .env; fi
python -m pip install -r requirements.txt
python app.py
