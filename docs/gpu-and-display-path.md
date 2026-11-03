# GPU acceleration and the display path

The Adreno 630 is driven by Android's KGSL kernel driver (`/dev/kgsl-3d0`) with ION
buffers, not by DRM. There is no `/dev/dri` render node for the GPU (`renderD128` is the
display controller). Everything below is a consequence of that.

## What is installed in the working system
| Layer | Choice |
|---|---|
| Compositor | Mir 1.8.3 + MirAL (`s9-miral-shell`) *nested* inside Lomiri System Compositor, which owns the screen through the Android HWC. |
| Mir platform | `graphics-android2` (UBports `mir-android2-platform`) + local patches (`platform/`). |
| X11 | Xwayland 24.1.6 built from `lfdevs/xwayland` (commit `0c42ac5`) + local gralloc/DRI3 patches (`xwayland/`). |
| GL for the desktop | Freedreno **native on KGSL** (Mesa 24.3 from the *ImPeekaboo/mesa-a630-kgsl* package, `GL_RENDERER = FD630`, OpenGL 4.6 compat). |
| Vulkan | Turnip on KGSL (Mesa 25.2.8). Zink/Turnip is the fallback for GL. |

## Why the obvious routes did not work
* **Mir 1.8.3 has no `zwp_linux_dmabuf_v1`.** It only advertises `wl_shm` and
  `android_wlegl` (served by libhybris). The `dmabuf` protocol appeared in Mir 2.1 and only
  for the GBM/KMS platform. Upgrading Mir to 2.x would require porting the system
  compositor, the Android platform and the window manager (2.0 removed `mirclient`,
  `host-socket` and `nested-passthrough`).
* **Android's EGL does not expose `EGL_EXT_image_dma_buf_import`.** It has
  `EGL_ANDROID_image_native_buffer`, `EGL_HYBRIS_*` and `EGL_WL_*` instead.
* Stock Xwayland therefore falls back to software GLX (llvmpipe) and `wl_shm` copies.

## The route that works: gralloc buffers over `android_wlegl`
1. A gralloc allocation (`hybris_gralloc_allocate`) yields a `native_handle` (ION dma-buf fd
   + metadata fd + 22 ints).
2. Mesa/KGSL can import the ION fd (`EGL_LINUX_DMA_BUF_EXT`, fourcc `AB24`) and render into it.
3. The same handle is handed to Mir with the `android_wlegl` protocol
   (`create_handle`, `add_fd`, `create_buffer`). Mir accepts and releases these buffers even
   from a client that is not libhybris' EGL (proved with a hand-written client).
4. Measured at 3840x1080/60 Hz: Mir CPU ~10 % with gralloc buffers vs ~67 % with `wl_shm`.

### Xwayland patches (`xwayland/xwayland-24.1.6-lfdevs-s9.diff`)
* **0008 gralloc backend** (`XWAYLAND_GRALLOC=1`): window backing pixmaps are gralloc
  buffers imported as EGLImages, presented to Mir with `android_wlegl`; glamor runs on the
  GPU; EGL is initialised through the *gbm* platform (the `surfaceless` platform fails in
  this Mesa build). `glFinish` is used instead of fences because `android_wlegl` has no fence.
  Depth 24 uses RGBX_8888, depth 32 RGBA_8888; Mesa always imports as ABGR8888.
* **0009 DRI3 for clients** (`XWAYLAND_GRALLOC_DRI3=1`): client buffers are imported as
  dma-bufs and copied by Present into the window pixmap (no direct flip).
* A guard so Xwayland does not assert when glamor initialisation fails.

Practical numbers on the real desktop: `glxgears` (vsync off) 1452 fps on native FD630 vs
676 fps on Zink/Turnip, same Xwayland CPU.

### Gotchas worth remembering
* Never extract the Mesa package into `/`; use an isolated prefix (`/opt/mesa-kgsl-peekaboo`).
* The user must be in the group **`android_graphics`** (GID 1003): `system/etc/udev/rules.d/99-s9-gpu.rules` gives that group
  `/dev/kgsl-3d0` and `/dev/ion` (mode 0660). Without the membership the GPU is root-only and every GL client falls back or
  fails (`glmark2` reported no KGSL access). The release image builder keeps this group when it scrubs the author's accounts and
  blocks the build if the placeholder account is not a member (`tools/image/tests/test-gpu-group.sh`). Check on a phone:
  `id` (must list `android_graphics`) and `glxinfo -B | grep renderer` (must say FD630).
* The package needs LLVM 19 (`libllvm19`, Debian trixie) while Ubuntu 24.04 has 20: unpack it
  into a sub-prefix with `dpkg -x`; put it on `LD_LIBRARY_PATH`.
* Set `GBM_BACKENDS_PATH` to the package's own gbm directory or the system `dri_gbm.so`
  drags in the system Mesa and crashes with an ABI mismatch.
* Clients of the *system* Mesa without the Zink override fail under DRI3 (the fd is KGSL, not
  DRM); native or Zink GL clients work.
* Copying a binary over a running Xwayland fails with `Text file busy`: copy to `.new` and
  `mv -f`.
* `glmark2` in a window crashed the desktop with a GPU page fault; benchmark off-screen
  (`--off-screen -s 800x600`) and without the `terrain` scene (hangs Turnip 25.2.8).
* The wrapper must tolerate an unwritable log file; an `exec ... 2>>log` that fails stops
  Xwayland from starting.

## Browser
Chrome runs as a normal X11 program on the native Freedreno path above (compositing and WebGL on the GPU); the old Wayland
+ EGL-shim setup, which kept compositing in software, is history. Details, numbers and how to go back:
[`chrome.md`](chrome.md).

## Open items
* Fences instead of `glFinish`; unexplained slowdown of some 2D operations (copy/scroll) vs
  software; exporting dma-bufs from native Freedreno (legacy ION ABI) is unproven.
