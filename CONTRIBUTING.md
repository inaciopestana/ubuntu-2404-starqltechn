# Contributing

Contributions are welcome, especially from people with another Snapdragon 845
Samsung (SM-G960x/SM-G965x, S9/S9+) or other Halium 10 devices.

* **Open an issue first** for anything bigger than a typo, describing the
  device model, firmware version and what you observed.
* Keep patches small and say which upstream file they apply to; Mir, Xwayland
  and kernel changes are kept as patches, not as full copies of those trees.
* Scripts must not hard-code a user name, IP address, Wi-Fi name or device
  serial. Use `/etc/s9-ubports.conf` (see `docs/configuration.md`).
* Before every commit run `tools/scan-privacy.sh`. Never commit images,
  firmware/vendor blobs, logs or backups.
* By contributing you agree your original work is licensed under
  GPL-3.0-or-later (patches to third-party code keep that code's licence).

## Language
Documentation is in English. Some code comments, log lines and a few UI strings in the scripts
under `system/` and `userland/` are still in Brazilian Portuguese (the author's language); they
are being translated over time. Do not change user-visible strings in a drive-by edit without
checking the application that shows them.
