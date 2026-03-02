#!/usr/bin/env bash
set -euo pipefail

STEWARD_USER="<YOUR_USER>"
STEWARD_ROOT="<STEWARDOS_ROOT>"
SYSTEMD_DIR="/etc/systemd/system"

install_unit() {
  local template="$1"
  local out_name="$2"
  sed \
    -e "s|<STEWARD_USER>|${STEWARD_USER}|g" \
    -e "s|<STEWARDOS_ROOT>|${STEWARD_ROOT}|g" \
    "${template}" | sudo tee "${SYSTEMD_DIR}/${out_name}" >/dev/null
  sudo systemctl daemon-reload
  sudo systemctl enable --now "${out_name}"
}

install_unit "${STEWARD_ROOT}/agents/family-office-mail-ingress/family-office-mail-ingress.service.example" "family-office-mail-ingress.service"
install_unit "${STEWARD_ROOT}/agents/family-office-mail-worker/family-office-mail-worker.service.example" "family-office-mail-worker.service"
install_unit "${STEWARD_ROOT}/agents/family-brief-agent/family-brief-agent.service.example" "family-brief-agent.service"

echo "Systemd service templates installed and started."
