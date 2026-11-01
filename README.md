# Ubuntu 24.04 + XFCE on the Samsung Galaxy S9 (SM-G9600)

A community experiment that runs a **full Ubuntu 24.04 desktop** (XFCE) on a Snapdragon 845
Galaxy S9 using Halium 10, with GPU acceleration (Adreno 630), external display support,
audio, mobile data, calls and SMS.

> **Status: experimental, one device, one tester.** Everything here comes from the author's
> own SM-G9600 (G9600 = Snapdragon S9, China/Hong Kong variants). The installer and image builder are still
> being written and have **not been tested by anyone else**. Flashing a kernel or boot image can
> make a phone unbootable. Back up EFS, modem and boot partitions first and only continue if you
> accept that risk. See `docs/installing.md`.

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
| `installer/` | overlay installer and first-boot setup (tested on a scratch directory only); image builder not written yet |
| `tools/` | maintainer tools: privacy scan, export scripts |

## What works (on the author's device)
Desktop with window frames, dock, Alt+Tab, full-screen, clipboard (text/images) between Chrome and
X11 apps, notifications, Bluetooth and Wi-Fi applets, external ultrawide monitor, GPU-accelerated
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
