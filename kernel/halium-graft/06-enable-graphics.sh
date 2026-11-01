#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd -P)"; source "$HERE/lib/common.sh"
ROOT=''; MODE='status'; APPLY=0
while (($#)); do case "$1" in --root) ROOT="$2"; shift 2;; --enable) MODE=enable; shift;; --disable) MODE=disable; shift;; --apply) APPLY=1; shift;; *) die "opção $1";; esac; done
[[ -d "$ROOT/etc/systemd/system" ]] || die "--root inválida"
cmd(){ if [[ "$APPLY" == 1 ]]; then chroot "$ROOT" "$@"; else printf 'DRY chroot %q ' "$ROOT"; printf '%q ' "$@"; echo; fi; }
case "$MODE" in
 enable)
   # keep direct Xorg path out
   if [[ "$APPLY" == 1 ]]; then ln -snf /dev/null "$ROOT/etc/systemd/system/display-manager.service"; fi
   cmd systemctl enable s9-halium-preflight.service s9-mir.service;;
 disable) cmd systemctl disable s9-mir.service s9-halium-preflight.service || true;;
 status) cmd systemctl status s9-halium-preflight.service s9-mir.service || true;;
esac
