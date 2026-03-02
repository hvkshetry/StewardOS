#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

link_skill() {
  local persona="$1"
  local skill_name="$2"
  local source_rel="$3"

  local source_path="${REPO_ROOT}/${source_rel}"
  local persona_skills_dir="${REPO_ROOT}/agent-configs/${persona}/.codex/skills"
  local target_path="${persona_skills_dir}/${skill_name}"

  if [[ ! -d "${source_path}" ]]; then
    echo "skip: missing source ${source_rel}" >&2
    return 0
  fi

  mkdir -p "${persona_skills_dir}"
  ln -sfn "${source_path}" "${target_path}"
  echo "linked ${persona}/${skill_name} -> ${source_rel}"
}

# Link persona-owned skills.
for persona_dir in "${REPO_ROOT}"/skills/personas/*; do
  [[ -d "${persona_dir}" ]] || continue
  persona="$(basename "${persona_dir}")"

  for skill_dir in "${persona_dir}"/*; do
    [[ -d "${skill_dir}" ]] || continue
    skill_name="$(basename "${skill_dir}")"
    link_skill "${persona}" "${skill_name}" "skills/personas/${persona}/${skill_name}"
  done

  # Shared family email formatting is used by all personas.
  link_skill "${persona}" "family-email-formatting" "skills/family-email-formatting"
done

# Shared search skills currently used by chief-of-staff.
if [[ -d "${REPO_ROOT}/agent-configs/chief-of-staff" ]]; then
  link_skill "chief-of-staff" "search" "skills/shared/search"
  link_skill "chief-of-staff" "search-strategy" "skills/shared/search-strategy"
fi

echo "Persona skill bootstrap complete."
