# TWRP settings that survive a reboot

The TWRP build used for the Galaxy S9 (SM-G9600, `starqltechn`) starts with default settings on every boot, because its
`/etc/recovery.fstab` marks no partition for settings storage. TWRP writes its settings file to the partition flagged
`settingsstorage`. The fix is one flag on the `/cache` line:

```
/cache  ext4  /dev/block/platform/soc/1d84000.ufshc/by-name/cache
/cache  ext4  /dev/block/platform/soc/1d84000.ufshc/by-name/cache  flags=settingsstorage
```

Nothing else in the recovery changes. Kernel, device tree and every other ramdisk entry stay byte-identical.

## Files

| File | Runs on | What it does |
| --- | --- | --- |
| `patch-recovery-settings.sh` | PC | Takes a recovery image file, adds the flag, repacks, and verifies the result. Never touches the phone. |
| `flash-recovery.sh` | Phone (root) | Backs up the current recovery partition (`sda21`), writes the patched image, reads it back and compares SHA-256. |

No recovery image is stored in the repository tree. TWRP and `magiskboot` are third-party GPL projects; get them from their
own releases. For convenience the result of this procedure is also attached to the
[release](../../../../releases/tag/v0.1.0-pre1) as `twrp-3.7.0_9-0-starqltechn-settings-cache.tar` (SHA-256
`b3d3061d30f253b78f9c146639e3c2cc937c40347e55451e4d5f3420f633e7e2`), an Odin "AP" tar holding a single file,
`recovery.img` (72,339,456 bytes, SHA-256 `96063fe2ba5c8450dced1f0bbdce9fe0da11f5a7fa462f6acaf89c122f115df0`). It is
TeamWin's TWRP with one line changed in `etc/recovery.fstab` (see above). To flash it from Linux or Windows use Odin in
download mode (AP slot); to get the bare image, `tar -xf` it; TWRP's source is available from <https://twrp.me/> and TeamWin's GitHub organisation.

## Usage

1. Get the original recovery to patch: download [`twrp-3.7.0_9-0-starqltechn.img`](https://dl.twrp.me/starqltechn/twrp-3.7.0_9-0-starqltechn.img.html) from twrp.me (or dump the
   `recovery` partition of a phone that already runs it; the dump is 72,339,456 bytes).
2. On the PC, with `magiskboot` from the Magisk project:

   ```
   tools/twrp/patch-recovery-settings.sh --in recovery-original.img --out recovery-settings.img \
       --magiskboot /path/to/magiskboot
   ```

   The script stops on any surprise: not exactly one `/cache` line, a changed kernel, an unpacking failure, or a size
   different from the input. It prints the SHA-256 of the result.
3. Copy the image to the phone and flash it, passing the SHA-256 printed in step 2:

   ```
   sudo tools/twrp/flash-recovery.sh recovery-settings.img <sha256> ~/recovery-before.img
   ```

   Keep the backup file. Restoring is `dd if=~/recovery-before.img of=/dev/sda21 bs=1M conv=fsync`.
   Alternatively use TWRP, Install, Install Image, Recovery.
4. Reboot to recovery, change a setting, reboot to recovery again, and check that it stuck.

## Checked on

TWRP 3.7.0_9-0 for `starqltechn` (build `omni_starqltechn-eng 16.1.0 OPM8.181105.002`, October 2022). Patching the
original image produced a file byte-identical to the one flashed by hand earlier
(SHA-256 `96063fe2ba5c8450dced1f0bbdce9fe0da11f5a7fa462f6acaf89c122f115df0`).
