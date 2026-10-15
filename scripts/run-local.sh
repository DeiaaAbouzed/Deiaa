#!/usr/bin/env bash
# Try رُشد on this computer only (http://localhost:8000). For real use, deploy with Docker + HTTPS.
set -euo pipefail
cd "$(dirname "$0")/.."
if [ ! -d .venv ]; then
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
. .venv/bin/activate
pip install -q --upgrade pip
pip install -q -r backend/requirements.txt
export RUSHD_COOKIE_SECURE="${RUSHD_COOKIE_SECURE:-false}"   # plain http is acceptable only on localhost
cd backend
python -m rushd init
echo "→ افتح المتصفح على: http://localhost:8000"
exec python -m rushd serve --host 127.0.0.1 --port 8000
