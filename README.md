# Ubuntu 24.04 + XFCE on the Samsung Galaxy S9 (SM-G9600)

A community experiment that runs a **full Ubuntu 24.04 desktop** (XFCE) on a Snapdragon 845
Galaxy S9 using Halium 10, with GPU acceleration (Adreno 630), external display support,
audio, mobile data, calls and SMS.

**The idea: the Galaxy S9 as a portable PC.** The system was designed to run with the phone plugged into a monitor
(through a DeX-style dock) and used with a **mouse and a keyboard**. The touch screen works, but it is not what the
desktop was made for, and **there is no on-screen (virtual) keyboard** in this project: without a physical keyboard you
cannot type.

> **Status: experimental, one device, one tester.** Everything here comes from the author's
> own SM-G9600 (G9600 = Snapdragon S9, China/Hong Kong variants). The author went from this port back to stock Android and
> installed it again twice; the second time with nothing but the files of the [Releases](../../releases) page, and it worked
> with no problem, so the installation path below is known to work on that phone. Nobody else has repeated it yet.
> Flashing a kernel or boot image can make a phone unbootable, and the ZIP **erases `userdata`** (Android's data). Back up
> EFS, modem and boot partitions first and only continue if you accept that risk. See [`docs/installing.md`](docs/installing.md).

## Installation at a glance
Everything you need is on the [Releases](../../releases) page. Full steps, risks and the way back: [`docs/installing.md`](docs/installing.md).

1. **Stock Android 10 on the phone** (PDA `G9600ZHU9FVF2`) with the **bootloader unlocked**, and the phone online once so the
   *OEM unlocking* item shows (otherwise Odin says `FAIL! (Auth)`). Not there yet:
   [`docs/returning-to-android.md`](docs/returning-to-android.md) (Odin on Windows, `odin4` on Linux).
2. **TWRP:** flash `twrp-3.7.0_9-0-starqltechn-settings-cache.tar` in Download Mode (Odin, AP slot, or `odin4 -a`), then boot
   straight into it. It is TeamWin's TWRP with one change so it keeps its settings on `/cache`
   ([`tools/twrp/`](tools/twrp/README.md)).
3. **Disabler:** in TWRP, `adb shell twrp sideload` and `adb sideload S9_G9600_disabler-and-encryption-removal.zip`. It turns off
   Samsung's boot-time checks and the forced encryption of `userdata` ([`tools/twrp/disabler/`](tools/twrp/disabler/README.md)).
   Do not boot Android afterwards.
4. **Ubuntu:** again `adb shell twrp sideload`, then `adb sideload s9-clean-*.zip` (about 9 minutes; no microSD card needed;
   a card also works). It writes the root and boot images with SHA-256 read-back and **erases `userdata`**. Build it yourself
   with [`tools/image/build-release.sh`](tools/image/README.md).
5. **First boot:** a window asks for your user name, password and host name, then the phone restarts.

The five steps describe the author's setup on one phone. The boot image is built from FakeShell's
[`android_kernel_samsung_sdm845`](https://github.com/FakeShell/android_kernel_samsung_sdm845) (branch `ubports`, Linux 4.9.186)
plus [`kernel/patches/`](kernel/patches/README.md).

### What the release ZIP contains, and what it does not
* **Contains:** the boot image (Linux 4.9.186 with the patches of this repository) and the Ubuntu 24.04 root image: XFCE, the
  patched Mir/MirAL desktop, Xwayland, Freedreno/KGSL Mesa, the Halium 10 Android container, telephony and audio stack. The
  licences and the places to get the source of every part are in [`THIRD_PARTY.md`](THIRD_PARTY.md).
* **Does not contain:** Samsung/Qualcomm firmware (the Adreno 630 firmware is copied at the first boot from your own phone's
  `vendor` partition), Google Chrome (downloaded from Google at the first boot, so it needs Wi-Fi or mobile data), and any
  personal data of the author.
* The ZIP is built by [`tools/image`](tools/image/README.md) from a backup of the author's phone, passes an automatic
  privacy audit and was inspected afterwards. Earlier builds had two bugs found on a phone and fixed (GPU device group, no pointless wired
  connection on `p2p0`); use the ZIP of the newest release.

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
Hardware H.264 decoding (shows repeated frames). There is no on-screen keyboard (see the top of this page). Anything not
listed above has not been tested.

## Privacy
No personal data, credentials or firmware are published. Run [`tools/scan-privacy.sh`](tools/scan-privacy.sh) before every
commit. The image carries a locked placeholder account; the first-boot window asks for your own user name, password and
host name, so there are no default credentials.

## License
GPL-3.0-or-later for original work; third-party patches keep their upstream licences. See
[`LICENSE`](LICENSE), [`NOTICE.md`](NOTICE.md) and [`THIRD_PARTY.md`](THIRD_PARTY.md).

## Credits and thanks
None of this would exist without the people and projects below. This is their work; this repository only joins it, patches
it for one phone and documents how. Licences and the exact source of every part: [`THIRD_PARTY.md`](THIRD_PARTY.md) and
[`NOTICE.md`](NOTICE.md). If a credit or a link is wrong or missing, please open an issue.

**The port and its base**
* [FakeShell](https://github.com/FakeShell/android_kernel_samsung_sdm845): the Snapdragon 845 Samsung kernel tree (branch `ubports`) this kernel is built from.
* [Gustavo2Toledo](https://github.com/Gustavo2Toledo/ubuntu-touch-star2qltechn): the Galaxy S9+ community port whose structure this port started from, and the route to the Halium 10 Android container.
* [UBports](https://gitlab.com/ubports) and the [Halium](https://halium.org) community: the Halium 10 container, the Mir Android platform ([`mir-android2-platform`](https://gitlab.com/ubports/development/core/hybris-support/mir-android2-platform.git)), libhybris and the 24.04 package repository ([repo.ubports.com](http://repo.ubports.com/)).
* [Canonical](https://github.com/canonical/mir): Mir and MirAL, the compositor this desktop is built on.

**Graphics**
* [ImPeekaboo](https://github.com/ImPeekaboo/mesa-a630-kgsl): the Mesa build with Freedreno on KGSL that gives the Adreno 630 its OpenGL.
* [lfdevs](https://github.com/lfdevs): the Xwayland patch series for Android containers and the Mesa builds for Android containers ([`mesa-for-android-container`](https://github.com/lfdevs/mesa-for-android-container)).
* [X.Org](https://www.x.org/): Xwayland 24.1.6, the X server every X11 program here runs on (Chrome, Thunar, Wine, the XFCE panel). The patches that let it draw into Android graphics buffers and give clients DRI3 are applied on top of the X.Org source, and they only work because of its glamor and DRI3 code ([`docs/gpu-and-display-path.md`](docs/gpu-and-display-path.md)).
* [Mesa](https://www.mesa3d.org/): Freedreno (the OpenGL driver for the Adreno 630, talking to the phone's KGSL driver), Turnip (Vulkan), Zink and llvmpipe, which the GPU path and the fallbacks are made of.

**Telephony, audio and Bluetooth**
* [Mer / Sailfish OS](https://github.com/mer-hybris) hybris projects ([`libgbinder`](https://github.com/mer-hybris/libgbinder), [`bluebinder`](https://github.com/mer-hybris/bluebinder), [`pulseaudio-modules-droid`](https://github.com/mer-hybris/pulseaudio-modules-droid)) and the Sailfish OS fork of [ofono](https://git.kernel.org/pub/scm/network/ofono/ofono.git) (`ofono-sailfish`), packaged by UBports.
* [libhybris](https://github.com/libhybris/libhybris).

**Desktop**
* [Ubuntu](https://ubuntu.com/) 24.04 and [Xfce](https://www.xfce.org/) 4.18: the session, the panel, Thunar and the notification daemon (`xfce4-notifyd`) the desktop is made of; the [docklike plugin](https://gitlab.xfce.org/panel-plugins/xfce4-docklike-plugin) by David Keogh (via the [xubuntu-dev/extras PPA](https://launchpad.net/~xubuntu-dev/+archive/ubuntu/extras)).

**Installing and flashing**
* [TeamWin](https://twrp.me/): TWRP, the recovery everything is installed from ([`twrp-3.7.0_9-0-starqltechn`](https://dl.twrp.me/starqltechn/twrp-3.7.0_9-0-starqltechn.img.html)).
* [Ragekill3377](https://github.com/Ragekill3377/Odin4-GUI): Odin4-GUI, a graphical front end for `odin4`, the Linux build of Samsung's Odin; `odin4` is how the author flashed from Ubuntu (see [`docs/returning-to-android.md`](docs/returning-to-android.md)).
* **Ian Macdonald** (Multi-disabler) and **@klabit87** (forceencrypt_remover_Q-mod), whose scripts are merged in [`tools/twrp/disabler/`](tools/twrp/disabler/README.md); both came from [this XDA post](https://xdaforums.com/t/kernel-upstream-kernelsu-susfs-s9-s9-n9-chn-usa.4703239/post-90032616).
* [Magisk](https://github.com/topjohnwu/Magisk) (`magiskboot`, used to patch the recovery image).

Samsung, Galaxy, Qualcomm, Snapdragon, Adreno and Google are trademarks of their owners. This project is not affiliated with
or endorsed by any of them, nor by UBports or Canonical.
