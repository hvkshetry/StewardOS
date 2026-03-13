#!/usr/bin/env bash
set -euo pipefail

STEWARD_USER="<YOUR_USER>"
STEWARD_ROOT="/home/${STEWARD_USER}/stewardos"
REPO_URL="https://github.com/stewardos-user/StewardOS.git"
BRANCH="main"

sudo apt-get update
sudo apt-get install -y git curl jq python3-venv nodejs npm

if [[ ! -d "${STEWARD_ROOT}/.git" ]]; then
  git clone --branch "${BRANCH}" "${REPO_URL}" "${STEWARD_ROOT}"
else
  git -C "${STEWARD_ROOT}" fetch origin
  git -C "${STEWARD_ROOT}" checkout "${BRANCH}"
  git -C "${STEWARD_ROOT}" pull --ff-only origin "${BRANCH}"
fi

mkdir -p "${STEWARD_ROOT}/runtime" "${STEWARD_ROOT}/logs"
echo "Host bootstrap complete: ${STEWARD_ROOT}"
