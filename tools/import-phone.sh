#!/usr/bin/env bash
# import-phone.sh - maintainer tool.
# Turns the output of tools/collect-phone.sh (extracted tarball) into the
# `system/` and `userland/` trees of this repository:
#   * drops backups, generated files, distro defaults and one-off test helpers
#   * replaces the maintainer's account with @S9_USER@ / @S9_HOME@ placeholders
#   * records every file that still contains a placeholder in
#     system/TEMPLATES.txt / userland/TEMPLATES.txt (the installer renders them)
#
#   mkdir /tmp/pe && tar xzf phone-export.tgz -C /tmp/pe
#   S9_REAL_USER=<account on the phone> tools/import-phone.sh /tmp/pe .
#
# Files that need hand-written replacements (the flattened s9-miral-nested unit
# and its wrapper) are NOT produced here; see system/etc/systemd/system/.
set -euo pipefail
SRC=$(realpath "${1:?usage: import-phone.sh EXTRACTED_DIR REPO_DIR}")
DST=$(realpath "${2:?usage: import-phone.sh EXTRACTED_DIR REPO_DIR}")
REAL=${S9_REAL_USER:?set S9_REAL_USER to the account name used on the phone}
[ -d "$SRC/etc" ] && [ -d "$SRC/usr" ] || { echo "not an extracted collector tree: $SRC" >&2; exit 1; }

# never exported: backups, disabled files, generated caches, runtime state,
# distro defaults we did not change, one-off diagnostics
skip() {
  case "$1" in
    *.backup*|*.bak*|*.disabled-*|*.task12*|*.orig|*~|*mimeinfo.cache) return 0;;
    etc/lightdm/lightdm-gtk-greeter.conf|etc/lightdm/users.conf) return 0;;
    etc/pulse/client.conf|etc/pulse/daemon.conf|etc/pulse/default.pa|etc/pulse/system.pa) return 0;;
    etc/NetworkManager/conf.d/default-wifi-powersave-on.conf) return 0;;
    etc/s9-phone.conf|etc/s9-lmk.origadj) return 0;;                # runtime state
    etc/systemd/system/s9-miral-nested.service*) return 0;;          # flattened by hand
    usr/local/sbin/s9-miral-nested|usr/local/sbin/s9-miral-nested-v8-task12p-clean) return 0;;
    usr/local/sbin/s9-ofono-test|usr/local/sbin/s9-ofono-data-test|usr/local/sbin/s9-ofono-data-debug) return 0;;
    root/*) return 0;;                                              # collector metadata
  esac
  return 1
}

where() {  # which tree does a path belong to?
  case "$1" in
    usr/local/bin/*|usr/local/libexec/*|usr/local/lib/*|usr/local/share/*|usr/share/applications/*) echo userland;;
    *) echo system;;
  esac
}

n=0
( cd "$SRC" && find . -type f | sed 's#^\./##' | sort ) | while read -r rel; do
  skip "$rel" && continue
  t=$(where "$rel")
  mkdir -p "$DST/$t/$(dirname "$rel")"
  sed -E "s#/home/$REAL#@S9_HOME@#g; s#$REAL#@S9_USER@#g; s#(UID|UID_NUM) ?= ?1000\b#\1=@S9_UID@#" "$SRC/$rel" > "$DST/$t/$rel"
  [ -x "$SRC/$rel" ] && chmod +x "$DST/$t/$rel"
  n=$((n+1))
done

for t in system userland; do
  ( cd "$DST/$t" && grep -rIl '@S9_[A-Z]*@' . 2>/dev/null | sed 's#^\./##' | sort ) > "$DST/$t/TEMPLATES.txt" || true
  echo "$t: $(find "$DST/$t" -type f ! -name TEMPLATES.txt | wc -l) files, $(wc -l < "$DST/$t/TEMPLATES.txt") templates"
done
