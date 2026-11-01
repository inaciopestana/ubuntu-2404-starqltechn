#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd -P)"; source "$HERE/lib/common.sh"
ROOT=''; APPLY=0; MODE=xfce-shell
while (($#)); do case "$1" in --root) ROOT="$2"; shift 2;; --apply) APPLY=1; shift;; --mode) MODE="$2"; shift 2;; *) die "opção $1";; esac; done
[[ "$MODE" =~ ^(minimal|xfce-shell|xwayland)$ ]] || die "mode inválido"
[[ -d "$ROOT" ]] || die "--root obrigatório"
if [[ "$MODE" == minimal ]]; then log "Nenhum componente XFCE será habilitado"; exit 0; fi
# We do not apt-install blindly: package availability differs between Ubuntu/UT roots.
need=(xfce4-panel xfce4-appfinder xfsettingsd thunar xfce4-terminal)
for c in "${need[@]}"; do [[ -x "$ROOT/usr/bin/$c" || -x "$ROOT/usr/local/bin/$c" ]] || echo "MISSING $c"; done
if [[ "$APPLY" == 1 ]]; then
  mkdir -p "$ROOT/home/$S9_USER/.config/systemd/user/default.target.wants"
  ln -snf /etc/systemd/user/s9-xfce-shell.service "$ROOT/home/$S9_USER/.config/systemd/user/default.target.wants/s9-xfce-shell.service"
  chown -h 1000:1000 "$ROOT/home/$S9_USER/.config/systemd/user/default.target.wants/s9-xfce-shell.service" 2>/dev/null || true
else echo "DRY enable s9-xfce-shell.service for UID 1000"; fi
