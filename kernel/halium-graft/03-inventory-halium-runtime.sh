#!/bin/bash
set -euo pipefail

MNT="${1:?uso: $0 /caminho/rootfs-v7}"
OUT="${2:-workdir/halium-graft/reports}"

MNT="$(readlink -f "$MNT")"
mkdir -p "$OUT"
OUT="$(readlink -f "$OUT")"

STATUS="$MNT/var/lib/dpkg/status"
INFO="$MNT/var/lib/dpkg/info"

[ -f "$STATUS" ] || {
    echo "ERRO: dpkg status ausente: $STATUS" >&2
    exit 1
}

REPORT="$OUT/halium-runtime-packages.txt"
OWNERS="$OUT/halium-runtime-owners.txt"
CONFIG="$OUT/halium-runtime-critical-config.txt"

: > "$REPORT"
: > "$OWNERS"
: > "$CONFIG"

package_version()
{
    pkg="$1"

    awk -v want="$pkg" '
        BEGIN {
            RS=""
            FS="\n"
        }

        {
            p=""
            v=""
            a=""

            for (i=1; i<=NF; i++) {
                if ($i ~ /^Package: /)
                    p=substr($i,10)

                if ($i ~ /^Version: /)
                    v=substr($i,10)

                if ($i ~ /^Architecture: /)
                    a=substr($i,15)
            }

            if (p == want) {
                print p "\t" v "\t" a
                exit
            }
        }
    ' "$STATUS"
}

owner_of()
{
    target="$1"

    for list in "$INFO"/*.list; do
        [ -f "$list" ] || continue

        if grep -Fxq "$target" "$list"; then
            base="$(basename "$list" .list)"

            # dpkg info pode usar:
            # package.list
            # package:arm64.list
            pkg="${base%%:*}"

            printf '%s\t%s\n' "$target" "$pkg"
        fi
    done
}

echo "===== OWNERS =====" >> "$OWNERS"

for f in \
    /usr/lib/aarch64-linux-gnu/mir1/server-platform/graphics-android2.so.16 \
    /usr/lib/aarch64-linux-gnu/libmir1server.so.53 \
    /usr/lib/aarch64-linux-gnu/libmir1al.so.3 \
    /usr/lib/aarch64-linux-gnu/libhybris-common.so.1.0.0 \
    /usr/lib/aarch64-linux-gnu/libhybris-hwcomposerwindow.so.1.0.0 \
    /usr/lib/aarch64-linux-gnu/libhybris/eglplatform_hwcomposer.so \
    /usr/libexec/Xwayland.lomiri \
    /usr/libexec/lxc-android-config/start-android-container \
    /var/lib/lxc/android/android-rootfs.img
do
    owner_of "$f" >> "$OWNERS"
done

echo "===== PACOTES DETECTADOS =====" >> "$REPORT"

awk -F '\t' 'NF >= 2 { print $2 }' "$OWNERS" |
    sort -u |
    while read -r pkg; do
        [ -n "$pkg" ] || continue
        package_version "$pkg"
    done |
    sort >> "$REPORT"

echo >> "$REPORT"
echo "===== TODOS OS PACOTES RELACIONADOS =====" >> "$REPORT"

awk '
BEGIN {
    RS=""
    FS="\n"
}

{
    p=""
    v=""
    a=""

    for (i=1; i<=NF; i++) {
        if ($i ~ /^Package: /)
            p=substr($i,10)

        if ($i ~ /^Version: /)
            v=substr($i,10)

        if ($i ~ /^Architecture: /)
            a=substr($i,15)
    }

    low=tolower(p)

    if (low ~ /(mir1|hybris|lxc-android|xwayland|qtmir)/ || low ~ /^lxc/)
        print p "\t" v "\t" a
}
' "$STATUS" |
sort >> "$REPORT"

{
    echo "===== ANDROID LXC CONFIG ====="
    cat "$MNT/var/lib/lxc/android/config" 2>/dev/null || true

    echo
    echo "===== PRE-START ====="
    cat "$MNT/var/lib/lxc/android/pre-start.sh" 2>/dev/null || true

    echo
    echo "===== MOUNT.SH ====="
    cat "$MNT/var/lib/lxc/android/mount.sh" 2>/dev/null || true

    echo
    echo "===== DISABLE SURFACEFLINGER ====="
    cat \
      "$MNT/var/lib/lxc/android/pre-start.d/30-no-surface-flinger" \
      2>/dev/null || true

    echo
    echo "===== LXC ANDROID CONFIG SERVICE ====="
    cat \
      "$MNT/usr/lib/systemd/system/lxc-android-config.service" \
      2>/dev/null || true

    echo
    echo "===== MOUNT ANDROID SYSTEM ====="
    cat \
      "$MNT/usr/lib/systemd/system/mount-android-system.service" \
      2>/dev/null || true

    echo
    echo "===== MOUNT ANDROID PARTITIONS ====="
    cat \
      "$MNT/usr/lib/systemd/system/mount-android-partitions.service" \
      2>/dev/null || true

    echo
    echo "===== MOUNT HALIUM OVERLAY ====="
    cat \
      "$MNT/usr/lib/systemd/system/mount-halium-overlay.service" \
      2>/dev/null || true

    echo
    echo "===== GPU PATH ====="
    cat \
      "$MNT/opt/halium-overlay/etc/default/lsc-wrapper.d/"*gpu-path \
      2>/dev/null || true

    echo
    echo "===== GPU PERMISSIONS ====="
    cat \
      "$MNT/opt/halium-overlay/usr/libexec/"*gpu-permissions \
      2>/dev/null || true

    echo
    echo "===== GPU SERVICE ====="
    cat \
      "$MNT/opt/halium-overlay/etc/systemd/system/"*gpu-permissions.service \
      2>/dev/null || true

    echo
    echo "===== LOMIRI/MIR WRAPPER ====="
    cat \
      "$MNT/opt/halium-overlay/usr/libexec/lomiri-systemd-wrapper" \
      2>/dev/null || true

} > "$CONFIG"

echo "[s9-halium] Gerados:"
echo "  $REPORT"
echo "  $OWNERS"
echo "  $CONFIG"
