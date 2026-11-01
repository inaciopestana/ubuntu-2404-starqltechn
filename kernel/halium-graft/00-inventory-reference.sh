#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd -P)"
# shellcheck source=lib/common.sh
source "$HERE/lib/common.sh"

URL='https://github.com/Gustavo2Toledo/ubuntu-touch-star2qltechn.git'
PROJ="$(project_root)"
WORK="$PROJ/workdir/halium-graft"
REF="$WORK/reference-star2qltechn"
REPORT="$WORK/reports"
OFFLINE=''
DRY=0

usage(){ cat <<USAGE
Uso: $0 [--offline DIR] [--reference-dir DIR] [--report-dir DIR] [--dry-run]
Inventaria o port do Gustavo sem tocar na rootfs do S9.
USAGE
}
while (($#)); do
  case "$1" in
    --offline) OFFLINE="$2"; shift 2;;
    --reference-dir) REF="$2"; shift 2;;
    --report-dir) REPORT="$2"; shift 2;;
    --dry-run) DRY=1; shift;;
    -h|--help) usage; exit 0;;
    *) die "opção desconhecida: $1";;
  esac
done
ensure_under "$PROJ" "$WORK"
mkdir -p "$REPORT"
if [[ -n "$OFFLINE" ]]; then
  [[ -d "$OFFLINE" ]] || die "offline não existe: $OFFLINE"
  REF="$(realpath "$OFFLINE")"
else
  require_cmd git
  if [[ -d "$REF/.git" ]]; then
    run_or_echo "$DRY" git -C "$REF" fetch --all --prune
    run_or_echo "$DRY" git -C "$REF" reset --hard origin/main
  elif [[ "$DRY" == 1 ]]; then
    log "dry-run: clonaria $URL em $REF"
  else
    rm -rf "$REF"
    git clone --depth=1 "$URL" "$REF"
  fi
fi
[[ -d "$REF" ]] || { [[ "$DRY" == 1 ]] && exit 0; die "checkout ausente: $REF"; }

find "$REF" -mindepth 1 -maxdepth 8 -printf '%P\n' | sort > "$REPORT/reference-tree.txt"
(
  grep -rInE --exclude-dir=.git --binary-files=without-match \
    'star2qltechn|starqltechn|star2qlte|starqlte|G965|G960|Galaxy S9\+' "$REF" || true
) > "$REPORT/device-identifiers.txt"
(
  find "$REF" -type f -not -path '*/.git/*' -print | \
    grep -Ei '/overlay/|halium|hybris|mir|graphics|display|hwcomposer|gralloc|egl|lxc|android|usb|displayport|ccic' || true
) | sed "s#^$REF/##" | sort > "$REPORT/graphics-candidates.txt"

log "Referência: $REF"
log "Relatórios: $REPORT"
