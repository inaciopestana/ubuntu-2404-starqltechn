# Installing on a Galaxy S9 (SM-G9600)

> **Read this first.** This is a hobby port assembled by one person on one phone. The pieces
> below are real and were used on that phone. The author went from this port back to stock Android and installed it again
> twice; the second time with nothing but the files of the release, and it worked with no problem. **Nobody else has repeated
> the procedure yet** (see [Known gaps](#known-gaps)). Flashing a boot image can leave the phone unbootable; the ZIP erases `userdata`;
> doing the wrong thing to modem/EFS partitions can destroy IMEI and radio. Only continue if you can recover a phone with
> Odin/stock firmware ([`returning-to-android.md`](returning-to-android.md)) and you accept that risk.

## Quick route: the release ZIP
1. Stock Android 10 (PDA `G9600ZHU9FVF2`) on the phone, bootloader unlocked, phone online once so that the *OEM unlocking*
   item shows in Developer options. Not there yet, or the phone is on something else: [`returning-to-android.md`](returning-to-android.md)
   (Odin on Windows, `odin4` on Linux). **Back up first** (section 1 below).
2. Flash the patched TWRP (it keeps its settings): from the release `twrp-3.7.0_9-0-starqltechn-settings-cache.tar`, in
   Download Mode, with Odin (AP slot) or `odin4 -a` ([`tools/twrp/`](../tools/twrp/README.md#flashing-with-odin-from-a-pc)).
   Then go straight into TWRP (Volume Up + Bixby + Power).
3. In TWRP flash the **one** disabler ZIP of the release, `S9_G9600_disabler-and-encryption-removal.zip`
   ([`tools/twrp/disabler/`](../tools/twrp/disabler/README.md)): it does what `multidisabler` and `forceencrypt_remover_q`
   do, in the right order. It is small, so over USB: `adb shell twrp sideload`, then `adb sideload <zip>`. Do not boot Android
   after it.
4. Install `s9-clean-*.zip` (from the [Releases](../../../releases) page; compare its SHA-256). Three ways:
   * **Over the cable, no card (the tested one):** in TWRP run `adb shell twrp sideload` (or Advanced > ADB Sideload) and then
     `adb sideload s9-clean-*.zip` on the PC. See [Installing the Ubuntu ZIP over the cable](#installing-the-ubuntu-zip-over-the-cable).
   * From a **microSD card or USB-OTG drive**, TWRP > Install (never from the internal storage: the ZIP overwrites it).
   * [`tools/image/flash-from-pc.sh`](../tools/image/flash-from-pc.sh) from the PC (not tested on a real phone).
5. Reboot. On the first boot a window asks for your **user name, password and host name**; the phone restarts. Chrome is
   downloaded once there is network. What the ZIP does and does not contain: [`THIRD_PARTY.md`](../THIRD_PARTY.md).

The sections below are the manual route (building everything yourself) and the details behind each step.

## 0. What you need
* **Samsung Galaxy S9 SM-G9600** (Snapdragon 845). Not the Exynos models; not the S9+ (SM-G9650)
  without changes (the board name, partition numbers and firmware differ).
* **Unlocked bootloader** and **TWRP** for `starqltechn`: use the patched `twrp-3.7.0_9-0-starqltechn-settings-cache.tar` of the
  release, or download the original [`twrp-3.7.0_9-0-starqltechn.img`](https://dl.twrp.me/starqltechn/twrp-3.7.0_9-0-starqltechn.img.html)
  and patch it with [`tools/twrp/`](../tools/twrp/README.md) so it keeps its settings. Flash it with Odin or `odin4`
  ([how, and the pitfalls](../tools/twrp/README.md#flashing-with-odin-from-a-pc)). (Unlocking wipes the phone.)
* **`multidisabler` and `forceencrypt_remover_q`**, flashed in that TWRP. The release has them merged in one ZIP
  ([`tools/twrp/disabler/`](../tools/twrp/disabler/README.md)); the originals are in [this XDA post](https://xdaforums.com/t/kernel-upstream-kernelsu-susfs-s9-s9-n9-chn-usa.4703239/post-90032616).
* **Samsung stock firmware on the phone, left untouched.** The author's phone runs the last stock
  update for this model: build `G9600ZHU9FVF2` (Android 10, `QP1A.190711.020`, security patch
  2022-05-01). The `system` and `vendor` partitions and the modem firmware stay as Samsung shipped them
  (the ramdisk mounts the vendor and modem partitions at boot); this port **never writes the `system` partition**. If your phone is on another build, expect differences
  (vendor libraries, firmware paths). Get the firmware from an official source and flash it with
  Odin or `odin4`; it is not distributed here ([`returning-to-android.md`](returning-to-android.md)).
* A Linux PC (x86_64, Ubuntu 22.04 or later) with about 40 GB free, root access, and:
  `adb`, `debootstrap`, `qemu-user-static` + `binfmt-support`, `systemd-container` (`systemd-nspawn`),
  `git`, `python3`, `mkbootimg`/`unpack_bootimg.py` (from AOSP `system/tools/mkbootimg`), `sha256sum`.
* A cable that does data, and later a DeX-style dock plus keyboard/mouse if you want the desktop
  on an external monitor.
* **Your own phone's firmware.** Vendor/system/firmware images and modem blobs are read from the
  phone you are converting. They are not distributed here and must not be uploaded anywhere.

## Installing the Ubuntu ZIP over the cable
This is how the release ZIP (about 1 GB) was installed on a real phone, with no microSD card. TWRP is running, USB is connected,
and `adb devices` says `recovery`.
```sh
adb shell twrp sideload                      # puts TWRP in sideload mode
adb sideload s9-clean-*.zip                  # on the PC; takes about 9 minutes for the ~1 GB ZIP
```
* The installer is the same one as for a card. Its guard against running from the internal storage does not trigger here,
  because the sideloaded copy is served from the PC, not from `userdata`.
* TWRP serves the file **on demand** through FUSE; it does not need to hold the ZIP in RAM. The progress line ends with
  `Total xfer: 1.93x` on the author's phone when the install went through.
* **`Total xfer: 0.00x`** means the installer stopped at once. The reason is in TWRP's log:
  ```sh
  adb shell 'grep -E "TWRP installer|ERROR" /tmp/recovery.log | tail -20'
  ```
  The two reasons seen so far were bugs of the script under TWRP's busybox (`userdata is too small…` because its `[` compares
  integers with only 32 bits, and a failing `unzip -t` that busybox does not have); both are fixed in the current ZIP builds
  (`tools/image/twrp/update-binary.in`), so an older ZIP (made before 2026-11-03) shows them. If you have one, use the ZIP of the newest release
  on the Releases page or build one ([`tools/image/README.md`](../tools/image/README.md)).
* **Timeouts** (`ioctl bulk write Fail : Connection timed out`, or `adb sideload` hanging): the same USB problem as with
  `odin4`; put a USB 2.0 hub between the PC and the phone.
* The installer writes the root image into `userdata` (read back and compared by SHA-256) and the boot image last. When the log
  says `DONE`, reboot. If it says anything else, do **not** reboot into Ubuntu.

## 1. Back up everything first (from TWRP)
Boot TWRP (power off, hold **Volume Up + Bixby + Power**), connect USB, then on the PC:
```sh
adb devices                       # must say "recovery"
adb shell ls -l /dev/block/platform/soc/1d84000.ufshc/by-name/
# back up at least: boot, efs, modem (and sec_efs/persist/vendor/system if you have the space)
for p in boot efs modem persist; do
  adb exec-out "dd if=/dev/block/platform/soc/1d84000.ufshc/by-name/$p bs=4M" > backup-$p.img
done
sha256sum backup-*.img | tee backup.sha256
```
Keep these files **offline and private**: `efs` contains your IMEI and serial number.
Also keep a stock Odin firmware package for your exact model/region so you can return to Android.

## 2. Get the sources
```sh
git clone <URL of this repository> s9-ubports
git clone --branch ubports https://github.com/FakeShell/android_kernel_samsung_sdm845   # kernel
git -C android_kernel_samsung_sdm845 checkout a22a0b358140                               # the base the patches were made on
```
Set `S9_WORK` to a working directory; scripts use it (`kernel/scripts/*.sh`).

## 3. Kernel and boot image
The kernel is Samsung's 4.9 tree (FakeShell's `ubports` branch, Linux 4.9.186) with Halium options and three patches
([`kernel/patches/`](../kernel/patches/README.md)): HEVC encoder profile fix, Bluetooth profiles, DisplayPort 3840x1080 and no HDCP.
```sh
cd android_kernel_samsung_sdm845
for p in ../s9-ubports/kernel/patches/000*.patch; do git apply "$p" || break; done
# defconfig: starqlte_chn_halium_defconfig + kernel/halium.config
```
* Build with the **Android GCC 4.9** cross compiler (`aarch64-linux-android-`) **inside an
  Ubuntu 22.04 chroot** (`debootstrap jammy /opt/ubuntu2204`, enter with `systemd-nspawn`): the
  `make` of a very new distribution fails in `scripts/Makefile.lib`.
  `ARCH=arm64 CROSS_COMPILE=aarch64-linux-android- CROSS_COMPILE_ARM32=arm-linux-androideabi-`,
  `make O=<objdir> -j$(nproc)`. Output: `arch/arm64/boot/Image.gz-dtb`.
* **Assemble the boot image from your current one**, replacing only the kernel (see the
  detailed rules in [display-ultrawide.md](display-ultrawide.md)): extract the arguments with
  `unpack_bootimg.py --format=mkbootimg`, keep header v0 / page size 4096, append
  `SEANDROIDENFORCE`, pad with zeros to exactly **67108864 bytes** (the boot partition is
  `sda20`, 64 MiB, no AVB), keep `second_addr` (`deviceinfo_bootimg_force_second_address`).
  `kernel/scripts/s9-kbuild5.sh` does this and verifies it (header identical except size and id,
  ramdisk byte-identical, kernel equals the build); it is written for the author's directory layout
  and in Portuguese, so read it and adapt it before running it.
* **First install (no S9 boot image yet).** The author only ever repacked an *existing* boot
  image; building one from scratch follows the same rules but has not been tried. Build the
  [ramdisk](../kernel/ramdisk/README.md) first (it mounts the Ubuntu root, see step 5), then:
  ```sh
  kernel/ramdisk/build-ramdisk.py --rootfs /mnt/rootfs --out ramdisk.cpio.gz
  python3 unpack_bootimg.py --boot_img backup-boot.img --out stock --format=mkbootimg
  #   -> prints the mkbootimg arguments of your stock image. Reuse them, replacing
  #      --kernel with Image.gz-dtb, --ramdisk with ramdisk.cpio.gz and
  #      --cmdline with the deviceinfo_kernel_cmdline value from kernel/deviceinfo.
  mkbootimg <those arguments> -o boot-new.img
  ```
  Then append `SEANDROIDENFORCE`, pad to 67108864 bytes, and compare the header of `boot-new.img`
  with the stock one (`unpack_bootimg.py` on both): `second_addr`, `tags_addr`, offsets and page
  size must match.
* Optional 120 Hz mode: module parameter `s9_uw_hz` (default 60). 120 Hz needs a 4-lane DisplayPort
  link and gives a blank screen on 2-lane docks.

## 4. Flash the boot image (TWRP only)
```sh
bash kernel/scripts/s9-flash-boot5.sh boot-new.img <sha256-of-boot-new.img>
```
The script refuses to run unless the phone is in TWRP, checks that `boot` resolves to `sda20`
with 131072 sectors, pushes the file, verifies the hash on the phone, asks you to type `GRAVAR`
("write"), writes with `dd`, reads the partition back and compares the SHA-256. Its built-in list
of "known" hashes belongs to the author's images; for yours pass the hash as the second argument.
**Rollback** = run it again with your backed-up `backup-boot.img`.

## 5. The Ubuntu root file system
```sh
cd s9-ubports && sudo S9_WORK=$PWD/work kernel/scripts/build-rootfs-stage1.sh   # debootstrap --foreign noble arm64 + second stage under qemu
```
Then, inside the arm64 root (chroot with `qemu-aarch64-static`):
1. Add the **UBports 24.04-2.x** repository and install the Halium/Lomiri base: `libhybris`,
   `lomiri-system-compositor`, `mir` 1.8.3 packages, `ofono-sailfish` + binder plugin,
   `pulseaudio-modules-droid`, `bluebinder`, `busybox-static` and `dmsetup` (for the ramdisk), `NetworkManager`, `xfce4` (minimal), `lightdm`
   (only for its seat handling), `xwayland`, `docklike` plugin. The complete list of packages on the
   author's phone is not published yet.
2. Run the Halium graft helpers `kernel/halium-graft/00..08` (dry-run by default; `--apply` to
   write). They adapt a reference Halium device's graphics/audio files to the S9 and **must be
   given vendor files extracted from your own phone**.
3. **Halium Android image.** The container that runs the Android HAL is `android-rootfs.img`
   (Halium 10, `lineage_halium_arm64`, build `QQ3A.200805.001` / 1439, 537,280,512 bytes), expected at
   `/var/lib/lxc/android/android-rootfs.img` inside the Ubuntu root. It is **not included in this repository** (the release ZIP does carry it):
   the author's copy is byte-identical to the one inside the V7 release of the base port
   (`Gustavo2Toledo/ubuntu-touch-star2qltechn`, whose `release/v7` README lists `rootfs.img`
   sha256 `fdd65c57deeed7716726b67384145d6a793ce43194339817e9e7a795d6d0474b`), whose build script fetches the
   generic `halium_halium_arm64` artifact of the UBports CI (halium-10.0); whether the file is that artifact unmodified was not checked. That repository states no
   licence, so we only point to it. Extract the file yourself (loop-mount the raw system image of
   that release read-only and copy `var/lib/lxc/android/android-rootfs.img`) and check:
   ```sh
   echo "527c53fd8e27957fe4046cd8588d689dec338e8abb6531af4602c2f235ca0944  android-rootfs.img" | sha256sum -c
   ```
   (The identity of the two copies was verified on the author's PC and phone; the extraction steps
   from the downloadable ZIP were not rehearsed.)
4. Build and install the patched Mir/Xwayland/shell (see [compositor-and-window-manager.md](compositor-and-window-manager.md)
   and the patches in `mir/`, `platform/`, `xwayland/`, `shell/`) into the layout below.
5. Copy this repository to `/opt/s9-ubports` inside the root (the first-boot service expects it
   there) and enable the first-boot service:
   ```sh
   # run inside the clone
   mkdir -p /mnt/rootfs/opt/s9-ubports && cp -a . /mnt/rootfs/opt/s9-ubports
   cp installer/s9-firstboot.service /mnt/rootfs/etc/systemd/system/
   mkdir -p /mnt/rootfs/etc/systemd/system/multi-user.target.wants
   ln -s /etc/systemd/system/s9-firstboot.service /mnt/rootfs/etc/systemd/system/multi-user.target.wants/
   ```
   Or do everything in one step, non-interactively, on the PC:
   ```sh
   printf 'S9_USER=alice\nS9_KEYMAP=us\nS9_TZ=Europe/Berlin\nS9_HOSTNAME=s9\n' > s9.conf
   S9_PASSWORD_HASH=$(openssl passwd -6) installer/s9-firstboot --root /mnt/rootfs --conf s9.conf --repo $PWD
   ```
   (`s9-firstboot` with `--conf` skips the questions. `installer/s9-apply-overlay` is the part that
   copies `system/` and `userland/`, fills the `@S9_USER@` placeholders, creates the account and
   enables the units.)
6. Binary layout the `s9-miral-nested.service` unit expects:

   | Path | Content |
   |---|---|
   | `/opt/s9-ubports/lib/` | patched Mir libraries (`libmir1server.so.53`, ...) |
   | `/opt/s9-ubports/platform/graphics-android2.so.16` | Android/GPU Mir platform |
   | `/opt/s9-ubports/shell/s9-miral-shell` | the window manager |
   | `/opt/s9-xwayland-gralloc/Xwayland.wrapper` | Xwayland with the gralloc backend (bind-mounted over `/usr/bin/Xwayland`) |
   | `/opt/mesa-kgsl-peekaboo/` | Mesa with Freedreno on KGSL (third-party package, not included) |

7. **Put the root file system on the phone.** The Ubuntu root lives inside the `userdata`
   partition (`sda29`), 1 MiB from its start; the ramdisk maps it as `/dev/mapper/s9root`
   ([kernel/ramdisk/README.md](../kernel/ramdisk/README.md)). This **destroys everything on `userdata`**
   (back it up if you want to keep it). Build a small ext4 image and write it at the 1 MiB offset
   from TWRP:
   ```sh
   # PC, as root: image of the finished root tree (overlay and account already installed)
   truncate -s 6G rootfs.img && mkfs.ext4 -L s9root -d /mnt/rootfs rootfs.img
   sha256sum rootfs.img
   # TWRP, USB connected (not tested by the author, who created the image differently):
   adb exec-in 'dd of=/dev/block/platform/soc/1d84000.ufshc/by-name/userdata bs=1M seek=1' < rootfs.img
   adb exec-out 'dd if=/dev/block/platform/soc/1d84000.ufshc/by-name/userdata bs=1M skip=1 count=6144' | sha256sum
   ```
   The two hashes must be equal. (For a finished ZIP, [`tools/image/flash-from-pc.sh`](../tools/image/flash-from-pc.sh) does exactly this over `adb`, with the checks, and also writes `boot`.) After the first boot, grow the file system to the whole
   mapping: `sudo resize2fs /dev/mapper/s9root`.

## 6. First boot
**Release ZIP:** a graphical window asks for the user name, password and host name, applies them (the account is renamed
everywhere it is referenced) and restarts the phone. If it fails it undoes its changes. The rest of this section is about
the manual route.

Boot the phone. If the first-boot service was enabled and no `--conf` was given, it asks on
`tty1` for: user name, password (twice), host name, time zone, keyboard layout and variant, and
locale. Then it writes `/etc/s9-ubports.conf`, installs the overlay, creates the account and
tells you to reboot. After the reboot:
```sh
systemctl status s9-lsc s9-miral-nested          # system compositor, nested desktop compositor
journalctl -u s9-miral-nested -b | head
ls /run/s9-miral/                                # wayland-0 and mir_socket must exist
pactl list short sinks                           # audio card (see audio-and-boot-reliability.md)
```
If audio is missing, the DSP firmware probably failed to load at boot: read
[audio-and-boot-reliability.md](audio-and-boot-reliability.md) (`s9-adsp-ensure`). The phone clock
starts in 2018/2019 until the network sets it (`s9-clock-keep` keeps the last known time).

External monitor: plug the dock after boot. `/etc/s9-miral.display` selects `3840x1080@60.0` for
`DisplayPort-1`; change it only together with the kernel parameter `s9_uw_hz`.

## Known gaps
These are the pieces that stop the procedure above from being a one-command install. They are
being worked on; patches welcome.

| Gap | Detail |
|---|---|
| **Boot image from scratch** | The ramdisk (`kernel/ramdisk/`) is published and `build-ramdisk.py` works on stand-in binaries, but nobody has built a boot image from it or booted it; the author reused the ramdisk of an existing boot image. Writing the root image to `userdata` (step 5.7) is also untested as written. |
| **Package list** | The exact list of installed packages and UBports repository pins is not yet exported. |
| **Halium image provenance** | `android-rootfs.img` is the UBports CI artifact `halium_halium_arm64` (halium-10.0), obtained via the base port's V7 release. The ready-made release ZIP includes it; the claim that the file is unmodified has not been checked against the CI artifact. |
| **Mesa KGSL package** | Comes from a third party (`ImPeekaboo`, Mesa under MIT). The ready-made release ZIP includes it under `/opt/mesa-kgsl-peekaboo` with credit. |
| **Release ZIP on a phone** | The release files (patched TWRP, disabler ZIP, Ubuntu ZIP over `adb sideload`) were used start to finish twice on the author's phone, the second time with no problem. Earlier builds of the ZIP had two bugs found on the phone and fixed: the Adreno GPU device group was dropped by the privacy scrub, and NetworkManager made a pointless "Wired connection 1" on `p2p0`. Not yet checked: a run by anyone but the author, the SD-card route and `flash-from-pc.sh` on a real phone, Odin on Windows. Stage 5 above remains the manual route. |
| **Tested only here** | `installer/s9-apply-overlay` and `s9-firstboot` were tested on a scratch directory, not on a phone. |

## Going back
* Boot image: flash `backup-boot.img` the same way (step 4).
* Whole phone: flash the stock Samsung firmware with Odin or `odin4`, using the plain `CSC` file so `userdata` is wiped:
  [`returning-to-android.md`](returning-to-android.md). Restoring `efs`/`modem` backups is only needed if you damaged them.
