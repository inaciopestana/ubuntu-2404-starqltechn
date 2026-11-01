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
  account), leaves Chrome, Claude Desktop, Wine/Office and the Qualcomm GPU firmware out, and then **audits** the result.
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
