#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd -P)"; source "$HERE/lib/common.sh"
ROOT=''; MANIFEST=''; APPLY=0
usage(){ echo "Uso: $0 --root MOUNT --manifest FILE [--apply]  (default=dry-run)"; }
while (($#)); do case "$1" in --root) ROOT="$2"; shift 2;; --manifest) MANIFEST="$2"; shift 2;; --apply) APPLY=1; shift;; -h|--help) usage; exit 0;; *) die "opção $1";; esac; done
[[ -d "$ROOT" && -f "$MANIFEST" ]] || die "--root e --manifest obrigatórios"
ROOT="$(realpath "$ROOT")"
[[ "$ROOT" != / && "$ROOT" != /home && "$ROOT" != /usr ]] || die "root insegura"
[[ -e "$ROOT/etc/os-release" ]] || die "sentinela etc/os-release ausente"
J="$ROOT/var/lib/s9-halium-graft"; B="$J/backup"; LOG="$J/journal.tsv"
if [[ "$APPLY" == 1 ]]; then mkdir -p "$B"; : > "$LOG"; fi
while IFS=$'\t' read -r kind src target required reason owner; do
  [[ "$kind" == kind ]] && continue
  [[ "$src" =~ G965|star2qltechn|star2qlte ]] && die "fonte S9+ proibida: $src"
  dst="$ROOT$target"; ensure_under "$ROOT" "$dst"
  if [[ ! -e "$src" && ! -L "$src" ]]; then [[ "$required" == yes ]] && die "fonte obrigatória ausente: $src"; continue; fi
  if [[ "$APPLY" != 1 ]]; then printf 'DRY %s -> %s\n' "$src" "$dst"; continue; fi
  mkdir -p "$(dirname "$dst")"
  if [[ -e "$dst" || -L "$dst" ]]; then
    bak="$B/${target#/}"; mkdir -p "$(dirname "$bak")"; cp -a "$dst" "$bak"; printf 'RESTORE\t%s\t%s\n' "$bak" "$dst" >> "$LOG"
  else printf 'REMOVE\t-\t%s\n' "$dst" >> "$LOG"; fi
  rm -rf "$dst"; cp -a "$src" "$dst"
done < "$MANIFEST"
# our overlay is staged separately, deliberately after reference runtime
OVERLAY="$(project_root)/rootfs-overlay/halium-graft"
if [[ "$APPLY" == 1 ]]; then cp -a "$OVERLAY"/. "$ROOT"/; else echo "DRY overlay $OVERLAY -> $ROOT"; fi
log "$([[ "$APPLY" == 1 ]] && echo Aplicado || echo 'Dry-run concluído')"
