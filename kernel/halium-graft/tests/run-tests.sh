#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd -P)"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT

# generator fixture
mkdir -p "$TMP/ref/overlay/system/etc"
cat > "$TMP/ref/deviceinfo" <<'E'
deviceinfo_name="Samsung Galaxy S9+"
deviceinfo_codename="samsung-star2qltechn"
deviceinfo_kernel_defconfig="star2qlte_chn_halium_defconfig halium.config"
E
cat > "$TMP/ref/overlay/system/etc/generic.conf" <<'E'
# generic
E
python3 "$HERE/01-generate-starqltechn.py" --reference "$TMP/ref" --output "$TMP/out" --map "$HERE/adaptation-map.tsv" --report-dir "$TMP/reports"
grep -q 'Samsung Galaxy S9"' "$TMP/out/deviceinfo"
grep -q 'samsung-starqltechn' "$TMP/out/deviceinfo"
grep -q 'starqlte_chn_halium_defconfig' "$TMP/out/deviceinfo"
[[ ! -s "$TMP/reports/unclassified-identifiers.txt" ]]

# unresolved must stop
rm -rf "$TMP/out" "$TMP/reports"; echo 'firmware=G9650ZHU9FVF2' >> "$TMP/ref/deviceinfo"
set +e
python3 "$HERE/01-generate-starqltechn.py" --reference "$TMP/ref" --output "$TMP/out" --map "$HERE/adaptation-map.tsv" --report-dir "$TMP/reports" >/dev/null 2>&1
rc=$?
set -e
[[ $rc -eq 3 ]]
grep -q 'G9650ZHU9FVF2' "$TMP/reports/unclassified-identifiers.txt"

# syntax
for f in "$HERE"/*.sh "$HERE"/lib/*.sh; do bash -n "$f"; done
python3 -m py_compile "$HERE/01-generate-starqltechn.py" "$HERE/04-build-graphics-manifest.py"
# forbidden desktop owners
! grep -RIE '(^|[ /])(xfwm4|xfdesktop|startxfce4)([ ;]|$)' "$(cd "$HERE/../.." && pwd -P)/rootfs-overlay/halium-graft" >/dev/null

echo 'ALL TESTS PASS'
