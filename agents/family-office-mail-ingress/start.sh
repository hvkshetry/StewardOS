#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
exec .venv/bin/uvicorn src.main:app --host "${SERVICE_HOST:-127.0.0.1}" --port "${SERVICE_PORT:-8311}"
