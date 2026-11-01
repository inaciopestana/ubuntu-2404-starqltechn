# Ubuntu 24.04 + XFCE on the Samsung Galaxy S9 (SM-G9600)

A community experiment that runs a **full Ubuntu 24.04 desktop** (XFCE) on a Snapdragon 845
Galaxy S9 using Halium 10, with GPU acceleration (Adreno 630), external display support,
audio, mobile data, calls and SMS.

> **Status: experimental, one device, one tester.** Everything here comes from the author's
> own SM-G9600 (G9600 = Snapdragon S9, China/Hong Kong variants). The installer and image builder are still
> being written and have **not been tested by anyone else**. Flashing a kernel or boot image can
> make a phone unbootable. Back up EFS, modem and boot partitions first and only continue if you
> accept that risk. See `docs/installing.md`.

## Installation at a glance
Five steps, in this order. Details, risks and the way back are in [`docs/installing.md`](docs/installing.md).

1. **Samsung stock Android 10 on the phone, with the PDA (AP) build `G9600ZHU9FVF2`**
   (`QP1A.190711.020`, security patch 2022-05-01). Flash it with Odin if the phone is on another build.
   The `system`, `vendor` and modem partitions stay exactly as Samsung shipped them; this port never writes `system`.
2. **Unlock the bootloader** (Developer options > OEM unlocking, then the download-mode unlock). This wipes the phone and
   trips Knox.
3. **Install the custom TWRP that keeps its settings in `/cache`** (see [`tools/twrp/`](tools/twrp/README.md)).
   Ubuntu lives in a dedicated image inside the `userdata` partition, so TWRP cannot keep its settings there; the
   patched recovery stores them on `/cache` instead (one flag in `recovery.fstab`).
4. **In that TWRP, flash `multidisabler` and `forceencrypt_remover_q`** (two ZIPs, one after the other). They turn off
   Samsung's boot-time integrity checks and the forced encryption of `userdata`, which get in the way of a custom boot and root image.
5. **In the same TWRP, flash the Ubuntu ZIP.** It carries the boot image and the Ubuntu root image (the Halium Android
   container is inside the root image), and it writes them with read-back checks. Keep the ZIP on a **microSD card or
   USB-OTG drive, never on the internal storage**: the ZIP overwrites `userdata`, and the installer refuses to run from it.
   Build the ZIP yourself with [`tools/image/build-image.sh`](tools/image/build-image.sh); a ready-made release is not published yet.

> The five steps describe the author's setup on one phone. The patched TWRP and the two ZIPs of step 4 are the
> author's choice; the Ubuntu ZIP of step 5 has been built and checked on a PC but **not yet flashed on a phone**, and
> nobody else has repeated any step.

## What is in this repository
| Path | Content |
|---|---|
| `docs/` | how the system works and how it was built (start at `docs/architecture.md`) |
| `kernel/` | device config, kernel patches (incl. 3840x1080 DisplayPort support), build/flash scripts, Halium graft tooling |
| `mir/` | patches on Mir 1.8.3 (cumulative) |
| `platform/` | patch on the Mir Android/GPU platform |
| `xwayland/` | Xwayland gralloc + DRI3 patches |
| `shell/` | the custom MirAL shell (window manager) |
| `system/`, `userland/` | systemd units, udev/sudoers rules, helper scripts and apps |
| `installer/` | overlay installer and first-boot setup (tested on a scratch directory only) |
| `tools/image/` | builds the flashable TWRP ZIP (boot + Ubuntu root image) from a backup of the phone, with a privacy audit |
| `tools/twrp/` | patch and flash the TWRP that keeps its settings in `/cache` |
| `tools/` | other maintainer tools: privacy scan, export scripts |

## What works (on the author's device)
Desktop with window frames, dock, Alt+Tab, full-screen, clipboard (text/images) between Wayland native and
X11 apps, notifications, Bluetooth and Wi-Fi applets, external monitor with audio (ultrawide resolution supported), GPU-accelerated
GL via native Freedreno on KGSL, audio, mobile data, voice calls and SMS (with an app), DeX
fan control, screen casting (browser/SRT/Cast/DLNA/Miracast), Chrome.

## What does not
Hardware H.264 decoding (shows repeated frames). Anything not listed above has not been tested.

## Privacy
No personal data, credentials or firmware are published. Run `tools/scan-privacy.sh` before every
commit. The installer asks for your own user name and password on first boot; there are no
default credentials.

## License
GPL-3.0-or-later for original work; third-party patches keep their upstream licences. See
`LICENSE` and `NOTICE.md`.
