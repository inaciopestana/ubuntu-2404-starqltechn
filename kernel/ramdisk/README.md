# The S9 initramfs

The phone boots a very small custom initramfs (not the Halium one). Its job is to give the
kernel a root device that does not exist as a partition: the Ubuntu root file system is an
ext4 image stored **inside `userdata` (`/dev/sda29`), starting 1 MiB from its beginning**, and
the initramfs exposes it as `/dev/mapper/s9root` with a device-mapper `linear` target.

```
sda29 (userdata, e.g. 111623864 sectors)
 |<-1 MiB->|<---------------- s9root: length = size - 2 x 1 MiB ---------------->|<-1 MiB->|
```
Both ends are left unused on purpose (GPT/backup structures). `init` then mounts the mapping
read-write on `/newroot`, mounts the Android `vendor` (`sda23`) and modem firmware (`sda17`)
partitions and moves them into the new root, and runs `switch_root` to
`/usr/local/sbin/s9-init-wrapper` (see `system/`), which logs to `/boot-stage.log` and starts
`/sbin/init` (systemd). Everything is printed on the kernel console; if something is missing the
script drops into a shell (`exec sh`).

## Contents
* `init` - the script (about 4 KB).
* `build-ramdisk.py` - builds `ramdisk.cpio.gz` from an Ubuntu 24.04 arm64 root: static `busybox`
  (with the applets listed in the script), `dmsetup` and its libraries (found with `readelf`),
  the mount-point directories and `init`. Python 3 and binutils only; no root, no `cpio`;
  output is byte-for-byte reproducible.

```sh
# packages in the arm64 root:  busybox-static dmsetup
kernel/ramdisk/build-ramdisk.py --rootfs /mnt/rootfs --out ramdisk.cpio.gz
```
The ramdisk goes into the Android boot image together with the kernel; see `docs/installing.md`.

## The root image
The mapping starts 1 MiB into the partition, so the ext4 image must be written there
(`dd ... of=/dev/block/sda29 bs=1M seek=1`) and **this destroys everything on `userdata`**.
The image can be small at first; after the first boot grow the file system to the whole mapping
with `resize2fs /dev/mapper/s9root`.

## Status
The `init` logic is the author's working script, with English messages and the length computed
instead of hard-coded. `build-ramdisk.py` was tested here only against x86 stand-in binaries (the
archive structure, library resolution and reproducibility), not with the real arm64 packages and
not on a phone.
