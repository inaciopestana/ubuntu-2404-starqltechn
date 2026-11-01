# External display: 3840x1080 ultrawide over DisplayPort

**Status:** working on the author's SM-G9600 with two different DeX-style docks and a
32:9 monitor (Samsung Odyssey G93SC). Without the patch the phone picks 3840x2160@60.

## Root cause
* Samsung's `secdp` DisplayPort driver (`CONFIG_SEC_DISPLAYPORT=y`) filters EDID modes
  through the table `secdp_supported_resolution[]` in `drivers/gpu/drm/msm/dp/dp_drm.c`.
  The 3840x1080 rows (60/100/120/144 Hz, `MON_RATIO_32_9`) are compiled out by two
  macros in `secdp.h` (`SECDP_WIDE_32_9_SUPPORT`, `SECDP_HIGH_REFRESH_SUPPORT`).
* The monitor's EDID only contains 3840x1080@120 (pixel clock 583.2 MHz). 120 Hz needs
  about 14 Gbit/s, i.e. HBR2 x4; one of the docks only negotiates fewer lanes and showed
  no picture. At 60 Hz with reduced blanking (about 266 MHz) the link needs ~6.4 Gbit/s.
* Mir's Android platform only knows the HWC's *active* mode (a one-entry list), so
  `mode:` in the Mir display config cannot change the mode by itself. The kernel therefore
  lists only the ultrawide mode.

## The patch (`kernel/patches/0003-msm-dp-ultrawide-3840x1080-and-no-hdcp.patch`)
* Enables the two macros (and defines `SECDP_HDCP_DISABLE`: the TrustZone never authenticates HDCP here, and the
  re-authentication loop cost about a quarter of one CPU core).
* `dp_connector_get_modes`: if the sink offers 3840x1080, synthesize 3840x1080@60 with
  `drm_cvt_mode(..., 60, reduced=true)` and enable a filter.
* `dp_connector_mode_valid`: reject anything that is not 3840x1080 at the chosen rate
  (monitors without a 3840x1080 mode are not affected).
* Module parameter `s9_uw_hz` (default **60**; 120 = EDID native, only with a 4-lane link;
  0 = filter off), under `/sys/module/*/parameters/`. It applies after replugging the cable.
* Known limitation: if the rate exists but the link cannot carry it, there is no fallback
  (blank screen). Lower `s9_uw_hz` and replug.

## Building and flashing a kernel
See `kernel/scripts/s9-kbuild5.sh`, `s9-kpatch5.sh`, `s9-flash-boot5.sh`. The lessons:
* Build in an Ubuntu 22.04 chroot (the host `make` of a very new distro fails in
  `scripts/Makefile.lib`). Use the Android GCC 4.9 cross compiler.
* Do not let a helper script re-sync the kernel tree to another commit; it drops local patches.
* Boot image: Android header v0, page size 4096. Re-use the arguments of the *current* boot
  image (`unpack_bootimg --format=mkbootimg`), replace only `--kernel`, append
  `SEANDROIDENFORCE`, pad to the 64 MiB partition. `mkbootimg` zeroes `second_addr`; keep the
  original header and patch only `kernel_size` and the id (this is why
  `deviceinfo_bootimg_force_second_address="true"` exists).
* Always verify: header identical apart from size/id, ramdisk byte-identical, kernel equals
  the freshly built `Image.gz-dtb`, expected symbols present.
* Flash from TWRP with `dd` to the `boot` partition, read back and compare SHA-256. Keep a
  backup of the working boot image so rollback is the same procedure.

## Open items
* HDCP authentication failures (`HDCP_STATE_AUTH_FAIL`) and some link-instability
  warnings in dmesg were observed and not investigated.
