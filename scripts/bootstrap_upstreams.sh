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
current_remote=""
current_commit=""

apply_entry() {
  [[ -n "$current_path" && -n "$current_remote" && -n "$current_commit" ]] || return 0

  target="$REPO_ROOT/$current_path"
  echo "==> $current_name ($current_path)"

  if [[ -d "$target/.git" ]]; then
    if ! git -C "$target" diff --quiet || ! git -C "$target" diff --cached --quiet; then
      echo "  skipping dirty checkout: $target"
      return 0
    fi
    git -C "$target" remote set-url origin "$current_remote"
    git -C "$target" fetch --all --tags --prune
  else
    mkdir -p "$(dirname "$target")"
    git clone "$current_remote" "$target"
  fi

  git -C "$target" checkout "$current_commit"
  echo "  checked out $(git -C "$target" rev-parse --short HEAD)"
}

while IFS= read -r line; do
  case "$line" in
    "  - name:"*)
      apply_entry
      current_name="${line#*name: }"
      current_path=""
      current_remote=""
      current_commit=""
      ;;
    "    path:"*)
      current_path="${line#*path: }"
      ;;
    "    remote:"*)
      current_remote="${line#*remote: }"
      ;;
    "    commit:"*)
      current_commit="${line#*commit: }"
      ;;
  esac
done < "$LOCKFILE"

apply_entry
