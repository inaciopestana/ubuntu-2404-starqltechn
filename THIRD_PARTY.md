# Third-party software in the release ZIP, and where to get its source

The release ZIP (`s9-clean-*.zip`) contains a boot image and an Ubuntu 24.04 root image. Almost all of the root image is
unmodified software from the Ubuntu and UBports archives. This page lists what else is in it, under which licence, and
where the corresponding source code is. The original work of this repository is GPL-3.0-or-later (see `LICENSE`);
[`NOTICE.md`](NOTICE.md) describes how each directory of the repository was derived.

## What is in the ZIP

| Component | Licence (main) | Source |
|---|---|---|
| **Linux kernel 4.9.186** in `boot.img` (Samsung sdm845 tree) | GPL-2.0 only | [`FakeShell/android_kernel_samsung_sdm845`](https://github.com/FakeShell/android_kernel_samsung_sdm845), branch `ubports`, base commit `a22a0b358140`, plus [`kernel/patches/`](kernel/patches/README.md) and [`kernel/halium.config`](kernel/halium.config) of this repository |
| **Ramdisk** in `boot.img` (initramfs that maps the Ubuntu root) | GPL-2.0 and others (busybox, device-mapper) | [`kernel/ramdisk/`](kernel/ramdisk/README.md) of this repository; busybox-static and dmsetup from the Ubuntu archive |
| **Ubuntu 24.04 "noble" (arm64) packages**, about 1500 | per package (mostly GPL, LGPL, MIT, BSD) | the Ubuntu archive: `apt source <package>` on any Ubuntu system with `deb-src` enabled, or <https://ports.ubuntu.com/ubuntu-ports/pool/> |
| **UBports packages**: `audiosystem-passthrough`, `bluebinder`, `libgbinder`, `libgbinder-radio`, `libglibutil`, `libmce-glib`, `ofono-sailfish`, `ofono-binder-plugin`, `libofonobinderpluginext`, `pulseaudio-modules-droid` (+ `-hidl`, `-discover`), `gst-hybris`, `ubuntutouch-artwork`, libhybris and Lomiri system compositor | GPL / LGPL / BSD per package | the UBports 24.04 repository (`deb http://repo.ubports.com/ 24.04-2.x main`) and <https://gitlab.com/ubports> |
| **Mir 1.8.3** libraries and **MirAL**, patched | GPL-2/3 and LGPL-2.1/3 | upstream tarball and packaging named in [`mir/BASE.txt`](mir/BASE.txt) plus [`mir/patches/`](mir/patches/); Mir Android platform: [`platform/`](platform/) |
| **S9 MirAL shell** (`s9-miral-shell`) | GPL-3.0 | [`shell/`](shell/) of this repository, built against the patched Mir |
| **Xwayland 24.1.6** with gralloc and DRI3 patches | MIT/X11 | upstream X.Org source plus [`xwayland/`](xwayland/) (the `lfdevs/xwayland` series and this project's patches) |
| **Mesa 24.3 with Freedreno on KGSL** (`/opt/mesa-kgsl-peekaboo`, with the LLVM 19 libraries it needs) | MIT (Mesa), Apache-2.0 with LLVM exceptions (LLVM) | [`ImPeekaboo/mesa-a630-kgsl`](https://github.com/ImPeekaboo/mesa-a630-kgsl) |
| **Mesa Turnip/Zink** (`/opt/mesa-turnip-kgsl`), fallback GL path | MIT | `lfdevs` Mesa builds for Android containers |
| **Halium 10 Android container** (`/var/lib/lxc/android/android-rootfs.img`, build 1439, sha256 `527c53fd…ca0944`) | Apache-2.0 (AOSP/LineageOS), GPL-2.0 parts, others per file | <https://halium.org>; the UBports CI artifact `halium_halium_arm64` (halium-10.0); obtained through the V7 release of [`Gustavo2Toledo/ubuntu-touch-star2qltechn`](https://github.com/Gustavo2Toledo/ubuntu-touch-star2qltechn). Not checked byte for byte against the CI artifact. |
| **XFCE docklike plugin** (`xfce4-docklike-plugin`) | GPL-3.0 | the `xubuntu-dev/extras` PPA |
| Scripts, units and tools of this project | GPL-3.0-or-later | this repository |

## What is not in the ZIP

* **Samsung and Qualcomm firmware and vendor files.** The Adreno 630 firmware (`a630_sqe.fw`, `a630_gmu.bin`) is copied at
  the first boot from your own phone's `vendor` partition. `system`, `vendor`, the modem and `efs` are never written.
* **Google Chrome.** Downloaded at the first boot from Google's own `.deb` link once the phone has network.
* **The author's personal files**, accounts, keys, Wi-Fi networks, browser profiles and logs.
* **`multidisabler` and `forceencrypt_remover_q`**: not in the Ubuntu ZIP. A merged version of the two, with credits to
  Ian Macdonald (Multi-disabler v2.3) and @klabit87 (forceencrypt_remover_Q-mod), is a separate small ZIP in
  [`tools/twrp/disabler/`](tools/twrp/disabler/README.md), attached to the release. **The licences of the two originals have not
  been verified**; their source is the [XDA post](https://xdaforums.com/t/kernel-upstream-kernelsu-susfs-s9-s9-n9-chn-usa.4703239/post-90032616).
* **TWRP**: the release also carries a copy of TeamWin's TWRP 3.7.0_9-0 for `starqltechn` (an Odin tar) with the one-line settings
  change of [`tools/twrp/`](tools/twrp/README.md) (a separate file, not part of the Ubuntu ZIP). TWRP is GPL-3.0 and other free licences;
  source: <https://twrp.me/> and TeamWin's GitHub organisation. The unmodified original is at
  <https://dl.twrp.me/starqltechn/twrp-3.7.0_9-0-starqltechn.img.html>.
* **`odin4` and Odin4-GUI**: not in this repository or in the release. `odin4` is a Linux build of Samsung's Odin, which the
  author does not redistribute; the docs only point to [Odin4-GUI](https://github.com/Ragekill3377/Odin4-GUI) by Ragekill3377,
  whose README says it bundles it and states no formal licence.

## Written offer for source code

For every component above that is licensed under the GPL or LGPL, the corresponding source is available from the
locations in the table, and the exact patches this project applied are in this repository. If something cannot be found
there, open an issue on this repository and the maintainer will provide the missing source. This offer is valid for as
long as the ZIP is distributed from this repository.

The Linux kernel and the Mir libraries in the ZIP were built by the maintainer from the sources and patches named
above. Rebuild instructions: [`docs/installing.md`](docs/installing.md) (kernel and boot image) and
[`docs/compositor-and-window-manager.md`](docs/compositor-and-window-manager.md) (Mir, shell, Xwayland).

## Corrections

If any attribution or licence here is wrong or missing, please open an issue; it will be fixed.
