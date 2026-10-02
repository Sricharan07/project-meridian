#!/usr/bin/env bash
# Run the app on http://localhost:8000. The first run creates .venv and installs
# requirements.txt; the knowledge base in kb/ is already built, so nothing else is needed.
set -euo pipefail
cd "$(dirname "$0")"

python=""
for candidate in python3.13 python3.12 python3.11 python3; do
  if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c 'import sys; sys.exit(sys.version_info < (3, 11))'; then
    python=$candidate
    break
  fi
done
if [ -z "$python" ]; then
  echo "Meridian needs Python 3.11 or newer." >&2
  exit 1
fi

[ -x .venv/bin/python ] || "$python" -m venv .venv
.venv/bin/python -m pip install --quiet --disable-pip-version-check -r requirements.txt

# Without a key, chat replays the recorded answers to the example questions and shows evidence for anything else.
[ -f .env ] || cp .env.example .env

port="${PORT:-8000}"
echo "Meridian on http://localhost:$port"
exec .venv/bin/python -m meridian serve --port "$port"
