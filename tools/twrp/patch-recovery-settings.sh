#!/usr/bin/env bash
# patch-recovery-settings.sh - make TWRP keep its settings across reboots (Galaxy S9, starqltechn)
#
# The stock TWRP build for this phone stores no settings: every boot starts with the defaults.
# TWRP keeps its settings (the .twrps file) on the partition marked "settingsstorage" in
# /etc/recovery.fstab. This script adds that flag to the /cache line and nothing else:
#
#   /cache  ext4  .../by-name/cache                      (before)
#   /cache  ext4  .../by-name/cache  flags=settingsstorage   (after)
#
# It works on an IMAGE FILE on your PC. It never touches the phone. Flash the result with
# flash-recovery.sh (run on the phone) or with TWRP/Odin.
#
# Usage:
#   patch-recovery-settings.sh --in recovery-original.img --out recovery-settings.img \
#                              [--magiskboot /path/to/magiskboot] [--keep-work] [--expect-sha256 HASH]
#
# Needs: magiskboot (x86-64 or arm64 build, GPL-3.0, from the Magisk project; not shipped here),
#        sha256sum, cmp, diff. The input image must be a TWRP recovery of this phone (Android boot
#        image v0 with the ramdisk containing etc/recovery.fstab).
#
# Checks done before the output is accepted:
#   * the input has exactly one /cache line in etc/recovery.fstab
#   * after repacking, the new image unpacks again
#   * kernel and kernel_dtb are byte-identical to the input
#   * the ONLY difference in etc/recovery.fstab is the flag on the /cache line
#   * every other ramdisk entry is unchanged (name list identical)
#   * the output has the same size as the input (a partition dump keeps its size)
set -euo pipefail

IN=""; OUT=""; MB="${MAGISKBOOT:-}"; KEEP=0; EXPECT=""
say() { printf '%s\n' "$*"; }
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
while [ $# -gt 0 ]; do
  case "$1" in
    --in) IN="${2:?}"; shift 2;;
    --out) OUT="${2:?}"; shift 2;;
    --magiskboot) MB="${2:?}"; shift 2;;
    --keep-work) KEEP=1; shift;;
    --expect-sha256) EXPECT="${2:?}"; shift 2;;
    -h|--help) sed -n '2,32p' "$0"; exit 0;;
    *) die "unknown option: $1";;
  esac
done
[ -n "$IN" ] && [ -n "$OUT" ] || die "usage: $0 --in IMG --out IMG [--magiskboot PATH]"
[ -f "$IN" ] || die "input not found: $IN"
[ ! -e "$OUT" ] || die "output already exists, refusing to overwrite: $OUT"
[ -n "$MB" ] || MB="$(command -v magiskboot || true)"
[ -n "$MB" ] && [ -x "$MB" ] || die "magiskboot not found; pass --magiskboot PATH"
for T in sha256sum cmp diff sed grep wc; do command -v "$T" >/dev/null || die "missing tool: $T"; done

WORK="$(mktemp -d "${TMPDIR:-/tmp}/s9-recovery-patch.XXXXXX")"
cleanup() { [ "$KEEP" = 1 ] && say "work dir kept: $WORK" || rm -rf "$WORK"; }
trap cleanup EXIT
MB="$(readlink -f "$MB")"
mb() { ( cd "$1" && shift && "$MB" "$@" ); }

say "== input"
INSZ=$(wc -c < "$IN"); INSHA=$(sha256sum "$IN" | cut -d' ' -f1)
say "   $IN  $INSZ bytes  sha256 $INSHA"
if [ -n "$EXPECT" ]; then [ "$INSHA" = "$EXPECT" ] || die "input sha256 does not match --expect-sha256"; fi

say "== 1/6 unpacking"
mkdir "$WORK/a"; cp "$IN" "$WORK/a/r.img"
mb "$WORK/a" unpack r.img >"$WORK/a/unpack.log" 2>&1 || { cat "$WORK/a/unpack.log"; die "magiskboot could not unpack the image"; }
for F in kernel ramdisk.cpio; do [ -s "$WORK/a/$F" ] || die "unpacked image has no $F"; done
grep -E 'KERNEL_SZ|RAMDISK_SZ|OS_VERSION|KERNEL_FMT|RAMDISK_FMT|SAMSUNG' "$WORK/a/unpack.log" | sed 's/^/   /'

say "== 2/6 reading etc/recovery.fstab"
mb "$WORK/a" cpio ramdisk.cpio "extract etc/recovery.fstab fstab.orig" >/dev/null 2>&1 || true
[ -s "$WORK/a/fstab.orig" ] || die "etc/recovery.fstab not found in the ramdisk (is this a TWRP image?)"
N=$(grep -c -E '^/cache[[:space:]]' "$WORK/a/fstab.orig" || true)
[ "$N" = 1 ] || die "expected exactly one /cache line, found $N"
LINE=$(grep -E '^/cache[[:space:]]' "$WORK/a/fstab.orig")
say "   /cache line: $LINE"

say "== 3/6 patching"
cp "$WORK/a/fstab.orig" "$WORK/fstab.new"
if printf '%s\n' "$LINE" | grep -q 'settingsstorage'; then
  say "   already has settingsstorage: nothing to change"
  cp "$IN" "$OUT"; sha256sum "$OUT"; exit 0
fi
if printf '%s\n' "$LINE" | grep -q 'flags='; then
  sed -i -E '/^\/cache[[:space:]]/ s/(flags=[^[:space:]]*)/\1;settingsstorage/' "$WORK/fstab.new"
else
  sed -i -E '/^\/cache[[:space:]]/ s/[[:space:]]*$/\tflags=settingsstorage/' "$WORK/fstab.new"
fi
say "   new line:    $(grep -E '^/cache[[:space:]]' "$WORK/fstab.new")"
DL=$(diff "$WORK/a/fstab.orig" "$WORK/fstab.new" | grep -c '^[<>]' || true)
[ "$DL" = 2 ] || die "unexpected fstab difference ($DL changed lines)"

say "== 4/6 writing it back into the ramdisk"
MODE=$(mb "$WORK/a" cpio ramdisk.cpio "ls -r" 2>/dev/null | grep -E '(^|[[:space:]])etc/recovery.fstab$' | awk '{print $1}' | head -1 || true)
case "$MODE" in [0-7][0-7][0-7]|0[0-7][0-7][0-7]) ;; *) MODE=0644;; esac
cp "$WORK/fstab.new" "$WORK/a/recovery.fstab.new"
mb "$WORK/a" cpio ramdisk.cpio "rm etc/recovery.fstab" "add $MODE etc/recovery.fstab recovery.fstab.new" >"$WORK/a/cpio.log" 2>&1 \
  || { cat "$WORK/a/cpio.log"; die "could not update the ramdisk"; }
say "   etc/recovery.fstab replaced (mode $MODE)"

say "== 5/6 repacking"
mb "$WORK/a" repack r.img new.img >"$WORK/a/repack.log" 2>&1 || { cat "$WORK/a/repack.log"; die "repack failed"; }
[ -s "$WORK/a/new.img" ] || die "repack produced no image"
NEWSZ=$(wc -c < "$WORK/a/new.img")
if [ "$NEWSZ" -lt "$INSZ" ]; then
  # a dump of the recovery partition keeps the partition size: pad with zeros like the original
  say "   padding $NEWSZ -> $INSZ bytes"
  dd if=/dev/zero bs=1 count=$((INSZ - NEWSZ)) 2>/dev/null >> "$WORK/a/new.img"
elif [ "$NEWSZ" -gt "$INSZ" ]; then
  die "the patched image ($NEWSZ bytes) is larger than the input ($INSZ bytes); it may not fit the partition"
fi

say "== 6/6 verifying the result"
mkdir "$WORK/b"; cp "$WORK/a/new.img" "$WORK/b/r.img"
mb "$WORK/b" unpack r.img >"$WORK/b/unpack.log" 2>&1 || die "the patched image does not unpack"
cmp -s "$WORK/a/kernel" "$WORK/b/kernel" || die "kernel changed"
if [ -e "$WORK/a/kernel_dtb" ] || [ -e "$WORK/b/kernel_dtb" ]; then cmp -s "$WORK/a/kernel_dtb" "$WORK/b/kernel_dtb" || die "kernel_dtb changed"; fi
say "   kernel and kernel_dtb identical to the input"
mb "$WORK/b" cpio ramdisk.cpio "extract etc/recovery.fstab fstab.check" >/dev/null 2>&1 || true
cmp -s "$WORK/fstab.new" "$WORK/b/fstab.check" || die "etc/recovery.fstab in the new image is not what was intended"
say "   etc/recovery.fstab in the new image is the intended one"
# entry names unchanged (the order may change because the entry was re-added)
for X in a b; do
  mb "$WORK/$X" cpio ramdisk.cpio "ls -r" 2>/dev/null | awk '{print $NF}' | sort > "$WORK/$X.names"
done
if [ -s "$WORK/a.names" ]; then
  cmp -s "$WORK/a.names" "$WORK/b.names" || die "the list of ramdisk entries changed"
  say "   ramdisk entry names unchanged ($(wc -l < "$WORK/a.names") entries)"
else
  say "   (this magiskboot cannot list the ramdisk; entry-name check skipped)"
fi
[ "$(wc -c < "$WORK/a/new.img")" = "$INSZ" ] || die "size mismatch"
cp "$WORK/a/new.img" "$OUT"
say ""
say "DONE: $OUT"
say "      $(wc -c < "$OUT") bytes   sha256 $(sha256sum "$OUT" | cut -d' ' -f1)"
say "Flash it with flash-recovery.sh (on the phone) or from TWRP > Install > Install Image > Recovery."
