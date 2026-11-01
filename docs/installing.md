# Installing (status: in progress)

**Honest status:** the author has one working device that was assembled step by step over weeks.
The pieces below exist as scripts, but the complete chain (image builder -> flash -> first boot)
has **not been run end to end by anyone**. Treat this page as a plan with working parts, not as a
tested guide. Flashing can leave the phone unbootable.

## Requirements
* Samsung Galaxy S9 **SM-G9600** (not Exynos models, not S9+ / SM-G9650 without changes).
* Unlocked bootloader and TWRP for the device; a full backup of EFS, modem, boot, system, vendor
  and data **made by you**.
* A Linux PC (x86_64) with ~30 GB free, `debootstrap`, `qemu-user-static`, `adb`, Python 3.
* The stock firmware images **from your own phone or a source you are licensed to use**. This
  project never ships them.

## Stages
| # | Stage | Where | State |
|---|---|---|---|
| 1 | Extract firmware/vendor blobs from your phone (read-only) | `kernel/halium-graft/` | scripts from the author's device, adapt to yours |
| 2 | Build kernel and boot image | `kernel/scripts/` | used by the author |
| 3 | Build the Ubuntu 24.04 arm64 rootfs, Mir/Xwayland from the patches | `kernel/scripts/build-rootfs-stage1.sh`, `mir/`, `platform/`, `xwayland/`, `shell/` | partially scripted |
| 4 | Put the S9 overlay into the rootfs and create your account | `installer/s9-apply-overlay` | **tested on a scratch directory only** |
| 5 | Flash from TWRP, with hash read-back and the previous boot image kept for rollback | `docs/display-ultrawide.md` (procedure) | manual |
| 6 | First boot: ask for user/password/host name/time zone/keyboard | `installer/s9-firstboot`, `s9-firstboot.service` | **tested non-interactively on a scratch directory only** |

## The overlay: `system/` and `userland/`
These two trees mirror the target file system (`system/etc/...`, `system/usr/local/sbin/...`,
`userland/usr/local/bin/...`). Files that mention the desktop account contain placeholders
(`@S9_USER@`, `@S9_UID@`, `@S9_HOME@`); `TEMPLATES.txt` in each tree lists them.

`installer/s9-apply-overlay --root DIR --conf FILE` copies both trees into `DIR`, fills the
placeholders from the configuration file (see `configuration.md`), sets host name, time zone,
locale and keyboard, creates the account with `useradd --root` (no chroot, so it works for an
arm64 rootfs on an x86 PC), and enables the units listed in `installer/enabled-units.txt` with
`systemctl --root`. Sudoers files are syntax-checked and removed if invalid.

`installer/s9-firstboot` asks the questions and calls the above; with `--conf FILE` and
`S9_PASSWORD_HASH` in the environment it runs without a terminal (for the image builder).
The password is hashed with `openssl passwd -6` and never written to disk in clear text.

### Binary layout the units expect
The development phone keeps every experiment in its own `/opt/s9-...-vNN` directory and selects
one with a systemd drop-in. The published unit `s9-miral-nested.service` is the flattened result
and expects one fixed layout, produced by the build steps:

| Path | Content | Built from |
|---|---|---|
| `/opt/s9-ubports/lib/` | patched Mir libraries (`libmir1server.so.53`, ...) | `mir/` |
| `/opt/s9-ubports/platform/graphics-android2.so.16` | Android/GPU Mir platform | `platform/` |
| `/opt/s9-ubports/shell/s9-miral-shell` | window manager | `shell/` |
| `/opt/s9-xwayland-gralloc/Xwayland.wrapper` | Xwayland with the gralloc backend (bind-mounted over `/usr/bin/Xwayland`) | `xwayland/` |
| `/opt/mesa-kgsl-peekaboo/` | Mesa with Freedreno on KGSL | upstream Mesa + KGSL work by third parties (not included) |

The Mesa build, Chrome, Wine/Office and similar large third-party software are **not** part of this
repository; `docs/gpu-and-display-path.md` and `docs/windows-apps-and-memory.md` describe how they
were obtained and what they need.

## What the installer will not do
It does not ship or download Android firmware, vendor blobs or any Samsung software, and it does
not set up Wi-Fi networks, mobile-data (APN) settings or accounts for you. Those are entered on
your device afterwards through NetworkManager and the modem menu.
