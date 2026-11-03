#!/usr/bin/env bash
# build-zip.sh - pack tools/twrp/disabler/update-binary into the flashable TWRP ZIP.
#
# Usage: tools/twrp/disabler/build-zip.sh [OUTPUT.zip]
#
# The ZIP is reproducible: fixed time stamps and file modes, so the same update-binary always
# gives the same SHA-256. Needs only python3.
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
OUT=${1:-S9_G9600_disabler-and-encryption-removal.zip}
[ -f "$HERE/update-binary" ] || { echo "ERROR: $HERE/update-binary not found" >&2; exit 1; }
# the script is run by TWRP's busybox ash: catch syntax errors before they reach a phone
if command -v busybox >/dev/null; then busybox sh -n "$HERE/update-binary"; else sh -n "$HERE/update-binary"; fi
python3 -I - "$HERE/update-binary" "$OUT" <<'PY'
import sys, zipfile, hashlib
src, out = sys.argv[1], sys.argv[2]
z = zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED)
def add(name, data, mode):
    zi = zipfile.ZipInfo(name, date_time=(2026, 11, 1, 21, 0, 0))
    zi.external_attr = (0o100000 | mode) << 16
    zi.compress_type = zipfile.ZIP_DEFLATED
    z.writestr(zi, data)
add('META-INF/com/google/android/update-binary', open(src, 'rb').read(), 0o755)
add('META-INF/com/google/android/updater-script', b'# script-based update-binary: nothing here\n', 0o644)
z.close()
print(out)
print('sha256', hashlib.sha256(open(out, 'rb').read()).hexdigest())
PY
