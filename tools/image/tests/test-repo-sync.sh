#!/bin/bash
# Regression test: files listed in tools/image/repo-sync.list must (1) exist in the repository and (2) end up in the image tree
# with the repository's content, root owner and the right mode, replacing the older copy that came from the phone backup.
#   bash tools/image/tests/test-repo-sync.sh
set -u
if [ "$(id -u)" != 0 ]; then
  # a user namespace is enough, but Ubuntu 24.04+ often forbids it for normal users (AppArmor): then use sudo
  if unshare -r true 2>/dev/null; then exec unshare -r bash "$0" "$@"; fi
  exec sudo bash "$0" "$@"
fi
HERE="$(cd "$(dirname "$0")/.." && pwd)"; REPO="$(cd "$HERE/../.." && pwd)"
AUDIT="$HERE/audit-tree.py"; LIST="$HERE/repo-sync.list"
WORK="$(mktemp -d)"; trap 'rm -rf "$WORK"' EXIT
FAIL=0
ok()  { echo "   [ok]   $*"; }
bad() { echo "   [FAIL] $*"; FAIL=1; }

echo "== 1. every listed file exists and starts with userland/ or system/"
N=0; : > "$WORK/rels"
while IFS= read -r P || [ -n "$P" ]; do
  case $P in ''|'#'*) continue;; esac
  case $P in userland/*) R=${P#userland/};; system/*) R=${P#system/};; *) bad "$P: must start with userland/ or system/"; continue;; esac
  [ -f "$REPO/$P" ] && { N=$((N+1)); echo "$P $R" >> "$WORK/rels"; } || bad "$P not found in the repository"
done < "$LIST"
[ "$N" -gt 0 ] && ok "$N file(s) listed" || bad "the list is empty"

echo "== 2. the scrub installs them over an older copy"
T="$WORK/t"; STAGE="$WORK/stage"
mkdir -p "$T"/{etc/udev/rules.d,var/lib/dpkg/info,var/log,var/lib/dbus,usr/local/sbin,usr/local/bin,opt,home/oldname,root,media,mnt}
printf 'root:x:0:0:root:/root:/bin/bash\noldname:x:1000:1000:oldname,,,:/home/oldname:/bin/bash\n' > "$T/etc/passwd"
printf 'root:x:0:\nsudo:x:27:oldname\noldname:x:1000:\n' > "$T/etc/group"; printf 'root:*::\noldname:!::\n' > "$T/etc/gshadow"
printf 'root:!:19000:0:99999:7:::\noldname:$6$s$aaaa:19000:0:99999:7:::\n' > "$T/etc/shadow"
printf 'Package: bash\nStatus: install ok installed\n\n' > "$T/var/lib/dpkg/status"; : > "$T/var/lib/dpkg/info/bash.list"
echo s9 > "$T/etc/hostname"; echo abc > "$T/etc/machine-id"
while read -r P R; do
  mkdir -p "$(dirname "$T/$R")" "$(dirname "$STAGE/$R")"
  echo "OLD CONTENT FROM THE BACKUP" > "$T/$R"; chmod 600 "$T/$R"
  install -D -m 644 "$REPO/$P" "$STAGE/$R"       # same staging as build-image.sh
done < "$WORK/rels"
python3 -I "$AUDIT" scrub "$T" --defer-account --old-user oldname --hostname s9 --overlay "$STAGE" > "$WORK/scrub.log" 2>&1 || { cat "$WORK/scrub.log"; bad "scrub failed"; }
while read -r P R; do
  if cmp -s "$REPO/$P" "$T/$R"; then
    M=$(stat -c %a "$T/$R"); O=$(stat -c %u:%g "$T/$R")
    case $R in usr/local/bin/*|usr/local/sbin/*) W=755;; *) W=644;; esac
    [ "$M" = "$W" ] && [ "$O" = 0:0 ] && ok "$R ($M, root)" || bad "$R has mode $M owner $O, wanted $W 0:0"
  else bad "$R differs from $P (the old copy survived?)"; fi
done < "$WORK/rels"

echo
[ "$FAIL" = 0 ] && echo "ALL OK" || echo "FAILED"
exit "$FAIL"
