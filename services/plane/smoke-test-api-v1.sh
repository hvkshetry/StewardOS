#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICES_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
ENV_FILE="${SERVICES_DIR}/.env"

read_env_value() {
  local env_file="$1"
  local key="$2"

  python3 - "$env_file" "$key" <<'PY'
import pathlib
import sys

env_path = pathlib.Path(sys.argv[1])
key = sys.argv[2]

for raw in env_path.read_text().splitlines():
    if not raw or raw.lstrip().startswith("#") or "=" not in raw:
        continue
    current_key, value = raw.split("=", 1)
    if current_key.strip() != key:
        continue
    value = value.rstrip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1]
    print(value)
    break
PY
}

if [ -f "${ENV_FILE}" ]; then
  : "${PLANE_BASE_URL:=$(read_env_value "${ENV_FILE}" PLANE_BASE_URL)}"
  : "${PLANE_API_TOKEN:=$(read_env_value "${ENV_FILE}" PLANE_API_TOKEN)}"
  : "${PLANE_SMOKE_WORKSPACE_SLUG:=$(read_env_value "${ENV_FILE}" PLANE_SMOKE_WORKSPACE_SLUG)}"
  : "${PLANE_SMOKE_PROJECT_ID:=$(read_env_value "${ENV_FILE}" PLANE_SMOKE_PROJECT_ID)}"
  : "${PLANE_SMOKE_WORK_ITEM_ID:=$(read_env_value "${ENV_FILE}" PLANE_SMOKE_WORK_ITEM_ID)}"
fi

BASE_URL="${PLANE_BASE_URL:-http://127.0.0.1:8082}"
API_TOKEN="${PLANE_API_TOKEN:?PLANE_API_TOKEN must be set for Plane API smoke checks}"
WORKSPACE_SLUG="${PLANE_SMOKE_WORKSPACE_SLUG:-chief-of-staff}"
PROJECT_ID="${PLANE_SMOKE_PROJECT_ID:-}"
WORK_ITEM_ID="${PLANE_SMOKE_WORK_ITEM_ID:-}"

auth_header=(-H "X-Api-Key: ${API_TOKEN}" -H "Accept: application/json")

extract_first_id() {
  python3 -c 'import json,sys; data=json.load(sys.stdin); items=data if isinstance(data, list) else data.get("results", []); print(items[0]["id"] if items else "")'
}

retry_curl() {
  local attempts="${1}"
  shift

  local attempt=1
  while true; do
    if curl -fsS "$@"; then
      return 0
    fi
    if [ "${attempt}" -ge "${attempts}" ]; then
      return 1
    fi
    attempt=$((attempt + 1))
    sleep 3
  done
}

if [ -z "${PROJECT_ID}" ]; then
  PROJECT_ID="$(
    retry_curl 10 "${auth_header[@]}" \
      "${BASE_URL}/api/v1/workspaces/${WORKSPACE_SLUG}/projects/" | extract_first_id
  )"
fi

if [ -z "${PROJECT_ID}" ]; then
  echo "Plane API v1 smoke check failed: no project found in workspace '${WORKSPACE_SLUG}'." >&2
  exit 1
fi

if [ -z "${WORK_ITEM_ID}" ]; then
  WORK_ITEM_ID="$(
    retry_curl 10 "${auth_header[@]}" \
      "${BASE_URL}/api/v1/workspaces/${WORKSPACE_SLUG}/projects/${PROJECT_ID}/work-items/" | extract_first_id
  )"
fi

if [ -z "${WORK_ITEM_ID}" ]; then
  echo "Plane API v1 smoke check failed: no work item found in workspace '${WORKSPACE_SLUG}' project '${PROJECT_ID}'." >&2
  echo "Set PLANE_SMOKE_WORK_ITEM_ID in services/.env if the workspace has no existing work items." >&2
  exit 1
fi

check_endpoint() {
  local name="$1"
  local url="$2"
  local status
  local body_file
  local attempt=1
  local max_attempts=10

  body_file="$(mktemp)"
  while true; do
    status="$(
      curl -sS -o "${body_file}" -w '%{http_code}' "${auth_header[@]}" "${url}" || true
    )"

    if [ "${status}" -ge 200 ] && [ "${status}" -lt 400 ]; then
      echo "  OK: ${name} (HTTP ${status})"
      rm -f "${body_file}"
      return 0
    fi

    if [ "${attempt}" -ge "${max_attempts}" ]; then
      break
    fi

    attempt=$((attempt + 1))
    sleep 3
  done

  echo "  FAIL: ${name} (HTTP ${status}) after ${max_attempts} attempts" >&2
  sed -n '1,20p' "${body_file}" >&2 || true
  rm -f "${body_file}"
  return 1
}

echo "Plane API v1 smoke checks:"
check_endpoint "pages" "${BASE_URL}/api/v1/workspaces/${WORKSPACE_SLUG}/projects/${PROJECT_ID}/pages/"
check_endpoint "views" "${BASE_URL}/api/v1/workspaces/${WORKSPACE_SLUG}/projects/${PROJECT_ID}/views/"
check_endpoint "estimates" "${BASE_URL}/api/v1/workspaces/${WORKSPACE_SLUG}/projects/${PROJECT_ID}/estimates/"
check_endpoint "relations" "${BASE_URL}/api/v1/workspaces/${WORKSPACE_SLUG}/projects/${PROJECT_ID}/work-items/${WORK_ITEM_ID}/relations/"
