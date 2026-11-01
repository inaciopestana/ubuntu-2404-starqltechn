#!/bin/bash
for f in /sys/devices/system/cpu/cpu[0-9]*/cpufreq/scaling_governor; do
  [ "$(cat "$f" 2>/dev/null)" = performance ] || echo performance > "$f" 2>/dev/null
done
