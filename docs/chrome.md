# Google Chrome on the S9

Chrome is Google's proprietary package, so it is **not** in the release ZIP: the first boot downloads the arm64 `.deb`
from Google as soon as the phone has a network (`s9-install-chrome`, retried every 30 s, see
[`installing.md`](installing.md)). This page is about how it draws on the screen, which changed once the Adreno 630 worked
natively on KGSL.

## Today: Chrome on X11, with native Freedreno (FD630)
Chrome is started as a normal X11 program (`--ozone-platform=x11`) and uses the same graphics path as every other GL program
of the desktop ([`gpu-and-display-path.md`](gpu-and-display-path.md)):

```
Chrome (ANGLE on Mesa, Freedreno FD630 on KGSL)
  └─ DRI3 → patched Xwayland :0 (client buffers imported as dma-bufs)
       └─ gralloc backend → android_wlegl → Mir
```

* For Mir, Chrome is just another X11 window: the Docklike dock, Alt+Tab, minimize and the window frame treat it like Thunar.
* The GL environment (Mesa prefix, `GBM_BACKENDS_PATH`, EGL vendor file, `MESA_LOADER_DRIVER_OVERRIDE`, ...) is inherited from
  the desktop session. A Chrome started from outside the session does not have it; `system/usr/local/sbin/s9-chrome-x11`
  contains a launcher (`start.sh`) that copies that environment from the running `xfce4-panel` and removes everything that
  belongs to the old shim.
* The author's own launcher is just `google-chrome-stable %U` (the stock command) started inside the session, so the
  inherited environment does the work. The `s9-chrome-x11` helper script (`aplicar` / `reverter`) is kept in the repository
  but is **not** used by the author, because `aplicar` rewrites the `.desktop` file and patches the dock helper.
* Checked on the author's phone (28 October 2026), `chrome://gpu`: compositing **hardware**, WebGL hardware (no "reduced
  performance"), Turnip listed as a WebGPU adapter. The GPU sandbox is off in this mode (Mesa creates threads before the
  sandbox starts), which is a security cost, not a speed cost.
* **Not checked:** `chrome://gpu` on a freshly installed release image. The Chrome that the first boot installs starts from the
  package's stock `.desktop` file, which should behave the same way, but nobody has looked.
* **No hardware video decoding** in Chrome: the list of accelerated profiles is empty, so 1080p H.264 costs about two CPU cores
  ([`video-playback.md`](video-playback.md)).

## Before: Wayland Chrome with an EGL shim (kept as a historical plan B)
Before the Xwayland patches and Freedreno on KGSL existed, a stock Xwayland could only give software GL, so Chrome was run as
a native **Wayland** client of Mir with a small EGL shim:

* GPU: ANGLE on GLES over Android's own EGL through libhybris (`EGL_PLATFORM=wayland`, `HYBRIS_EGLPLATFORM=wayland`, the
  vendor library path of `userland/usr/local/bin/s9-chrome-gpu-hybris-env`). The shim's launcher was
  `/opt/s9-chrome-eglshim/start-stable.sh`; **its source is not in this repository** (it only exists on the author's phone).
* Result: the GPU was used, but compositing stayed in software (`disabled_software`), WebGL/WebGPU "reduced performance".
  Chromium's Ozone/Wayland wants GBM and dma-buf, Mir 1.8.3 only offers `wl_shm` and `android_wlegl`, and Android's EGL has no
  `EGL_EXT_image_dma_buf_import` (see the notes in [`gpu-and-display-path.md`](gpu-and-display-path.md)). In-process GPU,
  extra sandbox flags, GPU-rasterisation toggles and the `performance` governor gave no gain. It still reached about 60 fps on
  ordinary pages.
* Because Chrome was a Wayland client, the rest of the system needed special parts that exist **because of it**:
  * a control socket in the shell and a proxy X11 window made by `s9-docklike-ewmh.py`, so the Docklike dock (which only
    sees X11 windows) could show, focus and minimize Chrome; the shell also placed its maximized window around the panel;
  * the clipboard bridge (`s9-clipbridge` + the Mir `data_device` patch), which carries the text and images copied in a Wayland
    client to the X11 CLIPBOARD and back.
* The bridge is switched off by the file `/etc/s9-docklike/chrome-bridge.off` (marker `S9_CHROME_BRIDGE_SWITCH_V2` in the
  helper). To go back to the shim, remove the file and restart the Docklike helper **and** MirAL together; restarting only the
  helper leaves the dock opening a new Chrome at every click.

## The two modes, measured once
One run per side, 20 s of manual scrolling, 8 cores, so this is a hint and not a benchmark:

| | Wayland + shim | X11 + FD630 |
|---|---|---|
| Compositing | software only | hardware |
| WebGL | reduced performance | hardware |
| WebGPU | no | Turnip adapter listed |
| Chrome CPU while scrolling | 0.89 core (compositor thread 0.44) | 0.61 core (compositor thread 0.08) |
| Hardware video decoding | none | none |

## What the old mode left behind in the code
Still in the repository, unused by Chrome today but harmless: the Chrome code of `shell/s9_miral_shell.cpp` (markers
`S9_CHROME_*`), the proxy of `userland/usr/local/libexec/s9-docklike-ewmh.py` (off while the flag file exists),
`s9-chrome-gpu-hybris-env`, and `s9-clipbridge`, which remains useful for any other Wayland client.
