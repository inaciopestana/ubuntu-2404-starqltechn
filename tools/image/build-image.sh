#!/usr/bin/env bash
# build-image.sh - turn a phone backup into a TWRP-flashable ZIP (boot image + Ubuntu root image).
#
#   sudo tools/image/build-image.sh --backup ~/s9-backups/s9-YYYYMMDD-HHMMSS \
#        --boot out/clean-.../boot-clean.img --out ~/s9-images [--mode restore] [--label s9root]
#
# Input : a backup made by tools/backup-phone.sh (root.tar.zst, meta/ext4-root.txt, SHA256SUMS).
# Output: <out>/s9-<mode>-<stamp>.zip  (+ .sha256), flashed from TWRP with the normal "Install" button.
#
# mode restore : the root exactly as it was in the backup (personal data included: keep it private).
# mode clean   : (not implemented yet) scrubbed root; see tools/image/audit-tree.py for the audit.
#
# The root file system is rebuilt with EXACTLY the ext4 features of the phone's file system
# (read from meta/ext4-root.txt) because the 4.9 kernel cannot mount newer features
# (for example orphan_file). Nothing is written to the phone by this script.
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
DECOMP=${S9_DECOMPRESS:-zstd -dc}
MODE=restore BACKUP= BOOT= OUT= LABEL= WORK= KEEP=0 EXTRA_MIB=1024 SKIP_VERIFY=0
while [ $# -gt 0 ]; do
  case $1 in
    --backup) BACKUP=$2; shift 2;;
    --boot) BOOT=$2; shift 2;;
    --out) OUT=$2; shift 2;;
    --mode) MODE=$2; shift 2;;
    --label) LABEL=$2; shift 2;;
    --work) WORK=$2; shift 2;;
    --extra-mib) EXTRA_MIB=$2; shift 2;;
    --keep-work) KEEP=1; shift;;
    --skip-backup-check) SKIP_VERIFY=1; shift;;
    -h|--help) sed -n '2,15p' "$0"; exit 0;;
    *) echo "unknown option: $1" >&2; exit 2;;
  esac
done
say()  { printf '\n== %s\n' "$*"; }
info() { printf '   %s\n' "$*"; }
die()  { printf '\nERROR: %s\n' "$*" >&2; exit 1; }
human() { numfmt --to=iec --suffix=B "$1" 2>/dev/null || echo "$1 B"; }

say "preflight"
[ "$(id -u)" = 0 ] || die "run as root (sudo): the tree must keep its numeric owners"
[ -n "$BACKUP" ] && [ -n "$BOOT" ] && [ -n "$OUT" ] || die "need --backup DIR --boot FILE --out DIR"
case $MODE in restore) ;; clean) die "mode clean is not implemented yet (run tools/image/audit-tree.py first)";; *) die "unknown mode $MODE";; esac
for t in ${DECOMP%% *} tar xz mke2fs e2fsck dumpe2fs python3 sha256sum split; do command -v "$t" >/dev/null || die "missing tool: $t"; done
[ -f "$BACKUP/root.tar.zst" ] && [ -f "$BACKUP/meta/ext4-root.txt" ] || die "$BACKUP is not a backup (root.tar.zst / meta/ext4-root.txt missing)"
[ -f "$BOOT" ] || die "boot image not found: $BOOT"
[ "$(stat -c %s "$BOOT")" = 67108864 ] || die "the boot image must be 64 MiB (flash-ready, padded)"
if [ "$SKIP_VERIFY" = 0 ]; then
  ( cd "$BACKUP" && sha256sum -c SHA256SUMS >/dev/null 2>&1 ) || die "the backup fails sha256sum -c (use --skip-backup-check to ignore)"
  info "backup hashes OK"
fi
STAMP=$(date +%Y%m%d-%H%M%S)
mkdir -p "$OUT"; OUT=$(cd "$OUT" && pwd)
WORK=${WORK:-$OUT/work-$STAMP}; mkdir -p "$WORK"
TREE=$WORK/tree; IMG=$WORK/root.img
FREE=$(df -B1 --output=avail "$WORK" | tail -1 | tr -d ' ')
ARCH_SZ=$(stat -c %s "$BACKUP/root.tar.zst")
[ "$FREE" -gt $((ARCH_SZ * 14)) ] || die "not enough free space in $WORK (have $(human "$FREE"), want about $(human $((ARCH_SZ * 14))))"
info "work dir: $WORK  (free $(human "$FREE"))"

say "ext4 parameters of the phone's root"
M=$BACKUP/meta/ext4-root.txt
FEAT=$(sed -n 's/^Filesystem features: *//p' "$M" | tr -s ' ')
BS=$(sed -n 's/^Block size: *//p' "$M"); ISZ=$(sed -n 's/^Inode size: *//p' "$M")
PL=$(sed -n 's/^Filesystem volume name: *//p' "$M"); UUID=$(sed -n 's/^Filesystem UUID: *//p' "$M")
[ -n "$FEAT" ] && [ -n "$BS" ] && [ -n "$ISZ" ] || die "cannot read features/block size/inode size from $M"
[ -n "$LABEL" ] || { LABEL=$PL; [ "$LABEL" != "<none>" ] || LABEL=s9root; }
FEAT_LIST=$(echo "$FEAT" | tr ' ' '\n' | grep -vx 'needs_recovery' | paste -sd, -)
info "features: $FEAT_LIST"
info "block size $BS, inode size $ISZ, label '$LABEL', uuid $UUID"

say "1/5 extracting the root tree (this takes a few minutes)"
rm -rf "$TREE"; mkdir -p "$TREE"
$DECOMP "$BACKUP/root.tar.zst" | tar -xpf - --xattrs --xattrs-include='*' --acls --numeric-owner -C "$TREE"
NFILES=$(find "$TREE" -xdev | wc -l); USED=$(du -sxb "$TREE" | cut -f1)
info "$NFILES entries, $(human "$USED") of data"
# the swap file is not in the backup (it cannot be copied reliably); recreate it on first boot if fstab wants it
if grep -qsE '^[^#]*[[:space:]/]swapfile[[:space:]]' "$TREE/etc/fstab" 2>/dev/null && [ ! -e "$TREE/swapfile" ]; then
  mkdir -p "$TREE/etc/systemd/system/multi-user.target.wants"
  cat > "$TREE/etc/systemd/system/s9-swapfile.service" <<'UNIT'
[Unit]
Description=Create the 4 GiB swap file if it is missing (restored image)
ConditionPathExists=!/swapfile
Before=swap.target
[Service]
Type=oneshot
ExecStart=/bin/sh -c 'fallocate -l 4G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon -p 10 /swapfile'
[Install]
WantedBy=multi-user.target
UNIT
  ln -sf ../s9-swapfile.service "$TREE/etc/systemd/system/multi-user.target.wants/s9-swapfile.service"
  info "fstab uses /swapfile: added s9-swapfile.service to create it on the first boot"
fi

say "2/5 building the ext4 image"
MIB=1048576
RAW_MIB=$(( (USED * 112 / 100 + EXTRA_MIB * MIB + MIB - 1) / MIB ))
INODES=$(( NFILES * 14 / 10 + 20000 ))
rm -f "$IMG"; truncate -s "${RAW_MIB}M" "$IMG"
UUID_OPT=(); [ -z "$UUID" ] || UUID_OPT=(-U "$UUID")
mke2fs -q -t ext4 -F -b "$BS" -I "$ISZ" -N "$INODES" -m 1 -L "$LABEL" "${UUID_OPT[@]}" -O "none,$FEAT_LIST" -E root_owner=0:0 -d "$TREE" "$IMG"
info "image: ${RAW_MIB} MiB"
NEWF=$(dumpe2fs -h "$IMG" 2>/dev/null | sed -n 's/^Filesystem features: *//p' | tr -s ' ')
BAD=$(comm -13 <(echo "$FEAT" | tr ' ' '\n' | sort -u) <(echo "$NEWF" | tr ' ' '\n' | sort -u) | grep -vx 'needs_recovery' || true)
[ -z "$BAD" ] || die "the new file system has features the phone's kernel may not support: $(echo $BAD)"
info "features of the new image are a subset of the phone's: OK"
e2fsck -fn "$IMG" >"$WORK/e2fsck.txt" 2>&1 || { tail -15 "$WORK/e2fsck.txt"; die "e2fsck found problems in the new image"; }
info "e2fsck -fn: clean"
if [ "$KEEP" = 0 ]; then rm -rf "$TREE"; fi

say "3/5 hashing and compressing (xz, all cores; slow step)"
RAW_SIZE=$(stat -c %s "$IMG"); [ $((RAW_SIZE % MIB)) = 0 ] || die "image size is not a multiple of 1 MiB"
RAW_SHA=$(sha256sum "$IMG" | cut -d' ' -f1)
BOOT_SHA=$(sha256sum "$BOOT" | cut -d' ' -f1); BOOT_SIZE=$(stat -c %s "$BOOT")
info "raw image $(human "$RAW_SIZE")  sha256 $RAW_SHA"
xz -T0 -6 -c "$IMG" > "$WORK/root.img.xz"
info "compressed $(human "$(stat -c %s "$WORK/root.img.xz")")"
rm -f "$WORK"/root.img.xz.part*
split -b $((1900 * MIB)) -d -a 2 "$WORK/root.img.xz" "$WORK/root.img.xz.part"
PARTS=$(cd "$WORK" && ls root.img.xz.part* | tr '\n' ' ' | sed 's/ $//')
info "parts: $PARTS"

say "4/5 assembling the ZIP"
ZIP=$OUT/s9-$MODE-$STAMP.zip
SCRIPT=$WORK/update-binary
sed -e "s|@MODE@|$MODE|g" -e "s|@BOOT_SIZE@|$BOOT_SIZE|" -e "s|@BOOT_SHA256@|$BOOT_SHA|" \
    -e "s|@RAW_SIZE@|$RAW_SIZE|" -e "s|@RAW_SHA256@|$RAW_SHA|" -e "s|@PARTS@|$PARTS|" \
    "$HERE/twrp/update-binary.in" > "$SCRIPT"
sh -n "$SCRIPT" || die "generated update-binary has a syntax error"
cat > "$WORK/MANIFEST.txt" <<TXT
mode: $MODE
created: $STAMP
boot.img: $BOOT_SIZE bytes sha256 $BOOT_SHA
root image (raw ext4, written at 1 MiB of userdata): $RAW_SIZE bytes sha256 $RAW_SHA
parts: $PARTS
TXT
python3 -I - "$ZIP" "$WORK" "$HERE/twrp/updater-script" "$BOOT" "$PARTS" <<'PY'
import sys, zipfile, os
zpath, work, upd, boot, parts = sys.argv[1:6]
with zipfile.ZipFile(zpath, 'w', zipfile.ZIP_STORED, allowZip64=True) as z:
    z.write(os.path.join(work, 'update-binary'), 'META-INF/com/google/android/update-binary')
    z.write(upd, 'META-INF/com/google/android/updater-script')
    z.write(os.path.join(work, 'MANIFEST.txt'), 'payload/MANIFEST.txt')
    z.write(boot, 'payload/boot.img')
    for p in parts.split():
        z.write(os.path.join(work, p), 'payload/' + p)
PY
ZSZ=$(stat -c %s "$ZIP")
( cd "$OUT" && sha256sum "$(basename "$ZIP")" > "$(basename "$ZIP").sha256" )
info "$(basename "$ZIP"): $(human "$ZSZ")"
[ "$ZSZ" -lt $((4096 * MIB - 8 * MIB)) ] || info "WARNING: the ZIP is larger than 4 GiB and needs ZIP64; the recovery's unzip may not read it (untested)."

say "5/5 verifying the ZIP"
python3 -I - "$ZIP" <<'PY'
import sys, zipfile
z = zipfile.ZipFile(sys.argv[1]); bad = z.testzip()
print('   members:', len(z.namelist()), '| CRC test:', 'OK' if bad is None else 'FAILED at ' + bad)
sys.exit(0 if bad is None else 1)
PY
[ "$KEEP" = 1 ] || rm -f "$WORK/root.img" "$WORK/root.img.xz" "$WORK"/root.img.xz.part*
say "DONE"
info "ZIP    : $ZIP"
info "sha256 : $(cut -d' ' -f1 "$ZIP.sha256")"
info "work   : $WORK (delete it when you no longer need it)"
