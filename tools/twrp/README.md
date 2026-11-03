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
[release](../../../../releases/tag/v0.1.0) as `twrp-3.7.0_9-0-starqltechn-settings-cache.tar` (SHA-256
`b3d3061d30f253b78f9c146639e3c2cc937c40347e55451e4d5f3420f633e7e2`), an Odin "AP" tar holding a single file,
`recovery.img` (72,339,456 bytes, SHA-256 `96063fe2ba5c8450dced1f0bbdce9fe0da11f5a7fa462f6acaf89c122f115df0`). It is
TeamWin's TWRP with one line changed in `etc/recovery.fstab` (see above). To flash it from Linux or Windows use Odin in
download mode (AP slot), as described in [Flashing with Odin](#flashing-with-odin-from-a-pc) below; to get the bare image,
`tar -xf` it; TWRP's source is available from <https://twrp.me/> and TeamWin's GitHub organisation.

## Flashing with Odin from a PC

This is the route for a phone that is still on stock Android (no TWRP yet). The other route, `flash-recovery.sh` below, needs
a phone that already runs a recovery with root.

**Before you start:** the phone must have been **online**, and the *OEM unlocking* item must be visible in Developer
options. Without it Odin stops at `recovery.img` with `FAIL! (Auth)`. Details, and how to get the phone to that state:
[`docs/returning-to-android.md`](../../docs/returning-to-android.md).

1. **Make an Odin tar** (skip this if you use the one from the release). The file inside must be called `recovery.img`, because
   Odin maps it to the recovery partition by name:
   ```sh
   mkdir t && cp twrp-3.7.0_9-0-starqltechn-settings-cache.img t/recovery.img
   (cd t && tar -H ustar -c recovery.img) > twrp-settings-cache.tar
   ```
   Give `odin4` the **plain `.tar`**. A `.tar.md5` made by hand with `md5sum` made `odin4` stop with `md5 fail`.
2. **Download Mode**: power off, hold Volume Down + Bixby, plug the cable, Volume Up to continue.
3. **Flash it:**
   * Linux, command line: `odin4 -a twrp-settings-cache.tar` (it ends with `Close Connection`; `odin4` does not restart the phone).
     If it times out in `Setup Connection`, connect the phone through a USB 2.0 hub.
   * Linux, [Odin4 GUI](../../docs/returning-to-android.md#odin4-gui) ([Ragekill3377/Odin4-GUI](https://github.com/Ragekill3377/Odin4-GUI)): put the tar in the *AP* slot (the GUI was not used for this by the author).
   * Windows, Odin: the tar in the *AP* slot, *Auto Reboot* off, Start (not tested by the author).
4. **Boot straight into the recovery.** Do not let Android start first: Samsung's firmware has a `flash_recovery` service that can
   restore the stock recovery on a normal boot (on the author's phone it should find nothing to restore, because there is no
   `recovery-from-boot.p`, but going straight to TWRP costs nothing).
   Hold Volume Down + Power about ten seconds until the screen goes dark, then immediately hold Volume Up + Bixby + Power.

## Usage: patching the image and flashing from a running recovery

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
