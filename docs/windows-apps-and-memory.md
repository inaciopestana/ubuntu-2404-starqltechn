# Windows applications (box64 + Wine) and memory pressure

**Status: experimental, and not part of the release ZIP** (the image builder leaves Wine, box64, hangover and Office out;
this page describes the author's own phone). Wine 11.x (WoW64) runs under box64 0.4.4 with the Dynarec. The
Wine4Office installer is used for the runner/prefix management; the Office suites themselves
are **not** distributed or installed by this project.

## Things that were needed
* `libxkbregistry0` (native arm64). Without it `winex11.so` fails to load, the driver is
  missing and `winecfg` exits without a window (WineHQ bug 55999).
* Running `box64 wine ...` directly from the runner's `bin/` creates a stray `~/.wine`; keep
  the managed prefix (`~/.wine4office`) separate.
* The first start under box64 is slow (tens of seconds; a fresh prefix ~2 minutes).
* Zink/Turnip works inside Wine (`GL_RENDERER = zink Vulkan 1.3 (Turnip Adreno 630)`,
  `winevulkan` lists the GPU). Messages about EGL/DRI3 failures come from `winex11` probing
  EGL first and are harmless. **Never force `UseEGL=N`** - it took the whole graphical
  session down. With the gralloc/DRI3 Xwayland the EGL path may work now; untested.

## Why Wine got "Killed": the Android low-memory killer
The 4.9 Samsung kernel still has Android's `lowmemorykiller`:
* It looks at free memory *and* page cache, ignores swap, and sees roughly 300 MiB less
  "free" than `/proc/meminfo` shows; under pressure both values go negative.
* This kernel compares the `adj` threshold **directly** with the process `oom_score_adj` (no
  conversion), so with `adj=0,1,6,12` it still killed a process at `oom_score_adj` 900.
* Every Wine process under box64 can reach 450-680 MiB RSS (JIT regions of 100-340 MiB).
  Peak anonymous memory was ~2.3 GiB of 3.5 GiB.
* Setting `minfree=0` or `adj=16` does not disable it.

What works (each with a rollback script):
1. `s9-lmk-tune.service` re-applies every 3 s `adj=1000,1000,1000,1000` (only processes with
   `oom_score_adj >= 1000` are eligible) and the original `minfree`. Config: `/etc/s9-lmk.conf`.
2. Wine processes run at `oom_score_adj` 900 through a wrapper; Xwayland, the shell and the
   system compositor are protected at -500 (`s9-oom-protect.service`).
3. A 4 GiB swap file with zswap (zstd, pool in RAM) and `swappiness=60`; written-back pages
   stayed near zero, so flash wear is negligible.

`Killed` printed by a program = the LMK; confirm with
`dmesg | grep -A5 'lowmemorykiller: Killing'`.

## Pitfalls
* Never pipe Wine's output (`| head`): helper processes inherit the pipe and nothing exits.
* Wine processes rename themselves; `pgrep -f box64` does not find them.
