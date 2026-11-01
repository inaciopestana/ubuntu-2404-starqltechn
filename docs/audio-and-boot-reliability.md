# Audio, boot reliability and the clock

Four independent problems showed up around boot. Each has a small, separate fix.

## 1. The ADSP sometimes fails to load its firmware
* Symptom: no ALSA card (`sdm845-tavil-snd-card`), the audio service loops in `start-pre`.
* dmesg: `subsys-pil-tz ...lpass: adsp: Failed to locate adsp.mdt (rc:-11)`. The kernel's
  `firmware_class.path` is `/vendor/firmware_mnt/image`, but the blobs live in the modem
  firmware partition mounted at `/android/vendor/firmware-modem/image/`; when the direct
  lookup fails the kernel falls back to Android's `ueventd`, which occasionally drops the
  request (`-EAGAIN`). The loader never retries by itself.
* Manual fix (3 s):
  `echo -n /android/vendor/firmware-modem/image > /sys/module/firmware_class/parameters/path;
  echo 1 > /sys/kernel/boot_adsp/boot`.
* Permanent fix: `system/sbin/s9-adsp-ensure`, an `ExecStartPre` of the audio unit. It waits
  about 20 s for the card, then retries up to three times with the path redirected, and
  always exits 0. All Qualcomm subsystems use `restart_level=SYSTEM`, so a crash of the ADSP
  right after loading would reboot the phone; this has not been observed.

## 2. PulseAudio comes up with no sinks
Never let a shutdown script switch the Pulse card profile to `off`: `module-card-restore`
persists it and the next boot has zero sinks. Only `default` is safe to persist
(`voicecall`, `communication` and `ringtone` have hung Pulse before). The ordered-shutdown
script unloads `module-droid-card` and `module-droid-hidl` but keeps the profile.

## 3. Reboot loop to the vendor logo around 45 s
Pre-existing and not caused by audio: the modem blob load fails mid-image
(`pil-q6v5-mss: Failed to locate blob modem.bNN (rc:-11)`), the retry ends in a reset.
`s9-lastkmsg-save.service` keeps the previous session's `last_kmsg` and the first ~95 s of
dmesg for the last 12 boots so the pattern can be studied. Root cause not found.

## 4. Wrong date at every boot
The RTC (`qpnp_rtc`) holds no real date, so each boot starts in 2018/2019 until NTP
arrives. `s9-clock-keep` restores the last saved time at boot, saves every 60 s, and a guard
watches for the Android `time_daemon` stepping the clock backwards during the first four
minutes and puts it back.

## 5. Idle CPU: suspend-on-idle for the droid sinks
The droid sinks stay `IDLE` and keep writing silence into the audio HAL (which also floods
Android's `logd`). Loading `module-suspend-on-idle timeout=5` (guarded by `.nofail`) lets
them suspend; measured idle CPU dropped sharply. A logrotate rule keeps the compositor log
from growing without bound.

## Lessons
* Read state before deleting anything (a journal vacuum once discarded 448 MB of history).
* Mark `dmesg` with `echo MARK > /dev/kmsg` before an experiment instead of counting lines.
* Keep every fix as a separate script with a `--check` mode and a rollback script.
