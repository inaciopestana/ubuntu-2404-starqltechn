# Notices and provenance

Original work in this repository (scripts, documentation, the custom shell logic, the tray
panel, installer) is licensed under **GPL-3.0-or-later** (see `LICENSE`) unless a file says
otherwise. **Patches keep the licence of the code they modify.** This project combines many
upstream components and asserts no ownership over them.

| Path | Derived from | Licence of the upstream code |
|---|---|---|
| `mir/patches/` | Mir 1.8.3 with UBports packaging patches (`mir/BASE.txt`) | GPL-2/3 and LGPL-2.1/3 depending on the file (Canonical Ltd. and contributors) |
| `shell/` | Mir `miral-shell` example | GPL-3 (Canonical Ltd.) |
| `platform/patches/` | `ubports/development/core/hybris-support/mir-android2-platform` | GPL / LGPL (see its `COPYING.*`) |
| `xwayland/` | X.Org Xwayland 24.1.6 + `lfdevs/xwayland` series | MIT/X11 |
| `kernel/patches/`, `kernel/halium.config` | Linux kernel (Samsung sdm845 tree via `FakeShell/android_kernel_samsung_sdm845`) | GPL-2.0 only |
| `kernel/deviceinfo`, `kernel/halium-graft/` | UBports/Halium community-port tooling and the `Gustavo2Toledo/ubuntu-touch-star2qltechn` S9+ port | as upstream |

## Not included, on purpose
* Samsung/Qualcomm firmware and vendor blobs, Android system/vendor images, the stock kernel
  and boot images. The installer must read them from **your own phone**. The phone must keep
  its Samsung stock firmware (the author's: `G9600ZHU9FVF2`, Android 10); this project never
  modifies or ships the `system` partition.
* The Halium Android container image `android-rootfs.img` (Halium 10, build 1439) **is included** in the root image of
  the release ZIP. It is the generic `halium_halium_arm64` artifact of the UBports CI (halium-10.0), obtained through the
  V7 release of `Gustavo2Toledo/ubuntu-touch-star2qltechn`, whose build script fetches it from the UBports CI (that
  repository itself states no licence). Halium is built from open sources (LineageOS/AOSP: Apache-2.0 and GPL parts;
  see https://halium.org). Whether the file is byte-identical to the UBports artifact has not been checked yet.
* The Adreno 630 GPU firmware (`a630_sqe.fw`, `a630_gmu.bin`). These are Qualcomm files that Samsung ships in the phone's
  `vendor` partition. Images built by `tools/image/` leave them out, and a first-boot service
  (`s9-install-gpu-firmware`) copies them from **your own phone's** vendor partition (`/android/vendor/firmware`).
* Google Chrome and the Mesa KGSL package from *ImPeekaboo/mesa-a630-kgsl*; they are referenced and installed from their original sources.

## Credits
UBports and the Lomiri/Halium communities; Canonical (Mir/MirAL); X.Org; the `lfdevs`
projects (Xwayland and Mesa for Android containers); ImPeekaboo (Mesa A630 KGSL packaging);
FakeShell (Snapdragon 845 Samsung kernel); Gustavo2Toledo (Galaxy S9+ community port whose
structure this port started from); the libhybris, ofono-sailfish and pulseaudio-modules-droid
maintainers.

Samsung, Galaxy, Qualcomm, Snapdragon, Adreno, Google are trademarks of their
owners. This project is not affiliated with or endorsed by any of them, nor by UBports or
Canonical.
