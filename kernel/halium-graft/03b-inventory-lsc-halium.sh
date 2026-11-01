#!/bin/bash
set -euo pipefail

MNT="${1:?uso: $0 /caminho/mnt-v7 [saida]}"
OUT="${2:-workdir/halium-graft/reports}"

MNT="$(readlink -f "$MNT")"
mkdir -p "$OUT"
OUT="$(readlink -f "$OUT")"

STATUS="$MNT/var/lib/dpkg/status"
INFO="$MNT/var/lib/dpkg/info"
REPORT="$OUT/halium-lsc-integration.txt"

[ -f "$STATUS" ] || {
    echo "ERRO: rootfs V7 inválida: $MNT" >&2
    exit 1
}

: > "$REPORT"

show_file()
{
    rel="$1"

    {
        echo
        echo "============================================================"
        echo "FILE: $rel"
        echo "============================================================"

        if [ -f "$MNT$rel" ]; then
            cat "$MNT$rel"
        elif [ -L "$MNT$rel" ]; then
            echo "SYMLINK -> $(readlink "$MNT$rel")"
        else
            echo "[AUSENTE]"
        fi
    } >> "$REPORT"
}

owner_of()
{
    rel="$1"

    for list in "$INFO"/*.list; do
        [ -f "$list" ] || continue

        if grep -Fxq "$rel" "$list"; then
            basename "$list" .list
        fi
    done
}

package_paragraph()
{
    pkg="$1"

    awk -v want="$pkg" '
        BEGIN {
            RS=""
            FS="\n"
        }

        {
            found=0

            for (i=1; i<=NF; i++) {
                if ($i == "Package: " want) {
                    found=1
                    break
                }
            }

            if (found) {
                print $0
                print ""
                exit
            }
        }
    ' "$STATUS"
}

{
    echo "===== LSC / MIR / HALIUM FINAL INVENTORY ====="

    echo
    echo "===== LSC BINARIES ====="

    for rel in \
        /usr/sbin/lomiri-system-compositor \
        /usr/sbin/lomiri-system-compositor.sleep \
        /usr/bin/lomiri \
        /usr/libexec/Xwayland.lomiri \
        /usr/lib/aarch64-linux-gnu/mir1/server-platform/graphics-android2.so.16
    do
        if [ -e "$MNT$rel" ]; then
            ls -l "$MNT$rel"

            echo -n "SHA256 "
            sha256sum "$MNT$rel"

            echo -n "OWNER  "
            owner_of "$rel" | tr '\n' ' '
            echo

            echo "NEEDED:"
            readelf -d "$MNT$rel" 2>/dev/null |
                grep '(NEEDED)' || true

            echo
        fi
    done

    echo
    echo "===== LSC REFERENCES ====="

    grep -RInsE \
        'lomiri-system-compositor|MIR_SERVER_HOST_SOCKET|/run/mir_socket|lsc-wrapper' \
        "$MNT/etc" \
        "$MNT/usr/lib/systemd" \
        "$MNT/lib/systemd" \
        "$MNT/usr/share/lightdm" \
        2>/dev/null |
        head -1200 || true

    echo
    echo "===== SYSTEMD/INIT FILES WITH LSC ====="

    find \
        "$MNT/etc" \
        "$MNT/usr/lib/systemd" \
        "$MNT/lib/systemd" \
        \( -type f -o -type l \) \
        2>/dev/null |
        grep -Ei \
        'lomiri-system-compositor|lightdm|lsc-wrapper' |
        sort || true

    echo
    echo "===== LSC DEFAULT DIRECTORY ====="

    find "$MNT/etc/default/lsc-wrapper.d" \
        -maxdepth 1 \
        \( -type f -o -type l \) \
        -printf '%y %p -> %l\n' \
        2>/dev/null |
        sort || true

    echo
    echo "===== LIBTLS-PADDING ====="

    while IFS= read -r path; do
        [ -n "$path" ] || continue

        rel="${path#$MNT}"

        ls -l "$path"
        sha256sum "$path"

        echo -n "OWNER: "
        owner_of "$rel" | tr '\n' ' '
        echo

        readelf -d "$path" 2>/dev/null |
            grep '(NEEDED)' || true

        echo
    done < <(
        find "$MNT/usr/lib" "$MNT/lib" \
            -name 'libtls-padding.so*' \
            -print 2>/dev/null |
        sort
    )

    echo
    echo "===== GPU PLUGIN BASE vs OVERLAY ====="

    BASE="$MNT/usr/lib/aarch64-linux-gnu/mir1/server-platform/graphics-android2.so.16"
    OVER="$MNT/opt/halium-overlay/usr/lib/aarch64-linux-gnu/mir1/server-platform/graphics-android2.so.16"

    if [ -f "$BASE" ]; then
        echo "BASE:"
        sha256sum "$BASE"
        ls -l "$BASE"
    fi

    if [ -f "$OVER" ]; then
        echo "OVERLAY:"
        sha256sum "$OVER"
        ls -l "$OVER"
    fi

    if [ -f "$BASE" ] && [ -f "$OVER" ]; then
        if cmp -s "$BASE" "$OVER"; then
            echo "RESULTADO: IDENTICOS"
        else
            echo "RESULTADO: DIFERENTES"
        fi
    fi

    echo
    echo "===== USERS / GROUPS IMPORTANTES ====="

    grep -E \
        '^(phablet|lightdm|root):' \
        "$MNT/etc/passwd" 2>/dev/null || true

    echo
    echo "--- GID 1003 / graphics / video / render ---"

    awk -F: \
        '$3 == 1003 || $1 ~ /graphics|video|render/ {print}' \
        "$MNT/etc/group" 2>/dev/null || true

    echo
    echo "--- grupos contendo phablet ---"

    grep -E \
        '(^|,)phablet(,|$)' \
        "$MNT/etc/group" 2>/dev/null || true

    echo
    echo "===== ANDROID ROOTFS IMAGE ====="

    IMG="$MNT/var/lib/lxc/android/android-rootfs.img"

    if [ -f "$IMG" ]; then
        ls -lh "$IMG"
        file "$IMG"
        blkid "$IMG" 2>/dev/null || true
        sha256sum "$IMG"
    fi

    echo
    echo "===== APT SOURCES ====="

    find "$MNT/etc/apt" \
        \( -name '*.list' -o -name '*.sources' \) \
        -type f \
        -print 2>/dev/null |
        sort |
        while read -r f; do
            echo
            echo "--- ${f#$MNT} ---"
            cat "$f"
        done

    echo
    echo "===== KEY PACKAGE METADATA ====="

    for pkg in \
        lomiri-system-compositor \
        lomiri \
        lxc-android-config \
        libhybris \
        libhybris-common1 \
        mir1-platform-graphics-android2-16 \
        libmir1server53 \
        libmir1al3
    do
        echo
        echo "--- PACKAGE: $pkg ---"
        package_paragraph "$pkg"
    done

} >> "$REPORT"


for rel in \
    /usr/libexec/lxc-android-config/start-android-container \
    /usr/libexec/lxc-android-config/mount-android-system \
    /usr/libexec/lxc-android-config/mount-android-partitions \
    /usr/libexec/lxc-android-config/mount-halium-overlay \
    /usr/lib/lxc-android-config/common.sh \
    /usr/lib/lxc-android-config/lxc-android-ready \
    /var/lib/lxc/android/config \
    /var/lib/lxc/android/pre-start.sh \
    /var/lib/lxc/android/mount.sh \
    /var/lib/lxc/android/post-stop.sh
do
    show_file "$rel"
done


for rel in \
    /etc/default/lomiri-system-compositor \
    /etc/default/lsc-wrapper \
    /usr/bin/lsc-wrapper \
    /usr/libexec/lsc-wrapper \
    /lib/systemd/system/lomiri-system-compositor.service \
    /usr/lib/systemd/system/lomiri-system-compositor.service \
    /etc/init/lomiri-system-compositor.conf
do
    if [ -e "$MNT$rel" ] || [ -L "$MNT$rel" ]; then
        show_file "$rel"
    fi
done


if [ -d "$MNT/etc/default/lsc-wrapper.d" ]; then
    while IFS= read -r f; do
        rel="${f#$MNT}"
        show_file "$rel"
    done < <(
        find "$MNT/etc/default/lsc-wrapper.d" \
            -maxdepth 1 \
            -type f \
            -print |
        sort
    )
fi

echo "[s9-halium] Gerado:"
echo "  $REPORT"
echo
wc -l "$REPORT"
ls -lh "$REPORT"
