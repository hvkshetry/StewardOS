#!/usr/bin/env bash
set -euo pipefail

REMOTE_HOST="${1:-home-server}"
REMOTE_HOME="${REMOTE_HOME:-/home/stewardos-user}"
REMOTE_PLANE_API_DIR="${REMOTE_HOME}/personal/servers/plane-fork/apps/api"
REMOTE_SERVICES_DIR="${REMOTE_HOME}/personal/services"
REMOTE_NETWORK="${REMOTE_NETWORK:-services_personal-net}"
REMOTE_IMAGE="${REMOTE_IMAGE:-stewardos/plane-backend:v1.2.3-api-v1}"
TEST_PATH="${TEST_PATH:-plane/tests/contract/api/test_coordination.py}"

read_remote_env_value() {
  local key="$1"
  ssh "${REMOTE_HOST}" "python3 - <<'PY' '${REMOTE_SERVICES_DIR}/.env' '${key}'
import pathlib
import sys

env_path = pathlib.Path(sys.argv[1])
key = sys.argv[2]

for raw in env_path.read_text().splitlines():
    if not raw or raw.lstrip().startswith('#') or '=' not in raw:
        continue
    current_key, value = raw.split('=', 1)
    if current_key.strip() != key:
        continue
    value = value.rstrip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'\"', \"'\"}:
        value = value[1:-1]
    print(value)
    break
PY"
}

POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-$(read_remote_env_value POSTGRES_PASSWORD)}"
PLANE_SECRET_KEY="${PLANE_SECRET_KEY:-$(read_remote_env_value PLANE_SECRET_KEY)}"
PLANE_WEB_URL="${PLANE_WEB_URL:-$(read_remote_env_value PLANE_WEB_URL)}"
if [ -z "${PLANE_WEB_URL}" ]; then
  PLANE_WEB_URL="$(read_remote_env_value PLANE_BASE_URL)"
fi
PLANE_CORS_ALLOWED_ORIGINS="${PLANE_CORS_ALLOWED_ORIGINS:-$(read_remote_env_value PLANE_CORS_ALLOWED_ORIGINS)}"
if [ -z "${PLANE_CORS_ALLOWED_ORIGINS}" ]; then
  PLANE_CORS_ALLOWED_ORIGINS="${PLANE_WEB_URL}"
fi

if [ -z "${POSTGRES_PASSWORD}" ] || [ -z "${PLANE_SECRET_KEY}" ] || [ -z "${PLANE_WEB_URL}" ]; then
  echo "Missing required Plane env values on ${REMOTE_HOST}." >&2
  echo "Expected POSTGRES_PASSWORD, PLANE_SECRET_KEY, and either PLANE_WEB_URL or PLANE_BASE_URL in ${REMOTE_SERVICES_DIR}/.env." >&2
  exit 1
fi

ssh "${REMOTE_HOST}" "
docker run --rm \
  --network '${REMOTE_NETWORK}' \
  -v '${REMOTE_PLANE_API_DIR}:/code' \
  -e DATABASE_URL='postgresql://postgres:${POSTGRES_PASSWORD}@personal-db:5432/plane' \
  -e REDIS_URL='redis://plane-valkey:6379/' \
  -e RABBITMQ_HOST='plane-mq' \
  -e SECRET_KEY='${PLANE_SECRET_KEY}' \
  -e WEB_URL='${PLANE_WEB_URL}' \
  -e CORS_ALLOWED_ORIGINS='${PLANE_CORS_ALLOWED_ORIGINS}' \
  -e USE_MINIO='1' \
  -e DJANGO_SETTINGS_MODULE='plane.settings.test' \
  '${REMOTE_IMAGE}' \
  sh -lc '
    python -m pip install -q -r /code/requirements/test.txt
    cd /code
    pytest ${TEST_PATH} -q
  '
"
