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
# mode clean   : scrubbed root for distribution. tools/image/audit-tree.py removes personal data,
#                renames the desktop account, installs the first-boot overlay and then audits the
#                result; a blocking finding stops the build. Two ways to get the account:
#                  --first-boot-account   (releases) the image carries a locked placeholder account and a
#                                         wizard asks for user name, password and host name on the first boot
#                                         (clean-overlay/ + clean-overlay-firstboot/)
#                  --user NAME            (private tests) the account is created now; the password is asked
#                                         for, or give --password-hash-file
#                --stop-after-audit stops after the audit (no image), to iterate on the findings.
#
# The root file system is rebuilt with EXACTLY the ext4 features of the phone's file system
# (read from meta/ext4-root.txt) because the 4.9 kernel cannot mount newer features
# (for example orphan_file). Nothing is written to the phone by this script.
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
DECOMP=${S9_DECOMPRESS:-zstd -dc}
MODE=restore BACKUP= BOOT= OUT= LABEL= WORK= KEEP=0 EXTRA_MIB=1024 SKIP_VERIFY=0
NEWUSER= FIRSTBOOT=0 HOSTNAME_NEW=s9 PWFILE= STOP_AUDIT=0 KEEP_HOME=() DROP=() ALLOW_BLOB=() PRUNE=() PRIVATE=0
HALIUM_SHA=527c53fd8e27957fe4046cd8588d689dec338e8abb6531af4602c2f235ca0944
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
    --user) NEWUSER=$2; shift 2;;
    --first-boot-account) FIRSTBOOT=1; NEWUSER=s9user; shift;;
    --hostname) HOSTNAME_NEW=$2; shift 2;;
    --password-hash-file) PWFILE=$2; shift 2;;
    --stop-after-audit) STOP_AUDIT=1; shift;;
    --keep-home) KEEP_HOME+=(--keep-home "$2"); shift 2;;
    --drop) DROP+=(--drop "$2"); shift 2;;
    --halium-sha256) HALIUM_SHA=$2; shift 2;;
    --allow-blob) ALLOW_BLOB+=(--allow-blob "$2"); PRIVATE=1; shift 2;;
    --prune-opt-unreferenced) PRUNE=(--prune-opt-unreferenced); shift;;
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
case $MODE in
  restore) ;;
  clean) [ -n "$NEWUSER" ] || die "mode clean needs --first-boot-account or --user NAME"
         [[ $NEWUSER =~ ^[a-z_][a-z0-9_-]{0,31}$ ]] && [ "$NEWUSER" != root ] || die "--user must be a lower-case account name (not root)"
         [ -f "$HERE/audit-tree.py" ] && [ -d "$HERE/clean-overlay" ] || die "audit-tree.py or clean-overlay/ missing next to this script"
         [ "$FIRSTBOOT" = 0 ] || [ -d "$HERE/clean-overlay-firstboot" ] || die "clean-overlay-firstboot/ missing next to this script"
         command -v openssl >/dev/null || die "missing tool: openssl";;
  *) die "unknown mode $MODE";;
esac
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
FEAT=$(sed -n 's/^Filesystem features:[[:space:]]*//p' "$M" | tr -s '[:space:]' ' ' | sed 's/ $//')
BS=$(sed -n 's/^Block size:[[:space:]]*//p' "$M" | tr -d '[:space:]'); ISZ=$(sed -n 's/^Inode size:[[:space:]]*//p' "$M" | tr -d '[:space:]')
PL=$(sed -n 's/^Filesystem volume name:[[:space:]]*//p' "$M" | tr -d '[:space:]'); UUID=$(sed -n 's/^Filesystem UUID:[[:space:]]*//p' "$M" | tr -d '[:space:]')
[[ $BS =~ ^[0-9]+$ ]] && [[ $ISZ =~ ^[0-9]+$ ]] && [ -n "$FEAT" ] || die "cannot read features/block size/inode size from $M"
[ -n "$LABEL" ] || { LABEL=$PL; [ "$LABEL" != "<none>" ] || LABEL=s9root; }
FEAT_LIST=$(echo "$FEAT" | tr ' ' '\n' | grep -vx 'needs_recovery' | paste -sd, -)
info "features: $FEAT_LIST"
info "block size $BS, inode size $ISZ, label '$LABEL', uuid $UUID"

say "1/5 extracting the root tree (this takes a few minutes)"
rm -rf "$TREE"; mkdir -p "$TREE"
$DECOMP "$BACKUP/root.tar.zst" | tar -xpf - --xattrs --xattrs-include='*' --acls --numeric-owner -C "$TREE"
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

if [ "$MODE" = clean ]; then
  say "1b/5 inventory of the extracted tree (names and sizes only)"
  python3 -I "$HERE/audit-tree.py" inventory "$TREE" | tee "$WORK/inventory.txt" | head -n 330
  OLDUSER=$(awk -F: '$3==1000{print $1; exit}' "$TREE/etc/passwd")
  [ -n "$OLDUSER" ] || die "no account with uid 1000 in the tree"
  OLDHOST=$(head -n1 "$TREE/etc/hostname" 2>/dev/null | tr -d '[:space:]')
  OVERLAYS=(--overlay "$HERE/clean-overlay") FB_SCRUB=() FB_AUDIT=()
  if [ "$FIRSTBOOT" = 1 ]; then
    say "1c/5 account: a locked placeholder; the user's name, password and host name are asked on the first boot"
    OVERLAYS+=(--overlay "$HERE/clean-overlay-firstboot"); FB_SCRUB=(--defer-account); FB_AUDIT=(--first-boot-account)
    S9_PASSWORD_HASH=
  else
    say "1c/5 account and password for the new image"
    if [ -n "$PWFILE" ]; then
      S9_PASSWORD_HASH=$(head -n1 "$PWFILE")
    else
      [ -r /dev/tty ] || die "no terminal for the password prompt: use --password-hash-file"
      while :; do
        read -rsp "   Password for '$NEWUSER': " P1 </dev/tty >/dev/tty; echo >/dev/tty
        read -rsp "   Repeat: " P2 </dev/tty >/dev/tty; echo >/dev/tty
        [ -n "$P1" ] && [ "$P1" = "$P2" ] && break
        echo "   empty or different, again" >/dev/tty
      done
      S9_PASSWORD_HASH=$(printf '%s' "$P1" | openssl passwd -6 -stdin); unset P1 P2
    fi
  fi
  export S9_PASSWORD_HASH
  say "1d/5 scrubbing personal data and renaming the account"
  python3 -I "$HERE/audit-tree.py" scrub "$TREE" --user "$NEWUSER" --hostname "$HOSTNAME_NEW" \
      "${OVERLAYS[@]}" "${FB_SCRUB[@]}" "${KEEP_HOME[@]}" "${DROP[@]}" "${PRUNE[@]}"
  unset S9_PASSWORD_HASH
  say "1e/5 audit (blocking findings stop the build)"
  REPORT=$OUT/clean-report-$STAMP.txt
  python3 -I "$HERE/audit-tree.py" audit "$TREE" --old-user "$OLDUSER" --old-hostname "$OLDHOST" --expect-user "$NEWUSER" "${FB_AUDIT[@]}" \
      --halium-sha256 "$HALIUM_SHA" --report "$REPORT" "${ALLOW_BLOB[@]}" || {
    info "the tree is kept in $TREE for inspection (delete it afterwards)"
    die "the audit found blocking problems; nothing was built"; }
  info "audit passed (REVIEW items above are for you to read)"
  if [ "$STOP_AUDIT" = 1 ]; then info "--stop-after-audit: no image built; tree kept in $TREE"; exit 0; fi
fi

NFILES=$(find "$TREE" -xdev | wc -l); USED=$(du -sxb "$TREE" | cut -f1)
info "$NFILES entries, $(human "$USED") of data"

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
ZTAG=$MODE; [ "$PRIVATE" = 0 ] || ZTAG=$MODE-PRIVATE-do-not-publish
ZIP=$OUT/s9-$ZTAG-$STAMP.zip
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
