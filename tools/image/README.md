# Building the flashable ZIP

`build-image.sh` turns a backup of a working phone (the backup script is not in this repository yet; the layout it must produce is described in the header of `build-image.sh`) into a ZIP that TWRP installs:
the boot image plus the Ubuntu root image written into `userdata`. Run it as root on a Linux PC.

## Release build (what users get)

```
sudo tools/image/build-image.sh --backup ~/s9-backups/<backup> --boot <boot-clean.img> --out ~/s9-images \
     --mode clean --first-boot-account --prune-opt-unreferenced \
     --halium-sha256 527c53fd8e27957fe4046cd8588d689dec338e8abb6531af4602c2f235ca0944
```

`tools/image/build-release.sh` wraps this: it runs the regression tests in `tests/`, refuses an installer template with the
known busybox traps, calls `build-image.sh` with exactly these options (re-running itself with `sudo`), and then verifies the ZIP
(CRC, installer text, boot image hash, parts, `.sha256`, no `PRIVATE` in the name). `build-release.sh --verify-zip FILE` does
only that last step, on any ZIP:

```
tools/image/build-release.sh --backup ~/s9-backups/<backup> --boot <boot-clean.img> --out ~/s9-images
```

It never uploads anything.

* **The ZIP is built from the phone backup, not from this repository.** A change committed here (an icon, a script) is in the
  ZIP only if the backup already has it. `repo-sync.list` closes that gap: the files named in it are copied from the
  repository over the extracted tree before the scrub and the audit, so a fix can ship without a new backup (and the log shows
  `installed <path>` for each). Remove an entry once the backup you build from has the same file. `tests/test-repo-sync.sh`
  checks that the listed files exist and that they replace the backup's copy with the right owner and mode.
* `audit-tree.py` removes personal data (Wi-Fi, keys, browser profiles, logs, call/SMS history, caches, the author's
  account), leaves Chrome, other closed-source applications and the Qualcomm GPU firmware out, and then **audits** the result.
  A blocking finding stops the build.
* The image carries a **locked placeholder account** (`s9user`). On the first boot a window asks for the user name, the
  password and the host name; `s9-firstboot-apply` renames the account everywhere it is referenced (the list is recorded
  at build time in `rename.json`), sets the password and the host name, and restarts the phone. The password is hashed
  immediately and never stored in clear.
* The scrub drops every account and group of the author, **except the groups named by the image's own udev rules**
  (`android_graphics`, GID 1003, owns `/dev/kgsl-3d0` and `/dev/ion`): the placeholder account is kept as a member, and
  the first-boot wizard renames it. Without that group the GPU is root-only and OpenGL fails. The audit blocks the build
  if such a group is missing or the account is not a member; `tools/image/tests/test-gpu-group.sh` checks both.
* NetworkManager must not manage `usb0`/`rndis0` (the USB debug network), `swlan0` (the Wi-Fi AP interface: it shares its MAC with `p2p0`, which only works with its own MAC while `swlan0` is left alone) or `p2p0` (the
  Wi-Fi driver's own Wi-Fi Direct interface: it looks like Ethernet, so NetworkManager made a "Wired connection 1" there that
  never got an address). `clean-overlay/etc/NetworkManager/conf.d/` carries the files (`unmanaged-devices+=`, never a plain
  `=`: a later `=` replaces the list built by the earlier files), the audit reads the effective list and blocks the build
  if one of the four is missing, and `tools/image/tests/test-nm-unmanaged.sh` checks it.
* First-boot services also grow the root file system, create the ssh host keys, copy the Adreno 630 firmware from the
  phone's own `vendor` partition and install Google Chrome from Google's direct arm64 `.deb` once there is network.

## Private test build

`--user NAME` instead of `--first-boot-account` creates the account at build time (password asked for, or
`--password-hash-file`). `--allow-blob GLOB` lets named files through the audit; the ZIP is then named
`...-PRIVATE-do-not-publish-...`.

## Flashing

Copy the ZIP to a **microSD card or USB-OTG drive** (the installer refuses to run from the internal storage, which it
overwrites) and install it from TWRP. See the front page of the repository for the full sequence.

### Without a microSD card: USB cable and `adb`

Boot TWRP and connect the phone to the PC (`adb devices` must say `recovery`). Two ways:

1. **`adb sideload`.** In TWRP, Advanced > ADB Sideload (or `adb shell twrp sideload`), then `adb sideload s9-....zip` on the
   PC. The installer is the same one as above; it accepts this because the sideloaded copy is not on `userdata`.
   **Tested on a real phone** with the ~1 GB ZIP (about 9 minutes, `Total xfer: 1.93x`): TWRP serves the file on demand, it
   does not keep it in RAM. The installer log is in `/tmp/recovery.log` (search for `TWRP installer`); `Total xfer: 0.00x`
   means the installer stopped at once, the reason is the `ERROR:` line in that log. If `adb sideload` fails with timeouts
   (`ioctl bulk write Fail : Connection timed out`), connect the phone through a USB 2.0 hub.

   The installer runs in TWRP's busybox: its `[` compares integers with 32 bits (so a size above 2 GiB must be compared
   inside `$(( ))`) and its `unzip` has no `-t`. Keep the script free of both.
2. **`flash-from-pc.sh`.** It reads the sizes and SHA-256 values from the installer script inside the ZIP, then does what the
   installer does, but from the PC (nothing is copied to the phone except the 64 MiB boot image):

   ```
   tools/image/flash-from-pc.sh s9-....zip            # optional: --serial SERIAL, --method exec-in|nc, --port N
   ```

   It checks the device (`starqltechn`, boot = `sda20`, userdata = `sda29`), unmounts `userdata`, asks you to type `FLASH`,
   streams the root image into `userdata` (1 MiB offset), reads it back and compares the SHA-256, and only then writes `boot`
   and verifies it. If anything differs it stops before touching `boot`, and tells you not to reboot into Ubuntu.
   The stream goes through `adb exec-in` when your `adb` has it, otherwise through `adb forward` plus `nc -l` in TWRP.
   Tested here only against a stand-in `adb` on a PC (small files, both methods), **not on a real phone**.

Either way the ZIP is verified before anything is written, and `system`, `vendor`, modem and `efs` are never touched.
