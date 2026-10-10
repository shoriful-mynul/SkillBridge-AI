#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
PY=python3
command -v python3 >/dev/null 2>&1 || PY=python
if ! command -v "$PY" >/dev/null 2>&1; then
  echo "Python 3.10+ is required: https://www.python.org/downloads/"; exit 1
fi
[ -x .venv/bin/python ] || { echo "Creating a private Python environment, first run only..."; "$PY" -m venv .venv; }
echo "Installing requirements, first run takes about a minute..."
.venv/bin/python -m pip install --disable-pip-version-check -q -r requirements.txt
[ -f .env ] || cp .env.example .env
PORT="${PORT:-8000}"
echo
echo "  SkillBridge AI is running at  http://127.0.0.1:${PORT}"
echo "  Press Ctrl+C to stop."
echo
( sleep 3; { command -v open >/dev/null && open "http://127.0.0.1:${PORT}"; } || { command -v xdg-open >/dev/null && xdg-open "http://127.0.0.1:${PORT}"; } || true ) >/dev/null 2>&1 &
exec .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port "${PORT}"
