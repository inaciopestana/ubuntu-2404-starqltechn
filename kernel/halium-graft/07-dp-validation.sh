#!/usr/bin/env bash
set -euo pipefail
LOG=${1:-/var/log/s9-halium-dp.log}
exec >"$LOG" 2>&1
echo "===== DP VALIDATION $(date -Is 2>/dev/null || date) ====="
for i in $(seq 0 11); do
  echo "=== SAMPLE $i ==="
  for f in /sys/class/drm/card0-DP-1/status /sys/class/drm/card0-DP-1/enabled /sys/class/drm/card0-DP-1/modes; do echo "# $f"; cat "$f" 2>/dev/null || true; done
  dmesg | grep -Ei 'max77705|ccic|alternate|alt.?mode|vdm|secdp|displayport|drm.?dp|hpd|edid|aux' | tail -n 500
  sleep 5
done
