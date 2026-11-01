# Building the flashable ZIP

`build-image.sh` turns a backup of a working phone (made with `tools/backup-phone.sh`) into a ZIP that TWRP installs:
the boot image plus the Ubuntu root image written into `userdata`. Run it as root on a Linux PC.

## Release build (what users get)

```
sudo tools/image/build-image.sh --backup ~/s9-backups/<backup> --boot <boot-clean.img> --out ~/s9-images \
     --mode clean --first-boot-account --prune-opt-unreferenced \
     --halium-sha256 527c53fd8e27957fe4046cd8588d689dec338e8abb6531af4602c2f235ca0944
```

* `audit-tree.py` removes personal data (Wi-Fi, keys, browser profiles, logs, call/SMS history, caches, the author's
  account), leaves Chrome, other closed-source applications and the Qualcomm GPU firmware out, and then **audits** the result.
  A blocking finding stops the build.
* The image carries a **locked placeholder account** (`s9user`). On the first boot a window asks for the user name, the
  password and the host name; `s9-firstboot-apply` renames the account everywhere it is referenced (the list is recorded
  at build time in `rename.json`), sets the password and the host name, and restarts the phone. The password is hashed
  immediately and never stored in clear.
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

1. **`adb sideload`.** In TWRP, Advanced > ADB Sideload, then `adb sideload s9-....zip` on the PC. The installer is the same
   one as above; it accepts this because the sideloaded copy is not on `userdata`. **Not tested:** TWRP keeps a sideloaded
   package in RAM, and this ZIP is about 1 GB, so it may not fit.
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
