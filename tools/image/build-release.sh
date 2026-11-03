#!/usr/bin/env bash
# build-release.sh - build the release ZIP (clean mode) with the checks that matter before it is published.
#
#   tools/image/build-release.sh --backup ~/s9-backups/s9-YYYYMMDD-HHMMSS \
#        --boot ~/s9-ubuntu2404-kernel/out/clean-.../boot-clean.img --out ~/s9-images
#   tools/image/build-release.sh --verify-zip ~/s9-images/s9-clean-STAMP.zip     # checks only, no build
#
# What it does, in order:
#   1. (--pull) fast-forwards the repository from origin.
#   2. runs the regression tests of tools/image/tests/ (GPU group, NetworkManager unmanaged list);
#   3. checks that the installer template has no known busybox traps (32-bit "[" comparison of sizes, "unzip -t");
#   4. runs build-image.sh in release mode (clean, first-boot account, unreferenced /opt pruned, Halium image checked);
#   5. verifies the ZIP it produced (CRC, installer text, no private marker in the name, sizes and hashes agree).
# It never uploads anything. Publishing the ZIP (GitHub release) is a manual step.
#
# build-image.sh needs root (the tree keeps numeric owners): the script re-runs itself with sudo when needed.
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
REPO=$(cd "$HERE/../.." && pwd)
HALIUM_SHA=527c53fd8e27957fe4046cd8588d689dec338e8abb6531af4602c2f235ca0944
BACKUP= BOOT= OUT= BOOT_SHA= VERIFY= PULL=0 SKIP_TESTS=0 EXTRA=()
say()  { printf '\n== %s\n' "$*"; }
info() { printf '   %s\n' "$*"; }
die()  { printf '\nERROR: %s\n' "$*" >&2; exit 1; }
usage() { sed -n '2,17p' "$0"; echo; echo "Options: --backup DIR --boot FILE --out DIR [--boot-sha256 HEX] [--pull] [--skip-tests] [--halium-sha256 HEX] [-- extra build-image.sh args]"; }
while [ $# -gt 0 ]; do
  case $1 in
    --backup) BACKUP=$2; shift 2;;
    --boot) BOOT=$2; shift 2;;
    --out) OUT=$2; shift 2;;
    --boot-sha256) BOOT_SHA=$2; shift 2;;
    --halium-sha256) HALIUM_SHA=$2; shift 2;;
    --verify-zip) VERIFY=$2; shift 2;;
    --pull) PULL=1; shift;;
    --skip-tests) SKIP_TESTS=1; shift;;
    -h|--help) usage; exit 0;;
    --) shift; EXTRA=("$@"); break;;
    *) die "unknown option: $1 (try --help)";;
  esac
done

# ---- verification of a finished ZIP (also usable on its own) -------------------------------------------------
verify_zip() {
  local T RC; T=$(mktemp -d "${TMPDIR:-/tmp}/s9-verify.XXXXXX")
  RC=0; verify_zip_in "$1" "$T" || RC=$?
  rm -rf "$T"; return "$RC"
}
verify_zip_in() {
  local Z=$1 T=$2 R=0
  [ -f "$Z" ] || die "ZIP not found: $Z"
  command -v unzip >/dev/null || die "missing tool: unzip"
  say "verifying $(basename "$Z")"
  case $(basename "$Z") in *PRIVATE*|*private*) info "FAIL: the name says PRIVATE: this is a private test build, do not publish"; R=1;; esac
  if unzip -tq "$Z" >"$T/unzip-t.txt" 2>&1; then info "ok   CRC of every member"; else info "FAIL: ZIP is corrupt: $(tail -1 "$T/unzip-t.txt")"; R=1; fi
  local UB=META-INF/com/google/android/update-binary
  unzip -p "$Z" "$UB" > "$T/ub" 2>/dev/null || { info "FAIL: no $UB"; return 1; }
  unzip -l "$Z" META-INF/com/google/android/updater-script payload/MANIFEST.txt payload/boot.img >/dev/null 2>&1 \
    && info "ok   updater-script, MANIFEST.txt and boot.img are present" || { info "FAIL: a required member is missing"; R=1; }
  # the installer must have its busybox fixes (3 Nov 2026) and none of the traps
  grep -q 'DATA_PART_SIZE >= RAW_SIZE' "$T/ub" && info "ok   installer compares userdata size inside \$(( ))" \
    || { info "FAIL: installer lacks the 64-bit size check (it would stop with 'userdata is too small' in TWRP's busybox)"; R=1; }
  if grep -nE '\[ +"?\$\{?(DATA_PART_SIZE|BOOT_PART_SIZE)\}?"? +-(ge|gt|le|lt|eq|ne)' "$T/ub" | grep -v 'BOOT_PART_SIZE" -ge "\$BOOT_SIZE"' | grep -q .; then
    info "FAIL: installer compares a partition size with [ -ge ] (32-bit in busybox)"; R=1; fi
  grep -qE 'unzip +-(t|tq|qt)( |$)' "$T/ub" && { info "FAIL: installer calls 'unzip -t' (TWRP's busybox unzip has no -t)"; R=1; } || info "ok   installer does not call 'unzip -t'"
  grep -q 'unzip -l "\$ZIPFILE"' "$T/ub" && info "ok   installer checks the ZIP with 'unzip -l'" || { info "FAIL: installer does not check the ZIP with unzip -l"; R=1; }
  if grep -qE '@[A-Z0-9_]+@' "$T/ub"; then info "FAIL: unreplaced @PLACEHOLDER@ in the installer"; R=1; else info "ok   no unreplaced placeholders"; fi
  sh -n "$T/ub" 2>/dev/null && info "ok   installer passes 'sh -n'" || { info "FAIL: installer has a syntax error"; R=1; }
  local V
  for V in BOOT_SIZE BOOT_SHA256 RAW_SIZE RAW_SHA256 PARTS; do
    grep -q "^$V=" "$T/ub" || { info "FAIL: $V not set in the installer"; R=1; }
  done
  local RAW_SIZE BOOT_SIZE BOOT_SHA PARTS
  RAW_SIZE=$(sed -n 's/^RAW_SIZE=//p' "$T/ub" | head -1 | tr -d '"'); BOOT_SIZE=$(sed -n 's/^BOOT_SIZE=//p' "$T/ub" | head -1 | tr -d '"')
  BOOT_SHA=$(sed -n 's/^BOOT_SHA256=//p' "$T/ub" | head -1 | tr -d '"'); PARTS=$(sed -n 's/^PARTS=//p' "$T/ub" | head -1 | tr -d '"')
  [ $((RAW_SIZE % 1048576)) = 0 ] && info "ok   root image size is a multiple of 1 MiB ($RAW_SIZE)" || { info "FAIL: RAW_SIZE not a multiple of 1 MiB"; R=1; }
  if [ "$(unzip -p "$Z" payload/boot.img | wc -c)" = "$BOOT_SIZE" ] && [ "$(unzip -p "$Z" payload/boot.img | sha256sum | cut -d' ' -f1)" = "$BOOT_SHA" ]; then
    info "ok   boot.img size and SHA-256 agree with the installer ($BOOT_SHA)"
  else info "FAIL: boot.img differs from what the installer expects"; R=1; fi
  local P
  for P in $PARTS; do unzip -l "$Z" "payload/$P" >/dev/null 2>&1 || { info "FAIL: part payload/$P missing"; R=1; }; done
  info "ok   $(echo $PARTS | wc -w) root image part(s) present"
  # never ship the author's data: the audit already ran at build time, this is a cheap second look at the text members
  unzip -p "$Z" payload/MANIFEST.txt | sed 's/^/     /'
  if [ -f "$Z.sha256" ]; then
    ( cd "$(dirname "$Z")" && sha256sum -c "$(basename "$Z").sha256" >/dev/null 2>&1 ) && info "ok   $(basename "$Z").sha256 matches" || { info "FAIL: the .sha256 file does not match"; R=1; }
  else info "note: no $(basename "$Z").sha256 next to the ZIP"; fi
  info "sha256 $(sha256sum "$Z" | cut -d' ' -f1)"
  [ "$R" = 0 ] && say "ZIP verification: ALL OK" || say "ZIP verification: PROBLEMS FOUND (see FAIL lines)"
  return "$R"
}

if [ -n "$VERIFY" ]; then verify_zip "$VERIFY"; exit $?; fi

# ---- build -----------------------------------------------------------------------------------------------------
[ -n "$BACKUP" ] && [ -n "$BOOT" ] && [ -n "$OUT" ] || { usage; die "need --backup DIR --boot FILE --out DIR (or --verify-zip FILE)"; }
[ -d "$BACKUP" ] || die "backup directory not found: $BACKUP"
[ -f "$BOOT" ] || die "boot image not found: $BOOT"

say "0/5 repository"
if [ "$PULL" = 1 ]; then git -C "$REPO" pull --ff-only; fi
if git -C "$REPO" rev-parse --git-dir >/dev/null 2>&1; then
  info "commit $(git -C "$REPO" log -1 --format='%h %s')"
  if [ -n "$(git -C "$REPO" status --porcelain --untracked-files=no)" ]; then info "note: the working tree has uncommitted changes; the ZIP is built from them"; fi
fi
if [ -n "$BOOT_SHA" ]; then
  [ "$(sha256sum "$BOOT" | cut -d' ' -f1)" = "$BOOT_SHA" ] || die "boot image SHA-256 differs from --boot-sha256"
  info "boot image SHA-256 matches --boot-sha256"
else info "boot image sha256 $(sha256sum "$BOOT" | cut -d' ' -f1)  (pass --boot-sha256 to have it checked)"; fi

say "1/5 regression tests"
if [ "$SKIP_TESTS" = 1 ]; then info "skipped (--skip-tests)"; else
  for T in "$HERE"/tests/test-*.sh; do
    info "$(basename "$T")"; bash "$T" >/tmp/s9-test.$$ 2>&1 || { cat /tmp/s9-test.$$; rm -f /tmp/s9-test.$$; die "$(basename "$T") failed: not building"; }
    tail -1 /tmp/s9-test.$$ | sed 's/^/     /'; rm -f /tmp/s9-test.$$
  done
fi

say "2/5 installer template"
TPL=$HERE/twrp/update-binary.in
grep -q 'DATA_PART_SIZE >= RAW_SIZE' "$TPL" || die "twrp/update-binary.in lacks the 64-bit size check"
grep -qE 'unzip +-(t|tq|qt)( |$)' "$TPL" && die "twrp/update-binary.in calls unzip -t"
grep -q 'unzip -l "\$ZIPFILE"' "$TPL" || die "twrp/update-binary.in lacks the unzip -l check"
info "ok"

say "3/5 build (build-image.sh, release mode; needs root)"
mkdir -p "$OUT"
ARGS=("$HERE/build-image.sh" --backup "$BACKUP" --boot "$BOOT" --out "$OUT" --mode clean --first-boot-account \
      --prune-opt-unreferenced --halium-sha256 "$HALIUM_SHA" "${EXTRA[@]}")
if [ "$(id -u)" = 0 ]; then bash "${ARGS[@]}"; else sudo bash "${ARGS[@]}"; fi

say "4/5 find the ZIP"
ZIP=$(ls -t "$OUT"/s9-clean-*.zip 2>/dev/null | grep -v PRIVATE | head -1 || true)
[ -n "$ZIP" ] || die "no s9-clean-*.zip in $OUT"
info "$ZIP"

say "5/5 verify"
verify_zip "$ZIP"
echo
echo "Next: flash it from TWRP (adb shell twrp sideload; adb sideload $ZIP) and check on the phone:"
echo "   id                              # must list android_graphics"
echo "   glxinfo -B | grep -i renderer   # must say FD630"
echo "   nmcli con show --active         # no 'Wired connection 1' on p2p0"
echo "Then upload $ZIP (and its .sha256) to the GitHub release, replacing the old ZIP."
