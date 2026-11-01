#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd -P)"
source "$HERE/lib/common.sh"
PROJ="$(project_root)"; REPORT="$PROJ/workdir/halium-graft/reports"; mkdir -p "$REPORT"
require_cmd adb
adb get-state >/dev/null

adb shell 'mount; echo ===; ls -l /dev/ion /dev/kgsl-3d0 /dev/binder /dev/hwbinder /dev/vndbinder 2>/dev/null || true' > "$REPORT/smg9600-mounts-and-nodes.txt"
adb shell 'getprop 2>/dev/null | grep -Ei "ro.product|ro.build|ro.vendor|ro.hardware|gralloc|hwc|egl|vndk|first_api" || true' > "$REPORT/smg9600-properties.txt"
adb shell '
for B in /vendor /system/vendor /odm /system /apex; do
  [ -d "$B" ] || continue
  find "$B" -type f 2>/dev/null | grep -Ei "/(hwcomposer|gralloc|mapper|allocator|composer|egl|libEGL|libGLES|libgui|libui|libsync|libion|libhardware|libhidl|libcutils|libutils|liblog|libbase|libbinder|libvndksupport)[^/]*\\.so$|/hw/.*(composer|gralloc|allocator|mapper).*\\.so$" || true
done
' | sort -u > "$REPORT/smg9600-graphics-libs.txt"
adb shell 'dmesg 2>/dev/null | grep -Ei "kgsl|ion|binder|hwc|gralloc|egl|display|sde|msm_drm|secdp|max77705|ccic" | tail -n 1200 || true' > "$REPORT/smg9600-graphics-dmesg.txt"
log "Probe salvo em $REPORT"
