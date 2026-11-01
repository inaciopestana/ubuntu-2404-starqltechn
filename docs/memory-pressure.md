# Memory pressure and the Android low-memory killer

**Status: works on the author's phone.** The phone has 4 GiB of RAM. A memory-hungry application (a browser with many
tabs, a large build) can be killed by the Android kernel before Linux's own out-of-memory handling gets involved.

## Why a program gets "Killed": the Android low-memory killer
The 4.9 Samsung kernel still has Android's `lowmemorykiller`:
* It looks at free memory *and* page cache, ignores swap, and sees roughly 300 MiB less
  "free" than `/proc/meminfo` shows; under pressure both values go negative.
* This kernel compares the `adj` threshold **directly** with the process `oom_score_adj` (no
  conversion), so with `adj=0,1,6,12` it still killed a process at `oom_score_adj` 900.
* Setting `minfree=0` or `adj=16` does not disable it.

## What works (each with a rollback script)
1. `s9-lmk-tune.service` re-applies every 3 s `adj=1000,1000,1000,1000` (only processes with
   `oom_score_adj >= 1000` are eligible) and the original `minfree`. Config: `/etc/s9-lmk.conf`.
2. Xwayland, the shell and the system compositor are protected at `oom_score_adj` -500 (`s9-oom-protect.service`), so
   the desktop survives while an application is the one that is killed.
3. A 4 GiB swap file with zswap (zstd, pool in RAM) and `swappiness=60`; written-back pages
   stayed near zero, so flash wear is negligible.

`Killed` printed by a program = the LMK; confirm with
`dmesg | grep -A5 'lowmemorykiller: Killing'`.
