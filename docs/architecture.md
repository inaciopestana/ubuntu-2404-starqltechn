# Architecture and how the project was built

## What this is
A way to run a **full Ubuntu 24.04 desktop (XFCE)** on a Samsung Galaxy S9 (SM-G9600,
Snapdragon 845, Adreno 630) on top of the **Halium 10** Android hardware layer used by
Ubuntu Touch, with an external 3840x1080 monitor (DeX-style dock), audio, mobile data, calls
and SMS. It is a personal, community-style port; it is **not** an official UBports or Samsung
product.

## Layers
```
 hardware: SD845, Adreno 630, UFS, modem/ADSP firmware (vendor blobs, from the phone itself)
 kernel : Samsung 4.9 (FakeShell/android_kernel_samsung_sdm845, branch ubports)
          + halium.config + local patches (ultrawide DisplayPort, vidc, build tools)
 Android : Android 10 vendor + system images run as an LXC container (HALs only, no framework)
 Ubuntu  : Ubuntu 24.04 (noble, arm64) rootfs; UBports packages for libhybris/Mir/ofono/pulse-droid
 graphics: lomiri-system-compositor (owns the display through HWC)
             └─ nested Mir 1.8.3 + MirAL "s9-miral-shell" (this repo: mir/, platform/, shell/)
                  └─ Xwayland 24.1.6 with a gralloc/android_wlegl backend (xwayland/)
                       └─ XFCE 4.18 session, Docklike taskbar, Chrome, Thunar, ...
 audio   : PulseAudio with the droid modules (HIDL) talking to the Android audio HAL
 phone   : ofono-sailfish + binder plugin -> Android radio HAL
 extras  : s9-panel tray launcher, DeX fan control, screen cast, clipboard bridge
```
Why nested? The Android HWC allows exactly one client to own the display. Lomiri's system
compositor is that client, and a second Mir instance runs inside it so that the desktop can be
restarted without losing the display and so that window-management code can be changed freely.

## Build recipe in outline
1. **Kernel** - take the Halium-patched Samsung sdm845 tree, apply `kernel/halium.config`
   and `kernel/patches/`, build in an Ubuntu 22.04 chroot with the Android GCC 4.9 toolchain,
   assemble a boot image reusing the stock header values (`kernel/scripts/s9-kbuild5.sh`).
2. **Root filesystem** - `debootstrap --foreign --variant=minbase noble` under `qemu-aarch64-static`
   (`kernel/scripts/build-rootfs-stage1.sh`), then the UBports 24.04-2.x repository, then
   `kernel/halium-graft/` (adapts a reference Halium device's graphics/audio setup to the S9)
   and `kernel/rootfs-overlay/`.
3. **Mir stack** - rebuild only the changed objects of Mir 1.8.3 inside the arm64 chroot
   (`mir/patches/`), relink `libmir1server`, `libmir1al` and the `s9-miral-shell` binary.
4. **Xwayland** - build 24.1.6 from `lfdevs/xwayland` plus `xwayland/*.diff` (needs a newer
   `xorgproto` than the chroot's; build it into a private prefix).
5. **Userland** - install the scripts, systemd units, udev/sudoers/polkit rules (`system/`,
   `userland/`).

## Milestones (October 2026)
| Date | Milestone |
|---|---|
| 7-14 | nested MirAL desktop integrated (Oct 7); gralloc fixes, software cursor, host-pointer lock/confine work (Oct 14) |
| 16-21 | XFCE panel popup/menu placement and calendar popups (libs v23/v24); shell V25+ (maximize, Chrome docklike, keyboard/scroll input V33) |
| 20-21 | 3840x1080 over DisplayPort; Chrome GPU diagnostics; mobile data via ofono; tray menus close fast |
| 22 | clipboard bridge; notifications; Bluetooth/NM tray; calls/SMS app; fan controller |
| 25-27 | ADSP/boot reliability; screen cast (SRT/Cast/DLNA/Miracast); full-screen without panel; window frames for panel dialogs; native Freedreno GL via gralloc Xwayland |
| 28-31 | crash guards in the Mir lib (v49-v51); tray panel; Alt+Tab; Thunar pin; idle-CPU cleanup |

## Design principles that emerged
* **Additive and reversible**: every deployed change lives next to the old one with a rollback
  script; nothing is overwritten in place.
* **Patch, do not fork**: third-party trees are kept as patches against a named base so they
  stay auditable.
* **Measure first**: most "performance" ideas (in-process GPU, rasterisation flags, governors)
  gave nothing; frame-level checks (not buffer counts) found the broken video decoder.
* **No credentials, ever**: user-specific values live in `/etc/s9-ubports.conf`.

## Known limits
* Mir 1.8.3 only: no `zwp_linux_dmabuf_v1`, no `wp_viewporter`.
* Hardware video decode is broken (see `video-playback.md`).
* Kernel 4.9: no `kcmp`, no `dma_heap`; Android's low-memory killer is active.
* Single device, single tester. Expect rough edges.
