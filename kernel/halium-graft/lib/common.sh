#!/usr/bin/env bash
set -euo pipefail

log() { printf '[s9-halium] %s\n' "$*" >&2; }
die() { printf '[s9-halium] ERRO: %s\n' "$*" >&2; exit 1; }
require_cmd() { command -v "$1" >/dev/null 2>&1 || die "comando ausente: $1"; }
project_root() {
  local d
  d="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd -P)"
  printf '%s\n' "$d"
}
ensure_under() {
  local base path rb rp
  base="$1"; path="$2"
  rb="$(realpath -m "$base")"; rp="$(realpath -m "$path")"
  case "$rp" in "$rb"|"$rb"/*) ;; *) die "caminho fora da área permitida: $rp" ;; esac
}
run_or_echo() {
  local dry="$1"; shift
  if [[ "$dry" == 1 ]]; then printf '+ '; printf '%q ' "$@"; printf '\n'; else "$@"; fi
}
sha256_path() {
  local p="$1"
  if [[ -L "$p" ]]; then printf 'L %s -> %s\n' "$p" "$(readlink "$p")"
  elif [[ -f "$p" ]]; then sha256sum "$p"
  elif [[ -d "$p" ]]; then printf 'D %s\n' "$p"
  else printf 'MISSING %s\n' "$p"; fi
}
