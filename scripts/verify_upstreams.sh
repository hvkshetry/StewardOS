#!/usr/bin/env bash
set -euo pipefail

LOCKFILE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/docs/upstreams/upstreams.lock.yaml"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ ! -f "$LOCKFILE" ]]; then
  echo "Lockfile not found: $LOCKFILE" >&2
  exit 1
fi

current_name=""
current_path=""
current_commit=""
errors=0

check_entry() {
  [[ -n "$current_path" && -n "$current_commit" ]] || return 0

  target="$REPO_ROOT/$current_path"
  if [[ ! -d "$target/.git" ]]; then
    echo "MISSING: $current_name ($current_path)"
    errors=$((errors + 1))
    return 0
  fi

  head_commit="$(git -C "$target" rev-parse HEAD)"
  if [[ "$head_commit" != "$current_commit" ]]; then
    echo "MISMATCH: $current_name ($current_path) expected $current_commit got $head_commit"
    errors=$((errors + 1))
  else
    echo "OK: $current_name ($current_path) @ $head_commit"
  fi
}

while IFS= read -r line; do
  case "$line" in
    "  - name:"*)
      check_entry
      current_name="${line#*name: }"
      current_path=""
      current_commit=""
      ;;
    "    path:"*)
      current_path="${line#*path: }"
      ;;
    "    commit:"*)
      current_commit="${line#*commit: }"
      ;;
  esac
done < "$LOCKFILE"

check_entry

if [[ $errors -ne 0 ]]; then
  echo "Verification failed with $errors issue(s)." >&2
  exit 1
fi

echo "All upstream checkouts match lockfile."
