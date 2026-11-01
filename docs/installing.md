# Installing on a Galaxy S9 (SM-G9600)

> **Read this first.** This is a hobby port assembled by one person on one phone. The pieces
> below are real and were used on that phone, but **nobody has repeated the whole procedure from
> a blank phone**, and one piece (the boot-image ramdisk, see [Known gaps](#known-gaps)) is not in
> this repository yet. Flashing a boot image can leave the phone unbootable; doing the wrong
> thing to modem/EFS partitions can destroy IMEI and radio. Only continue if you can recover a
> phone with Odin/stock firmware and you accept that risk.

## 0. What you need
* **Samsung Galaxy S9 SM-G9600** (Snapdragon 845). Not the Exynos models; not the S9+ (SM-G9650)
  without changes (the board name, partition numbers and firmware differ).
* **Unlocked bootloader** and **TWRP** for `starqltechn`. (Unlocking wipes the phone.)
* A Linux PC (x86_64, Ubuntu 22.04 or later) with about 40 GB free, root access, and:
  `adb`, `debootstrap`, `qemu-user-static` + `binfmt-support`, `systemd-container` (`systemd-nspawn`),
  `git`, `python3`, `mkbootimg`/`unpack_bootimg.py` (from AOSP `system/tools/mkbootimg`), `sha256sum`.
* A cable that does data, and later a DeX-style dock plus keyboard/mouse if you want the desktop
  on an external monitor.
* **Your own phone's firmware.** Vendor/system/firmware images and modem blobs are read from the
  phone you are converting. They are not distributed here and must not be uploaded anywhere.

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
```
Set `S9_WORK` to a working directory; scripts use it (`kernel/scripts/*.sh`).

## 3. Kernel and boot image
The kernel is Samsung's 4.9 tree with Halium options and three local patches.
```sh
cd android_kernel_samsung_sdm845
git apply ../s9-ubports/kernel/patches/s9-secdp-ultrawide-32-9.patch   # 3840x1080 over DisplayPort
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
   `pulseaudio-modules-droid`, `bluebinder`, `NetworkManager`, `xfce4` (minimal), `lightdm`
   (only for its seat handling), `xwayland`, `docklike` plugin. The complete list of packages on the
   author's phone is not published yet.
2. Run the Halium graft helpers `kernel/halium-graft/00..08` (dry-run by default; `--apply` to
   write). They adapt a reference Halium device's graphics/audio files to the S9 and **must be
   given vendor files extracted from your own phone**.
3. Build and install the patched Mir/Xwayland/shell (see [compositor-and-window-manager.md](compositor-and-window-manager.md)
   and the patches in `mir/`, `platform/`, `xwayland/`, `shell/`) into the layout below.
4. Copy this repository to `/opt/s9-ubports` inside the root (the first-boot service expects it
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
5. Binary layout the `s9-miral-nested.service` unit expects:

   | Path | Content |
   |---|---|
   | `/opt/s9-ubports/lib/` | patched Mir libraries (`libmir1server.so.53`, ...) |
   | `/opt/s9-ubports/platform/graphics-android2.so.16` | Android/GPU Mir platform |
   | `/opt/s9-ubports/shell/s9-miral-shell` | the window manager |
   | `/opt/s9-xwayland-gralloc/Xwayland.wrapper` | Xwayland with the gralloc backend (bind-mounted over `/usr/bin/Xwayland`) |
   | `/opt/mesa-kgsl-peekaboo/` | Mesa with Freedreno on KGSL (third-party package, not included) |

6. Put the root file system on the phone. The kernel command line in `kernel/deviceinfo`
   mounts the Ubuntu root from `root=/dev/sda29` (ext4) and the Android `system` image from the
   partition labelled `system`; this is where the [known gap](#known-gaps) about the ramdisk
   matters. Do not repartition unless you know exactly which partition holds your data.

## 6. First boot
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
| **Boot ramdisk** | The author's boot image uses a ramdisk modified so that the Ubuntu root (`/dev/mapper/s9root`, built on `sda29`) is mounted. Those changes come from the phone's own boot image (Halium initramfs) and are **not published** here. Until a ramdisk builder is added, use the Halium/UBports initramfs recipe for a device with the same `deviceinfo`. |
| **Package list** | The exact list of installed packages and UBports repository pins is not yet exported. |
| **Mesa KGSL package** | Comes from a third party (`ImPeekaboo`); you must obtain it yourself. |
| **Image builder** | There is no script that produces a flashable root image; stage 5 is manual. |
| **Tested only here** | `installer/s9-apply-overlay` and `s9-firstboot` were tested on a scratch directory, not on a phone. |

## Going back
* Boot image: flash `backup-boot.img` the same way (step 4).
* Whole phone: flash the stock Samsung firmware with Odin. Restoring `efs`/`modem` backups is
  only needed if you damaged them.
