#!/usr/bin/env bash
# flash-recovery.sh - write a recovery image to the phone's "recovery" partition, with checks
#
# Run as root ON THE PHONE (Ubuntu or TWRP shell), with the image already copied there.
# It backs up the current recovery first, writes the new one, reads it back and compares.
# Only the partition named "recovery" is touched. boot, system, vendor and userdata are not.
#
# Usage:  flash-recovery.sh IMAGE EXPECTED_SHA256 [BACKUP_FILE]
#   BACKUP_FILE defaults to ./recovery-before-<date>.img  (keep it; it is your way back)
set -euo pipefail

IMG="${1:-}"; WANT="${2:-}"; BK="${3:-}"
say() { printf '%s\n' "$*"; }
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
[ -n "$IMG" ] && [ -n "$WANT" ] || die "usage: $0 IMAGE EXPECTED_SHA256 [BACKUP_FILE]"
[ "$(id -u)" = 0 ] || die "run as root"
[ -f "$IMG" ] || die "image not found: $IMG"
for T in sha256sum dd cmp blockdev readlink; do command -v "$T" >/dev/null || die "missing tool: $T"; done

say "== checking the image"
GOT=$(sha256sum "$IMG" | cut -d' ' -f1)
say "   sha256 $GOT"
[ "$GOT" = "$WANT" ] || die "sha256 differs from the expected value"
ISZ=$(wc -c < "$IMG")

say "== locating the recovery partition"
DEV=""
for C in /dev/block/platform/soc/1d84000.ufshc/by-name/recovery /dev/block/bootdevice/by-name/recovery /dev/disk/by-partlabel/recovery; do
  [ -b "$C" ] && { DEV="$(readlink -f "$C")"; break; }
done
[ -n "$DEV" ] || die "recovery partition not found"
say "   $DEV"
[ "$DEV" = /dev/sda21 ] || die "expected /dev/sda21 for recovery on the Galaxy S9, found $DEV"
PSZ=$(blockdev --getsize64 "$DEV")
say "   partition $PSZ bytes, image $ISZ bytes"
[ "$ISZ" -le "$PSZ" ] || die "the image is larger than the partition"

[ -n "$BK" ] || BK="./recovery-before-$(date +%Y%m%d-%H%M%S).img"
say "== backing up the current recovery to $BK"
[ ! -e "$BK" ] || die "backup file already exists: $BK"
dd if="$DEV" of="$BK" bs=1M status=none
sha256sum "$BK" | sed 's/^/   /'

printf 'Write %s to %s? Type FLASH to continue: ' "$IMG" "$DEV"
read -r A </dev/tty || die "no terminal for the confirmation"
[ "$A" = FLASH ] || die "cancelled, nothing was written"

say "== writing"
dd if="$IMG" of="$DEV" bs=1M conv=fsync status=none
sync
say "== reading back"
H=$(dd if="$DEV" bs=1M count=$(( (ISZ + 1048575) / 1048576 )) status=none | head -c "$ISZ" | sha256sum | cut -d' ' -f1)
say "   $H"
[ "$H" = "$WANT" ] || die "readback differs! restore with: dd if=$BK of=$DEV bs=1M conv=fsync"
say "DONE: recovery verified. Reboot to recovery to test (settings should now survive a reboot)."
say "Way back: dd if=$BK of=$DEV bs=1M conv=fsync"
