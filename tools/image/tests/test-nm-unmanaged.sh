#!/bin/bash
# Regression test: NetworkManager must leave usb0, rndis0, swlan0 and p2p0 alone in the clean image.
# p2p0 (the Wi-Fi driver's own P2P interface) is an Ethernet device for NetworkManager: left managed, it gets an automatic
# "Wired connection 1" that asks for a DHCP lease forever. And a plain `unmanaged-devices=` in 90-s9-usb.conf replaced the
# list of 90-s9-swlan0-unmanaged.conf, so swlan0 lost its exclusion too.
#
# Builds a small synthetic tree with the NetworkManager files of the author's phone, runs the scrub with the clean overlay,
# and reads the effective list back with the same parser the audit uses.   bash tools/image/tests/test-nm-unmanaged.sh
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
ok()  { echo "   [ok]   $*"; }
bad() { echo "   [FAIL] $*"; FAIL=1; }

mktree() {  # phone-like tree with the NetworkManager files the author's phone had
  local T=$1
  mkdir -p "$T"/{etc/udev/rules.d,etc/NetworkManager/conf.d,var/lib/dpkg/info,var/log,var/lib/dbus,usr/local/sbin,opt,home/oldname,root,media,mnt}
  printf 'root:x:0:0:root:/root:/bin/bash\noldname:x:1000:1000:oldname,,,:/home/oldname:/bin/bash\n' > "$T/etc/passwd"
  printf 'root:x:0:\nsudo:x:27:oldname\noldname:x:1000:\nandroid_graphics:x:1003:oldname\n' > "$T/etc/group"
  printf 'root:*::\noldname:!::\nandroid_graphics:!::oldname\n' > "$T/etc/gshadow"
  printf 'root:!:19000:0:99999:7:::\noldname:$6$s$aaaaaaaaaaaaaaaaaaaaaaaaaaaa:19000:0:99999:7:::\n' > "$T/etc/shadow"
  printf 'oldname:100000:65536\n' | tee "$T/etc/subuid" > "$T/etc/subgid"
  printf 'KERNEL=="kgsl-3d0", OWNER="root", GROUP="android_graphics", MODE="0660"\n' > "$T/etc/udev/rules.d/99-s9-gpu.rules"
  printf 'Package: bash\nStatus: install ok installed\n\n' > "$T/var/lib/dpkg/status"; : > "$T/var/lib/dpkg/info/bash.list"
  echo s9 > "$T/etc/hostname"; echo abc > "$T/etc/machine-id"; echo hi > "$T/home/oldname/.bashrc"  # privacy-ok
  # exactly what the phone had (the second file replaces the first one's list)
  printf '[keyfile]\nunmanaged-devices+=interface-name:swlan0;interface-name:p2p-dev-swlan0\n' > "$T/etc/NetworkManager/conf.d/90-s9-swlan0-unmanaged.conf"
  printf '[keyfile]\nunmanaged-devices=interface-name:usb0;interface-name:rndis0\n' > "$T/etc/NetworkManager/conf.d/90-s9-usb.conf"
  printf '[connection]\nwifi.powersave = 3\n' > "$T/etc/NetworkManager/conf.d/default-wifi-powersave-on.conf"
}
effective() {  # effective TREE -> the unmanaged list, one per line, as the audit computes it
  python3 -I - "$AUDIT" "$1" <<'PY'
import importlib.util, sys
spec = importlib.util.spec_from_file_location('audit_tree', sys.argv[1]); m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
print('\n'.join(m.nm_unmanaged_devices(m.Tree(sys.argv[2]))))
PY
}
audit() { python3 -I "$AUDIT" audit "$1" --old-user oldname --expect-user s9user --first-boot-account --report "$WORK/report.txt" >/dev/null 2>&1; cat "$WORK/report.txt"; }

echo "== 1. the author's phone files, as they are: the list is wrong (the bug)"
mktree "$WORK/t0"
L0="$(effective "$WORK/t0")"
echo "$L0" | grep -qx 'interface-name:swlan0' && bad "swlan0 is still excluded (the plain = of 90-s9-usb.conf should have dropped it)" || ok "swlan0 is dropped by 90-s9-usb.conf (known bug, fixed by the overlay)"
echo "$L0" | grep -qx 'interface-name:p2p0' && bad "p2p0 excluded without the fix?" || ok "p2p0 is not excluded (the 'Wired connection 1' on p2p0)"
audit "$WORK/t0" | grep -q 'would manage an interface that is not a network' && ok "the audit blocks this tree" || bad "the audit did not block it"

echo "== 2. after the scrub with the clean overlay"
mktree "$WORK/t1"
python3 -I "$AUDIT" scrub "$WORK/t1" --defer-account --old-user oldname --hostname s9 --overlay "$HERE/clean-overlay" > "$WORK/scrub.log" 2>&1 || { tail -n 20 "$WORK/scrub.log"; bad "scrub failed"; }
L1="$(effective "$WORK/t1")"
for i in usb0 rndis0 swlan0 p2p-dev-swlan0 p2p0; do
  echo "$L1" | grep -qx "interface-name:$i" && ok "$i is unmanaged" || bad "$i is NOT unmanaged"
done
audit "$WORK/t1" | grep -q 'would manage an interface that is not a network' && bad "the audit still complains" || ok "the audit has no NetworkManager finding"

echo
[ "$FAIL" = 0 ] && echo "ALL OK" || echo "FAILED"
exit "$FAIL"
