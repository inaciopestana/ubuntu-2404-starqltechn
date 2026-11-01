#!/usr/bin/env bash
# collect-phone.sh - maintainer tool, runs ON THE PHONE (as root).
# Packs the S9-specific system files (scripts, systemd units, udev/sudoers/
# polkit rules, configs) into one tarball so they can be reviewed, scrubbed and
# published. READ-ONLY with respect to the system: it only reads files and
# writes /root/phone-export.tgz and /root/phone-export.list.
#
# It is an allowlist by location + a deny list by name (backups, old rollback
# helpers, binaries, logs, anything that looks like a credential). Nothing is
# uploaded anywhere. Review the list before publishing.
set -u
OUTT=${1:-/root/phone-export.tgz}
LIST=${OUTT%.tgz}.list
SKIP=${OUTT%.tgz}.skipped
: > "$LIST"; : > "$SKIP"
MAXSZ=$((1024*1024))

# basename patterns that are never exported
deny() {
  case "$(basename "$1")" in
    *.bak|*.bak.*|*.bak-*|*.before-*|*.pre-*|*.WORKING*|*.orig|*.rej|*~|*.pyc|*.log|*.core|*.so|*.so.*|*.tgz|*.tar|*.tar.*|*.img|*.zip) return 0;;
    *rollback*|*-activate|s9-v[0-9]*|s9-mirlib-v*|s9-task[0-9]*|s9-miral-nested-v[0-9]*) \
        [ "$(basename "$1")" = "s9-miral-nested-v8-task12p-clean" ] && return 1; return 0;;
    *psk*|*passw*|*secret*|*credential*|*.key|*.pem|*.p12|*token*|*shadow*|*wpa_supplicant*|*.nmconnection) return 0;;
  esac
  return 1
}

want() {  # $1=file
  f=$1
  [ -f "$f" ] && [ ! -L "$f" ] || return 1
  if deny "$f"; then echo "denied-name  $f" >> "$SKIP"; return 1; fi
  sz=$(stat -c %s "$f"); [ "$sz" -le "$MAXSZ" ] || { echo "too-big      $f ($sz)" >> "$SKIP"; return 1; }
  grep -Iq . "$f" 2>/dev/null || [ "$sz" -eq 0 ] || { echo "binary       $f" >> "$SKIP"; return 1; }
  echo "$f" >> "$LIST"
}

# ---- locations -----------------------------------------------------------
for d in /usr/local/sbin /usr/local/bin /usr/local/libexec; do
  for f in "$d"/s9-* "$d"/*s9*; do want "$f"; done
done
find /usr/local/lib /usr/local/share /usr/local/libexec -path '*s9*' -type f 2>/dev/null | sort -u | while read -r f; do want "$f"; done

find /etc/systemd/system -maxdepth 3 \( -name 's9-*' -o -path '*/s9-*.d/*' -o -name '*s9*.conf' \) \
  \( -type f -o -type l \) 2>/dev/null | sort -u | while read -r f; do
  if [ -L "$f" ]; then echo "symlink      $f -> $(readlink "$f")" >> "$SKIP"; else want "$f"; fi
done
find /etc/systemd/user /usr/lib/systemd/user -maxdepth 2 -name '*s9*' -type f 2>/dev/null | while read -r f; do want "$f"; done

for f in /etc/udev/rules.d/*s9* /etc/sudoers.d/s9-* /etc/polkit-1/rules.d/*s9* /etc/polkit-1/localauthority/*/*s9* \
         /usr/share/polkit-1/rules.d/*s9* /etc/s9-* /etc/logrotate.d/s9-* /etc/sysctl.d/*s9* /etc/tmpfiles.d/*s9* \
         /etc/modprobe.d/*s9* /etc/modules-load.d/*s9* /etc/xdg/autostart/*s9* /etc/xdg/xfce4/*s9* \
         /usr/share/applications/*s9* /usr/local/share/applications/*; do want "$f"; done
find /etc/default/lsc-wrapper.d /etc/pulse /etc/dconf /etc/lightdm /etc/NetworkManager/conf.d /etc/NetworkManager/dispatcher.d \
     -maxdepth 2 -type f \( -name '*s9*' -o -name '*.conf' -o -name '*.pa' \) 2>/dev/null | while read -r f; do
  case "$f" in /etc/NetworkManager/system-connections/*) continue;; esac; want "$f"; done

# ---- meta (no secrets) -----------------------------------------------------
M=/root/phone-export.meta; rm -rf "$M"; mkdir -p "$M"
{ . /etc/os-release; echo "$PRETTY_NAME"; uname -r; dpkg --print-architecture; } > "$M/system.txt"
apt-mark showmanual 2>/dev/null | sort > "$M/apt-manual.txt"
dpkg-query -W -f='${Package}\t${Version}\n' 2>/dev/null | sort > "$M/dpkg-versions.txt"
systemctl list-unit-files --no-legend 2>/dev/null | awk '$1 ~ /^s9-|^lxc-android|^ofono|^bluetooth|^pulse|^NetworkManager|^lightdm|^getty/ {print $1, $2}' > "$M/unit-states.txt"
ls -l --time-style=+%F /opt 2>/dev/null | awk 'NR>1{print $6, $7}' > "$M/opt-listing.txt"
id -Gn "$(getent passwd 1000 | cut -d: -f1)" 2>/dev/null | tr ' ' '\n' | sort > "$M/user1000-groups.txt"
for u in $(ls /etc/systemd/system | grep -E '^s9-.*\.service$'); do
  printf '%s\t%s\n' "$u" "$(systemctl show -p User --value "$u" 2>/dev/null)"; done > "$M/unit-users.txt"
find "$M" -type f >> "$LIST"

sort -u "$LIST" -o "$LIST"
tar czf "$OUTT" --ignore-failed-read -T "$LIST" 2>/dev/null
echo "files: $(wc -l < "$LIST")   skipped: $(wc -l < "$SKIP")   tarball: $(du -h "$OUTT" | cut -f1)" >&2
echo "list:    $LIST" >&2
echo "skipped: $SKIP" >&2
