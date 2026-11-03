# One ZIP for `multidisabler` + `forceencrypt_remover_q`

The installation needs two things done in TWRP before the Ubuntu ZIP: Samsung's boot-time security services switched off, and
the forced encryption of `userdata` removed. Two community ZIPs do that. This directory merges them into **one** flashable ZIP
that applies them in the right order and prints a log.

| File | What it is |
|---|---|
| `update-binary` | the whole installer (a shell script for TWRP's busybox) |
| `build-zip.sh` | packs it into `S9_G9600_disabler-and-encryption-removal.zip`, reproducibly (same input, same SHA-256) |

The ZIP is also attached to the release.

## Credits (please read)
* **Multi-disabler v2.3** (`Multidisabler_S9_N9_1.zip`): **Ian Macdonald**. Part of the merged script is his script, with small
  changes (see below).
* **forceencrypt_remover_Q-mod**: **@klabit87**. The `fstab.qcom` that the merged script writes is the one from that ZIP, embedded
  verbatim (checked byte for byte against the original, 3449 bytes).
* Both were obtained from [this XDA post](https://xdaforums.com/t/kernel-upstream-kernelsu-susfs-s9-s9-n9-chn-usa.4703239/post-90032616).
* **The licences of the two originals have not been verified.** The merged script is a derivative of them, so it is not covered
  by this repository's GPL-3.0-or-later notice, and whoever redistributes it should check the original terms. If an author
  objects to this copy or states a licence, open an issue and it will be removed or fixed. The original ZIPs remain the
  reference; this one exists only so that the user flashes one file instead of two.

## What it does
In this order, and it stops at the first failure of step 1 without touching anything else:

1. **Encryption removal.** Replaces `/vendor/etc/fstab.qcom` with an fstab without `forceencrypt`/`fileencryption`. The
   replacement is written in place (so owner, mode and SELinux label stay), is checked before use (must mention
   `by-name/userdata` and no encryption flag), keeps the very first original as `fstab.qcom.orig`, and does nothing if the
   file is already replaced.
2. **The rest of Multi-disabler:** vaultkeeperd, process authentication (`proca`), `wsm` (Android 10 only), and the
   restoration of the stock recovery (on the firmware this port uses there is nothing to disable for the last one: there is no
   `recovery-from-boot.p`).

Changes against the original Multi-disabler, all because of how TWRP 3.7.0_9 behaves on this phone:
* It finds the system partition at `$ANDROID_ROOT`, `/system_root` or `/system`. In this TWRP `$ANDROID_ROOT` is `/system` but
  the partition is mounted at `/system_root` (system as root), so the original could not reach it and quietly skipped the
  system-side steps.
* It reads the Android version from the firmware's `system/build.prop`, because TWRP reports an empty
  `ro.build.version.release` (the original then skipped the `wsm` step without saying so).
* It logs everything to `/cache/s9-disabler.log`, and prints the device string it did not recognise when it refuses to run.

## Order in the installation
TWRP (the patched one) → **this ZIP** → either *Wipe > Format Data > yes* or the Ubuntu ZIP (which overwrites `userdata`
anyway). **Never boot Android between this ZIP and the next step**: the fstab no longer expects encryption but `/data` is still
encrypted, so Android could not read it.

## Flashing it
It is small, so no microSD card is needed. With the phone in TWRP and `adb devices` saying `recovery`:
```sh
adb shell twrp sideload; sleep 3
adb sideload S9_G9600_disabler-and-encryption-removal.zip
adb shell 'mount /cache 2>/dev/null; cat /cache/s9-disabler.log'
```
(or copy it to the microSD card and use TWRP > Install). A good log ends with `Finished`, and mentions
`fstab.qcom replaced and verified` (or `already replaced` on a second run).

To check it on the phone afterwards (read only):
```sh
adb shell 'mount /vendor 2>/dev/null; mount /system_root 2>/dev/null;
  grep -E "forceencrypt|fileencryption|encryptable" /vendor/etc/fstab.qcom; ls -l /vendor/etc/fstab.qcom.orig'
```
The `grep` must print nothing and the `.orig` file must exist.

## Tested
On the author's SM-G9600 with TWRP 3.7.0_9-0, firmware `G9600ZHU9FVF2`: the previous build of this script (identical code, only
two comments differ from the version in the repository) ran and its result was checked as above. **The exact file in this
directory was tested only in simulation** (a mock TWRP environment on a PC), not on a phone. One phone, one tester.

## Build
```sh
tools/twrp/disabler/build-zip.sh                 # writes S9_G9600_disabler-and-encryption-removal.zip here
```
