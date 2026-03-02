#!/usr/bin/env bash
# Start the family brief agent (development mode)
set -euo pipefail

cd "$(dirname "$0")"

# Activate venv if it exists
if [ -d ".venv" ]; then
    source .venv/bin/activate
elif [ -d "venv" ]; then
    source venv/bin/activate
fi

exec uvicorn src.main:app --host 127.0.0.1 --port 8300 --reload
