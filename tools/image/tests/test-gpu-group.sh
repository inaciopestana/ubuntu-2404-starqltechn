#!/bin/bash
# Regression test: the clean image must keep the group that owns /dev/kgsl-3d0 and /dev/ion (android_graphics, GID 1003)
# and the account the first-boot wizard renames must be a member of it. Without this the GPU is root-only and
# glxinfo/glmark2 fail with "failed to create drisw screen".
#
# Builds a small synthetic root tree that mimics the author's phone, runs `audit-tree.py scrub` and `audit` on it and
# checks the result. Needs root (the scrub chowns files); as a normal user it re-runs itself in a user namespace, or with sudo when that is not allowed.
#   bash tools/image/tests/test-gpu-group.sh
set -u
if [ "$(id -u)" != 0 ]; then
  # a user namespace is enough, but Ubuntu 24.04+ often forbids it for normal users (AppArmor): then use sudo
  if unshare -r true 2>/dev/null; then exec unshare -r bash "$0" "$@"; fi
  exec sudo bash "$0" "$@"
fi
HERE="$(cd "$(dirname "$0")/.." && pwd)"
AUDIT="$HERE/audit-tree.py"
WORK="$(mktemp -d)"; trap 'rm -rf "$WORK"' EXIT
FAIL=0
ok()   { echo "   [ok]   $*"; }
bad()  { echo "   [FAIL] $*"; FAIL=1; }

mktree() {  # mktree DIR  -- phone-like tree: user 1000 = oldname, member of android_graphics (1003)
  local T=$1
  mkdir -p "$T"/{etc/udev/rules.d,var/lib/dpkg/info,var/log,var/lib/dbus,usr/local/sbin,opt,home/oldname,root,media,mnt}
  printf 'root:x:0:0:root:/root:/bin/bash\nnobody:x:65534:65534:nobody:/nonexistent:/usr/sbin/nologin\noldname:x:1000:1000:oldname,,,:/home/oldname:/bin/bash\nother:x:1001:1001::/home/other:/bin/bash\n' > "$T/etc/passwd"
  printf 'root:x:0:\nsudo:x:27:oldname\nvideo:x:44:oldname\nrender:x:993:oldname\nnogroup:x:65534:\noldname:x:1000:\nother:x:1001:\nandroid_graphics:x:1003:oldname\n' > "$T/etc/group"
  printf 'root:*::\nsudo:*::oldname\noldname:!::\nother:!::\nandroid_graphics:!::oldname\n' > "$T/etc/gshadow"
  printf 'root:!:19000:0:99999:7:::\noldname:$6$s$aaaaaaaaaaaaaaaaaaaaaaaaaaaa:19000:0:99999:7:::\nother:$6$s$bbbbbbbbbbbbbbbbbbbbbbbbbbbb:19000:0:99999:7:::\n' > "$T/etc/shadow"
  printf 'oldname:100000:65536\nother:165536:65536\n' | tee "$T/etc/subuid" > "$T/etc/subgid"
  printf 'KERNEL=="ion", OWNER="root", GROUP="android_graphics", MODE="0660"\nKERNEL=="kgsl-3d0", OWNER="root", GROUP="android_graphics", MODE="0660"\n' > "$T/etc/udev/rules.d/99-s9-gpu.rules"
  printf 'Package: bash\nStatus: install ok installed\n\n' > "$T/var/lib/dpkg/status"; : > "$T/var/lib/dpkg/info/bash.list"
  echo s9 > "$T/etc/hostname"; echo abc > "$T/etc/machine-id"; echo hi > "$T/home/oldname/.bashrc"  # privacy-ok
}
audit() { python3 -I "$AUDIT" audit "$1" --old-user oldname --expect-user s9user --first-boot-account --report "$WORK/report.txt" >/dev/null 2>&1; cat "$WORK/report.txt"; }

echo "== 1. scrub keeps android_graphics and its member"
mktree "$WORK/t1"
python3 -I "$AUDIT" scrub "$WORK/t1" --defer-account --old-user oldname --hostname s9 > "$WORK/scrub.log" 2>&1 || { cat "$WORK/scrub.log"; bad "scrub failed"; }
grep -q '^android_graphics:x:1003:s9user$' "$WORK/t1/etc/group" && ok "etc/group: android_graphics:x:1003:s9user" || { bad "android_graphics (1003) lost or without the placeholder user"; cat "$WORK/t1/etc/group"; }
grep -q '^android_graphics:' "$WORK/t1/etc/gshadow" && ok "etc/gshadow keeps the group" || bad "etc/gshadow lost the group"
grep -q '^other:' "$WORK/t1/etc/group" && bad "the other human account's group was kept" || ok "other human accounts' groups are still dropped"

echo "== 2. audit: no GPU/group finding on the scrubbed tree"
audit "$WORK/t1" | grep -E 'udev rule|GPU device' > /dev/null && { bad "audit complains about a good tree"; grep -E 'udev rule|GPU device' "$WORK/report.txt"; } || ok "no finding"

echo "== 3. audit blocks when the group is missing (the bug of the first clean build)"
cp -a "$WORK/t1" "$WORK/t3"; sed -i '/^android_graphics:/d' "$WORK/t3/etc/group" "$WORK/t3/etc/gshadow"
audit "$WORK/t3" | grep -q 'GPU device would be root-only' && ok "blocked" || bad "audit did not block a missing android_graphics"

echo "== 4. audit blocks when the user is not a member"
cp -a "$WORK/t1" "$WORK/t4"; sed -i 's/^android_graphics:x:1003:.*/android_graphics:x:1003:/' "$WORK/t4/etc/group"
audit "$WORK/t4" | grep -q 'not a member of the group that owns the GPU device' && ok "blocked" || bad "audit did not block a non-member"

echo
[ "$FAIL" = 0 ] && echo "ALL OK" || echo "FAILED"
exit "$FAIL"
