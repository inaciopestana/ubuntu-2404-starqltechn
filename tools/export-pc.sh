#!/usr/bin/env bash
# export-pc.sh - maintainer tool.
# Builds the PC-side part of the public repository from a local working tree,
# using an ALLOWLIST (nothing is copied unless it is named here) and rewriting
# absolute paths. Run it, review the output, then run tools/scan-privacy.sh.
#
#   S9_WORK=~/s9-ubuntu2404-kernel S9_MIR_PKG=~/s9-mir1-src \
#   S9_ANDROID2=~/s9-ubuntu2404-kernel/workdir/mir-android2-platform \
#       tools/export-pc.sh /tmp/s9-export
#
# Requires: bash, tar, diff, patch, git, sha256sum.
set -euo pipefail

OUT=$(realpath -m "${1:?usage: export-pc.sh OUTDIR}")
WORK=${S9_WORK:-$HOME/s9-ubuntu2404-kernel}
MIR_PKG=${S9_MIR_PKG:-$HOME/s9-mir1-src}
ANDROID2=${S9_ANDROID2:-$WORK/workdir/mir-android2-platform}
MP=$WORK/workdir/mir-patch
MIR_BUILD=$MP/arm64-build-rootfs/build/mir1
A2_BUILD=$MP/arm64-build-rootfs/build/mir-android2-task12p
SHELL_SRC=${S9_SHELL_SRC:-$MP/output-alttab-v40/s9_miral_shell_v40al.cpp}

die() { echo "ERROR: $*" >&2; exit 1; }
for p in "$MP" "$MIR_PKG/debian/patches" "$MIR_BUILD" "$A2_BUILD" "$ANDROID2/.git" "$SHELL_SRC"; do
  [ -e "$p" ] || die "not found: $p"
done
[ -e "$OUT" ] && [ -n "$(ls -A "$OUT" 2>/dev/null)" ] && die "$OUT is not empty"
mkdir -p "$OUT"
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT

# Strip timestamps from "---/+++" headers so the patches are reproducible and
# carry no local paths.
strip_hdr() { sed -E 's/^((---|\+\+\+) [^[:space:]]+)[[:space:]].*$/\1/'; }

# Files that are build products, backups or generated -> never part of a patch.
DIFF_EXCLUDES=(-x .pc -x .git -x debian -x 'obj-*' -x '*.o' -x '*.orig' -x '*.rej'
  -x '*.pre-*' -x '*.before-*' -x '*.backup*' -x '*.bak*' -x '*.WORKING*'
  -x '*.task12*' -x '*.v23-before*' -x '__pycache__' -x version.h
  -x mir_perf_framework_setup.py -x task12p-backup)

# ---------------------------------------------------------------- Mir 1.8.3
echo "[mir] rebuilding pristine UBports source (orig tarball + debian/patches series)"
ORIG=$MP/mir_1.8.3.orig.tar.gz
tar xzf "$ORIG" -C "$T"; mv "$T/mir-1.8.3" "$T/a"
SERIES=$(grep -vE '^[[:space:]]*(#|$)' "$MIR_PKG/debian/patches/series")
for p in $SERIES; do
  ( cd "$T/a" && patch -p1 -s --no-backup-if-mismatch < "$MIR_PKG/debian/patches/$p" ) \
    || die "series patch failed: $p"
done
mkdir -p "$OUT/mir/patches"
ln -s "$MIR_BUILD" "$T/b"
# symbols.map carries the GCC15/protobuf fix, which ships as its own patch.
( cd "$T" && diff -ruN "${DIFF_EXCLUDES[@]}" -x symbols.map a b || true ) \
  | strip_hdr > "$OUT/mir/patches/0002-s9-mir-1.8.3-cumulative.patch"
cp "$MP/compat-protobuf-gcc15.patch" "$T/compat.patch"
strip_hdr < "$T/compat.patch" | sed -E 's#(/[^ ]*)?/(mir-source|mir1)/#a/#g' \
  > "$OUT/mir/patches/0001-compat-protobuf-gcc15.patch"
{
  echo "base: mir_1.8.3.orig.tar.gz sha256 $(sha256sum "$ORIG" | cut -d' ' -f1)"
  echo "ubports packaging commit: $(git -C "$MIR_PKG" rev-parse HEAD)"
  echo "debian/patches series applied before the S9 patches:"
  echo "$SERIES" | sed 's/^/  /'
} > "$OUT/mir/BASE.txt"
echo "[mir] verifying: pristine + patch == build tree"
cp -a "$T/a" "$T/chk"
( cd "$T/chk" && patch -p1 -s < "$OUT/mir/patches/0002-s9-mir-1.8.3-cumulative.patch" ) || die "cumulative patch does not apply"
if diff -rq "${DIFF_EXCLUDES[@]}" -x symbols.map -x examples "$T/chk" "$MIR_BUILD" >"$T/verify.txt" 2>&1; then
  echo "[mir]   OK: reproduces the build tree"
else
  echo "[mir]   WARNING: differences remain:"; head -20 "$T/verify.txt"
fi

# ------------------------------------------------ Mir android2 platform (GPU)
echo "[platform] diff upstream HEAD -> deployed task12p tree"
mkdir -p "$OUT/platform/patches" "$T/pa"
git -C "$ANDROID2" archive HEAD | tar x -C "$T/pa"
ln -s "$A2_BUILD" "$T/pb"
( cd "$T" && diff -ruN "${DIFF_EXCLUDES[@]}" -x '*.bak' pa pb || true ) \
  | strip_hdr | sed -E 's#^(---|\+\+\+) pa/#\1 a/#; s#^(---|\+\+\+) pb/#\1 b/#; s#^diff .*#&#' \
  > "$OUT/platform/patches/0001-s9-android2-platform.patch"
{
  echo "upstream: $(git -C "$ANDROID2" remote get-url origin)"
  echo "base commit: $(git -C "$ANDROID2" rev-parse HEAD)"
} > "$OUT/platform/BASE.txt"

# ------------------------------------------------------------------ Xwayland
echo "[xwayland] copying diff"
mkdir -p "$OUT/xwayland"
cp "$MP/output-xwayland-24.1.6-lfdevs/xwayland-24.1.6-lfdevs-s9.diff" "$OUT/xwayland/"

# --------------------------------------------------------------------- shell
echo "[shell] copying current shell source"
mkdir -p "$OUT/shell"
cp "$SHELL_SRC" "$OUT/shell/s9_miral_shell.cpp"
cp "$MIR_BUILD/examples/s9-miral-shell/CMakeLists.txt" "$OUT/shell/CMakeLists.txt"

# -------------------------------------------------- kernel / Halium (allowlist)
echo "[kernel] copying allowlisted files"
mkdir -p "$OUT/kernel/patches" "$OUT/kernel/scripts" "$OUT/kernel/halium-graft"
cp "$WORK/deviceinfo"                      "$OUT/kernel/deviceinfo"
cp "$WORK/kernel-config/halium.config"     "$OUT/kernel/halium.config"
# the kernel patches are maintained in the repository (kernel/patches/), regenerated from `git diff` of the kernel tree;
# they are no longer copied from the work directory.
for f in s9-kbuild5.sh s9-kpatch5.sh s9-flash-boot5.sh; do cp "$WORK/scripts/$f" "$OUT/kernel/scripts/"; done
cp "$WORK/check-ubuntu2404-config.sh" "$WORK/build-rootfs-stage1.sh" "$OUT/kernel/scripts/"
( cd "$WORK/tools/halium-graft" && tar cf - --exclude=__pycache__ --exclude='*.bak*' --exclude='*.pyc' . ) \
  | tar xf - -C "$OUT/kernel/halium-graft"
[ -d "$WORK/rootfs-overlay" ] && cp -a "$WORK/rootfs-overlay" "$OUT/kernel/rootfs-overlay"

# --------------------------------------------------- generic path scrubbing
# Replace the maintainer's home directory in every text file we just wrote.
echo "[scrub] rewriting absolute home paths"
find "$OUT" -type f ! -name '*.so*' -print0 | while IFS= read -r -d '' f; do
  if grep -Iq . "$f" 2>/dev/null; then
    sed -i -E 's#/home/[A-Za-z0-9._-]+/s9-ubuntu2404-kernel/workdir/mir-patch#$S9_WORK/workdir/mir-patch#g;
               s#/home/[A-Za-z0-9._-]+/s9-ubuntu2404-kernel#$S9_WORK#g;
               s#/home/[A-Za-z0-9._-]+/#/home/$S9_USER/#g' "$f"
  fi
done

( cd "$OUT" && find . -type f | sort | xargs sha256sum ) > "$T/manifest.txt"
mv "$T/manifest.txt" "$OUT/MANIFEST.sha256"
echo "done: $(find "$OUT" -type f | wc -l) files, $(du -sh "$OUT" | cut -f1)"
