#!/usr/bin/env bash
# flash-from-pc.sh - install the Ubuntu ZIP from the PC over USB (adb in TWRP), without a microSD card
#
# Does what the ZIP's own installer does, but driven from the PC: it streams the root image into the
# userdata partition (sda29, 1 MiB from its start), reads it back and compares the SHA-256, and only then
# writes the boot image (sda20) and verifies it too. Nothing else on the phone is touched.
#
# Usage:   flash-from-pc.sh ZIP [--serial SERIAL] [--method auto|exec-in|nc] [--port 5555]
#
# Needs on the PC: adb, unzip, xz, sha256sum, bash. On the phone: TWRP (adb state "recovery"), started
# from the TWRP main screen; do not use the SD-card installer at the same time.
#
# Methods for sending the root image (it is several GB, so it is streamed, never stored on the phone):
#   exec-in   "adb exec-in" (only if your adb has it)
#   nc        adb forward + "nc -l" on the phone (TWRP's busybox) and bash's /dev/tcp on the PC
#   auto      exec-in if "adb help" lists it, otherwise nc (default)
# Whatever the method, the result is only accepted if the SHA-256 read back from the phone matches.
#
# THIS DESTROYS EVERYTHING ON userdata (Android's data). It asks you to type FLASH first.
set -euo pipefail

ZIP=""; SERIAL=""; METHOD=auto; PORT=5555
say() { printf '%s\n' "$*"; }
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
while [ $# -gt 0 ]; do
  case "$1" in
    --serial) SERIAL="${2:?}"; shift 2;;
    --method) METHOD="${2:?}"; shift 2;;
    --port) PORT="${2:?}"; shift 2;;
    -h|--help) sed -n '2,22p' "$0"; exit 0;;
    -*) die "unknown option: $1";;
    *) [ -z "$ZIP" ] || die "only one ZIP"; ZIP="$1"; shift;;
  esac
done
[ -n "$ZIP" ] || die "usage: $0 ZIP [--serial SERIAL] [--method auto|exec-in|nc] [--port N]"
[ -f "$ZIP" ] || die "ZIP not found: $ZIP"
case "$METHOD" in auto|exec-in|nc) ;; *) die "--method must be auto, exec-in or nc";; esac
for T in adb unzip xz sha256sum sed head tr; do command -v "$T" >/dev/null || die "missing tool on the PC: $T"; done

A=(adb); [ -z "$SERIAL" ] || A=(adb -s "$SERIAL")
ph() { "${A[@]}" shell "$1" | tr -d '\r'; }          # run on the phone, text out
MIB=1048576
DATA_WANT=/dev/block/sda29; BOOT_WANT=/dev/block/sda20

say "== 1/7 the ZIP"
UB=META-INF/com/google/android/update-binary
unzip -p "$ZIP" "$UB" >/dev/null 2>&1 || die "this is not an Ubuntu ZIP built by tools/image/build-image.sh (no $UB)"
meta() { unzip -p "$ZIP" "$UB" | sed -n "s/^$1=//p" | head -1 | tr -d '"'; }
BOOT_SIZE=$(meta BOOT_SIZE); BOOT_SHA=$(meta BOOT_SHA256); RAW_SIZE=$(meta RAW_SIZE); RAW_SHA=$(meta RAW_SHA256); PARTS=$(meta PARTS)
for V in BOOT_SIZE BOOT_SHA RAW_SIZE RAW_SHA PARTS; do [ -n "${!V}" ] || die "could not read $V from the installer script in the ZIP"; done
[ $((RAW_SIZE % MIB)) = 0 ] || die "root image size is not a multiple of 1 MiB"
say "   root image $RAW_SIZE bytes, sha256 $RAW_SHA"
say "   boot image $BOOT_SIZE bytes, sha256 $BOOT_SHA"
say "   testing the ZIP (CRC)..."
unzip -tq "$ZIP" >/dev/null 2>&1 || die "the ZIP is corrupt or incomplete"
TMP=$(mktemp -d "${TMPDIR:-/tmp}/s9-flash.XXXXXX"); trap 'rm -rf "$TMP"' EXIT
unzip -p "$ZIP" payload/boot.img > "$TMP/boot.img"
[ "$(wc -c < "$TMP/boot.img")" = "$BOOT_SIZE" ] || die "boot.img in the ZIP has the wrong size"
H=$(sha256sum "$TMP/boot.img" | cut -d' ' -f1); [ "$H" = "$BOOT_SHA" ] || die "boot.img in the ZIP has the wrong SHA-256"

say "== 2/7 the phone"
STATE=$("${A[@]}" get-state 2>/dev/null || true)
[ "$STATE" = recovery ] || die "adb state is '${STATE:-none}', expected 'recovery'. Boot TWRP, connect USB, run 'adb devices'."
DEV=$(ph 'getprop ro.product.device'); MODEL=$(ph 'getprop ro.product.model')
say "   device $DEV   model $MODEL"
case "$DEV:$MODEL" in starqltechn:*|*:SM-G9600*) ;; *) die "only for the Galaxy S9 SM-G9600 (starqltechn)";; esac
NAMES=/dev/block/platform/soc/1d84000.ufshc/by-name
BOOT=$(ph "readlink -f $NAMES/boot"); DATA=$(ph "readlink -f $NAMES/userdata")
say "   boot -> $BOOT   userdata -> $DATA"
[ "$BOOT" = "$BOOT_WANT" ] || die "boot is '$BOOT', expected $BOOT_WANT"
[ "$DATA" = "$DATA_WANT" ] || die "userdata is '$DATA', expected $DATA_WANT"
BS=$(ph "blockdev --getsize64 $BOOT"); DS=$(ph "blockdev --getsize64 $DATA")
[ "$BS" -ge "$BOOT_SIZE" ] || die "boot partition ($BS) is smaller than the boot image"
[ "$DS" -ge $((RAW_SIZE + 2 * MIB)) ] || die "userdata ($DS) is too small for the root image"

say "== 3/7 confirmation"
say "   This overwrites userdata (all Android data) and boot. system, vendor, modem, efs stay untouched."
printf '   Type FLASH to continue: '
read -r ANS </dev/tty || die "no terminal for the confirmation"
[ "$ANS" = FLASH ] || die "cancelled, nothing was written"

say "== 4/7 unmounting userdata on the phone"
for N in 1 2 3 4 5 6; do
  ph 'while read D M R; do r=$(readlink -f "$D" 2>/dev/null); [ "$r" = '"$DATA"' ] && umount "$M" 2>/dev/null; done < /proc/mounts; true' >/dev/null
done
LEFT=$(ph 'while read D M R; do r=$(readlink -f "$D" 2>/dev/null); [ "$r" = '"$DATA"' ] && echo "$M"; done < /proc/mounts; true')
[ -z "$LEFT" ] || die "userdata is still mounted at: $LEFT (in TWRP, Mount menu: untick Data, then retry)"

say "== 5/7 writing the root image (several minutes; no progress bar)"
if [ "$METHOD" = auto ]; then
  if adb help 2>&1 | grep -q 'exec-in'; then METHOD=exec-in; else METHOD=nc; fi
fi
say "   method: $METHOD"
stream() { ( for P in $PARTS; do unzip -p "$ZIP" "payload/$P" || exit 1; done ) | xz -dc; }
DD="dd of=$DATA bs=$MIB seek=1"
if [ "$METHOD" = exec-in ]; then
  stream | "${A[@]}" exec-in "$DD" || die "writing failed (exec-in). userdata is incomplete: do not boot, run again."
else
  "${A[@]}" forward "tcp:$PORT" "tcp:$PORT" >/dev/null || die "adb forward failed"
  "${A[@]}" shell "nc -l -p $PORT | $DD; sync" >"$TMP/phone.log" 2>&1 &
  SHELLPID=$!
  sleep 3
  kill -0 "$SHELLPID" 2>/dev/null || { cat "$TMP/phone.log"; die "the listener on the phone did not start (does this TWRP have nc -l?). Try --method exec-in, or use the SD-card installer."; }
  stream > "/dev/tcp/127.0.0.1/$PORT" || die "sending failed. userdata is incomplete: do not boot, run again."
  wait "$SHELLPID" || { cat "$TMP/phone.log"; die "the phone side failed. userdata is incomplete: do not boot, run again."; }
  "${A[@]}" forward --remove "tcp:$PORT" >/dev/null 2>&1 || true
fi
ph sync >/dev/null

say "== 6/7 reading the root image back from the phone (SHA-256)"
H=$(ph "dd if=$DATA bs=$MIB skip=1 count=$((RAW_SIZE / MIB)) 2>/dev/null | sha256sum" | cut -d' ' -f1)
say "   $H"
[ "$H" = "$RAW_SHA" ] || die "userdata does not match the image. Do NOT reboot into Ubuntu; run this again."

say "== 7/7 writing boot"
"${A[@]}" push "$TMP/boot.img" /tmp/s9-boot.img >/dev/null || die "adb push of boot.img failed"
H=$(ph 'sha256sum /tmp/s9-boot.img' | cut -d' ' -f1)
[ "$H" = "$BOOT_SHA" ] || die "boot.img arrived damaged on the phone"
ph "dd if=/tmp/s9-boot.img of=$BOOT bs=4096 2>/dev/null; sync" >/dev/null
H=$(ph "head -c $BOOT_SIZE $BOOT | sha256sum" | cut -d' ' -f1)
[ "$H" = "$BOOT_SHA" ] || die "boot does not match after writing"
ph 'rm -f /tmp/s9-boot.img' >/dev/null || true

say ""
say "DONE: root image and boot verified. Reboot with:  adb reboot"
