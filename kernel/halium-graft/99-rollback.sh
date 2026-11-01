#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd -P)"; source "$HERE/lib/common.sh"
ROOT=''; APPLY=0
while (($#)); do case "$1" in --root) ROOT="$2"; shift 2;; --apply) APPLY=1; shift;; *) die "opção $1";; esac; done
[[ -d "$ROOT" ]] || die "--root obrigatório"
J="$ROOT/var/lib/s9-halium-graft/journal.tsv"; [[ -f "$J" ]] || die "journal ausente"
tac "$J" | while IFS=$'\t' read -r op a dst; do
  ensure_under "$ROOT" "$dst"
  if [[ "$APPLY" != 1 ]]; then echo "DRY $op $a -> $dst"; continue; fi
  case "$op" in
    RESTORE) rm -rf "$dst"; mkdir -p "$(dirname "$dst")"; cp -a "$a" "$dst";;
    REMOVE) rm -rf "$dst";;
  esac
done
