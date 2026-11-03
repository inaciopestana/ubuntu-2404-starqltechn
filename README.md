# Ubuntu 24.04 + XFCE on the Samsung Galaxy S9 (SM-G9600)

A community experiment that runs a **full Ubuntu 24.04 desktop** (XFCE) on a Snapdragon 845
Galaxy S9 using Halium 10, with GPU acceleration (Adreno 630), external display support,
audio, mobile data, calls and SMS.

> **Status: experimental, one device, one tester.** Everything here comes from the author's
> own SM-G9600 (G9600 = Snapdragon S9, China/Hong Kong variants). The flashable ZIP was installed and booted on that phone
> (by `adb sideload` from TWRP), but nobody else has repeated any step, and the author's own run from a stock phone is not finished. Flashing a kernel or boot
> image can make a phone unbootable, and the ZIP **erases `userdata`** (Android's data). Back up EFS, modem and boot
> partitions first and only continue if you accept that risk. See [`docs/installing.md`](docs/installing.md).

## Installation at a glance
Five steps, in this order. Details, risks and the way back are in [`docs/installing.md`](docs/installing.md).

1. **Samsung stock Android 10 on the phone, with the PDA (AP) build `G9600ZHU9FVF2`**
   (`QP1A.190711.020`, security patch 2022-05-01). Flash it with Odin if the phone is on another build.
   The `system`, `vendor` and modem partitions stay exactly as Samsung shipped them; this port never writes `system`.
2. **Unlock the bootloader** (Developer options > OEM unlocking, then the download-mode unlock). This wipes the phone and
   trips Knox.
3. **Install the custom TWRP that keeps its settings in `/cache`** (see [`tools/twrp/`](tools/twrp/README.md)).
   Either download the already patched `twrp-3.7.0_9-0-starqltechn-settings-cache.tar` from the [Releases](../../releases) page
   (an Odin "AP" file: in download mode, load it as AP in Odin, or `odin4 -a` on Linux; the details and the pitfalls, such as
   `FAIL! (Auth)` when the phone has never been online, are in [`tools/twrp/`](tools/twrp/README.md#flashing-with-odin-from-a-pc)),
   or patch the original yourself: [`twrp-3.7.0_9-0-starqltechn.img`](https://dl.twrp.me/starqltechn/twrp-3.7.0_9-0-starqltechn.img.html).
   Ubuntu lives in a dedicated image inside the `userdata` partition, so TWRP cannot keep its settings there; the
   patched recovery stores them on `/cache` instead (one flag in `recovery.fstab`).
4. **In that TWRP, flash the disabler ZIP** (`S9_G9600_disabler-and-encryption-removal.zip` from the Releases page, over USB with
   `adb sideload`). It is `multidisabler` and `forceencrypt_remover_q` from [this XDA post](https://xdaforums.com/t/kernel-upstream-kernelsu-susfs-s9-s9-n9-chn-usa.4703239/post-90032616)
   merged into one script that applies them in the right order, with credits and notes in [`tools/twrp/disabler/`](tools/twrp/disabler/README.md).
   They turn off Samsung's boot-time integrity checks and the forced encryption of `userdata`, which get in the way of a custom
   boot and root image. Do not boot Android after it.
5. **In the same TWRP, flash the Ubuntu ZIP.** It carries the boot image and the Ubuntu root image (the Halium Android
   container is inside the root image), and it writes them with read-back checks. Keep the ZIP on a **microSD card or
   USB-OTG drive, never on the internal storage**: the ZIP overwrites `userdata`, and the installer refuses to run from it.
   Download `s9-clean-*.zip` from the [Releases](../../releases) page (check its SHA-256), or build it yourself with
   [`tools/image/build-image.sh`](tools/image/build-image.sh). On the first boot a window asks for your **user name,
   password and host name** (how the phone shows up on the network), then the phone restarts.
   **Over the USB cable, with no card (tested on a real phone):** in TWRP run `adb shell twrp sideload`, then
   `adb sideload s9-clean-*.zip` on the PC (about 9 minutes for the ~1 GB ZIP; the sideloaded copy is served from the PC, so
   the installer's guard does not trigger; how to read the log if it stops: [`docs/installing.md`](docs/installing.md#installing-the-ubuntu-zip-over-the-cable)).
   Another cable route is [`tools/image/flash-from-pc.sh`](tools/image/flash-from-pc.sh), which streams the root image into `userdata` and the boot image into
   `boot` with `adb` and checks both by SHA-256 read-back (details in [`tools/image/README.md`](tools/image/README.md); not tested on a real phone).

> **Kernel.** The boot image is built from FakeShell's [`android_kernel_samsung_sdm845`](https://github.com/FakeShell/android_kernel_samsung_sdm845)
> (branch `ubports`, Linux 4.9.186, base commit `a22a0b358140`) plus the patches in [`kernel/patches/`](kernel/patches/README.md).
>
> The five steps describe the author's setup on one phone. The patched TWRP and the disabler ZIP of step 4 are the
> author's choice. **Need to go back to stock Android first, or to restart from a clean phone?** See
> [`docs/returning-to-android.md`](docs/returning-to-android.md) (Odin on Windows, `odin4` on Linux; on the author's laptop `odin4` only
> worked through a USB 2.0 hub).

### What the release ZIP contains, and what it does not
* **Contains:** the boot image (Linux 4.9.186 with the patches of this repository) and the Ubuntu 24.04 root image: XFCE, the
  patched Mir/MirAL desktop, Xwayland, Freedreno/KGSL Mesa, the Halium 10 Android container, telephony and audio stack. The
  licences and the places to get the source of every part are in [`THIRD_PARTY.md`](THIRD_PARTY.md).
* **Does not contain:** Samsung/Qualcomm firmware (the Adreno 630 firmware is copied at the first boot from your own phone's
  `vendor` partition), Google Chrome (downloaded from Google at the first boot, so it needs Wi-Fi or mobile data), and any
  personal data of the author.
* The ZIP is built by [`tools/image`](tools/image/README.md) from a backup of the author's phone, passes an automatic
  privacy audit and was inspected afterwards; it is a **pre-release**. After the first test on a phone the build was fixed
  (GPU device group, no pointless wired connection on `p2p0`); use the newest ZIP on the Releases page.

## What is in this repository
| Path | Content |
|---|---|
| [`docs/`](docs/README.md) | how the system works and how it was built (start at [`architecture.md`](docs/architecture.md)) |
| [`kernel/`](kernel/) | device config, [kernel patches](kernel/patches/README.md) (incl. 3840x1080 DisplayPort support), build/flash scripts, Halium graft tooling |
| [`mir/`](mir/) | patches on Mir 1.8.3 (cumulative) |
| [`platform/`](platform/) | patch on the Mir Android/GPU platform |
| [`xwayland/`](xwayland/) | Xwayland gralloc + DRI3 patches |
| [`shell/`](shell/) | the custom MirAL shell (window manager) |
| [`system/`](system/), [`userland/`](userland/) | systemd units, udev/sudoers rules, helper scripts and apps |
| [`installer/`](installer/) | overlay installer and first-boot setup (tested on a scratch directory only) |
| [`tools/image/`](tools/image/README.md) | builds the flashable TWRP ZIP (boot + Ubuntu root image) from a backup of the phone, with a privacy audit; `flash-from-pc.sh` installs it over USB/adb |
| [`tools/twrp/`](tools/twrp/README.md) | patch and flash the TWRP that keeps its settings in `/cache` (with Odin/`odin4` too); [`disabler/`](tools/twrp/disabler/README.md) builds the one-ZIP version of `multidisabler` + `forceencrypt_remover_q` |
| [`tools/`](tools/) | other maintainer tools: privacy scan, export scripts |
| [`THIRD_PARTY.md`](THIRD_PARTY.md), [`NOTICE.md`](NOTICE.md), [`LICENSE`](LICENSE) | what the release ZIP contains with licences and source locations; provenance of every directory; the licence text |
| [`SECURITY.md`](SECURITY.md), [`CONTRIBUTING.md`](CONTRIBUTING.md) | reporting problems; how to contribute |

## What works (on the author's device)
Desktop with window frames, dock, Alt+Tab, full-screen, clipboard (text/images) between Wayland native and
X11 apps, notifications, Bluetooth and Wi-Fi applets, external monitor with audio (ultrawide resolution supported), GPU-accelerated
GL via native Freedreno on KGSL, audio, mobile data, voice calls and SMS (with an app), DeX
fan control, screen casting (browser/SRT/Cast/DLNA/Miracast), Chrome.

## What does not
Hardware H.264 decoding (shows repeated frames). Anything not listed above has not been tested.

## Privacy
No personal data, credentials or firmware are published. Run [`tools/scan-privacy.sh`](tools/scan-privacy.sh) before every
commit. The image carries a locked placeholder account; the first-boot window asks for your own user name, password and
host name, so there are no default credentials.

## License
GPL-3.0-or-later for original work; third-party patches keep their upstream licences. See
[`LICENSE`](LICENSE), [`NOTICE.md`](NOTICE.md) and [`THIRD_PARTY.md`](THIRD_PARTY.md).
