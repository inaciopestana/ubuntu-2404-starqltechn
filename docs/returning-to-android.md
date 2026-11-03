# Returning to stock Android 10 (and getting a clean phone for the install)

You need this page in two situations: you want your Android back, or you want to start the installation from a known
state (the procedure in [`installing.md`](installing.md) assumes stock Android 10, firmware `G9600ZHU9FVF2`).

> **This erases the phone.** Flashing the full firmware with the normal `CSC` file wipes `userdata`, and that is where the
> Ubuntu root image lives. Copy anything you want to keep first. Your own `efs`/`modem` backups are only needed if you
> damaged those partitions; a stock firmware flash does not need them.

The procedure below was run by the author on his SM-G9600 with an Ubuntu 26.04 LTS (x86_64) laptop and `odin4`, from a
phone that was running this port, back to stock, and then on to the patched TWRP. The Windows route is the standard Odin
procedure and was **not** used in that test.

## 0. What you need
* The **full stock firmware** for your model and region, from an official source (it is not distributed here). Four files:
  `BL_…`, `AP_…`, `CP_…` and `CSC_…`. For the build the port is based on they look like
  `BL_G9600ZHU9FVF2…`, `AP_G9600ZHU9FVF2…_meta_OS10…`, `CP_G9600ZCU9FVE3…`, `CSC_OMC_OWO_G9600OWO9FVF2…`.
* **Use `CSC_…`, not `HOME_CSC_…`.** `HOME_CSC` keeps user data, so the old Ubuntu root image would stay in `userdata`
  and the phone would not boot cleanly. `CSC` forces the wipe.
* A USB data cable. On Linux, **a USB 2.0 hub** (see the troubleshooting section: the author could not flash without one).

## 1. Put the phone in Download Mode
1. Power the phone off (if it boots into Ubuntu: hold Volume Down + Power until the screen goes dark).
2. Hold **Volume Down + Bixby**, and with both held plug the USB cable (the other end in the PC, or in the hub).
3. On the warning screen press **Volume Up** to continue. The screen says "Downloading…".

## 2a. Flash from Windows (Odin)
Odin 3.14.x: load the four files in `BL`, `AP`, `CP` and `CSC`, leave *Auto Reboot* and *F. Reset Time* checked and
*Re-Partition* unchecked, and press *Start*. The phone restarts into Android when the log says `PASS!`.

## 2b. Flash from Linux (`odin4`)
`odin4` is a Linux command-line build of Samsung's Odin. As far as the author knows Samsung does not offer it on its
download pages; it circulates in the community, so check where you got it from.

1. Stop ModemManager, which may try to open the phone's serial interface in Download Mode:
   ```sh
   sudo systemctl stop ModemManager
   ```
2. Go to the folder with the four files (extracted from the firmware ZIP) and run:
   ```sh
   odin4 -b BL_*.tar.md5 -a AP_*.tar.md5 -c CP_*.tar.md5 -s CSC_OMC_*.tar.md5
   ```
   `odin4` checks the MD5 of each file first (it prints `Check file … (100%)`), then flashes. If you pipe its output into
   `tee` the progress bar does not show; follow the progress on the phone screen instead.
3. If the phone does not restart by itself: `odin4 --reboot`.

`odin4 -l` lists the connected phones (`/dev/bus/usb/BBB/DDD`). It opens a session with the phone, so do not use it right
before a flash that is already failing: after any failed attempt, **restart the phone into Download Mode again** before the
next try. The USB device number goes up on every attempt (006, 030, 031…) because the phone re-enumerates.

### Odin4 GUI
There are graphical front ends that run the same `odin4` binary. The one the author looked at is a Python program using
`customtkinter`. Ubuntu refuses `pip install` into the system Python (PEP 668), so use a virtual environment:
```sh
sudo apt install python3-venv python3-tk
cd Odin4-GUI                                   # the folder with main.py
python3 -m venv --system-site-packages venv
venv/bin/pip install customtkinter
venv/bin/python main.py
```
This gets the window to start. The author did all his flashing with the command line above; **the GUI itself was not used
for a flash**, so if it misbehaves, use the command line.

### Troubleshooting `odin4`
* **`Setup Connection` → `ioctl bulk write Fail : Connection timed out 110` → `Fail Setup Connection`**, and in `dmesg`
  `usbfs: USBDEVFS_CONTROL failed cmd odin4 … ret -110` (later `-71`). `odin4 -l` still sees the phone, but nothing is
  written. This is what happened with the phone plugged straight into the laptop (a port on the xHCI root hub, 480 Mbit/s).
  **The only thing that fixed it was putting a USB 2.0 hub between the laptop and the phone.** Things that did *not* help:
  stopping ModemManager, unloading `cdc_acm` (`sudo modprobe -r cdc_acm`), turning USB autosuspend off
  (`power/control` = `on`), another cable, restarting Download Mode. Stop ModemManager anyway, it is harmless.
* **`md5 fail … Fail parse`** for a `.tar.md5` you made by hand: use a plain `.tar` (next section); `odin4` accepts it.
* **`FAIL! (Auth)`** when flashing a custom recovery: see the next section, the phone must have been online.

## 3. First boot of stock Android
Android needs a few minutes for the first boot after a wipe. Go through the setup wizard. Then:
* Enable Developer options (Settings > About phone > Software information > tap *Build number* seven times) and turn
  **USB debugging** on if you want to use `adb`.
* **Connect the phone to Wi-Fi and keep it online** (see below).

Check the bootloader state with `adb`:
```sh
adb shell getprop ro.boot.flash.locked          # 0 = unlocked
adb shell getprop ro.boot.verifiedbootstate     # orange = unlocked
```
`ro.boot.warranty_bit=1` only says that Knox was tripped once; it never goes back. On the author's phone
`ro.boot.vbmeta.device_state` and `ro.boot.veritymode` are empty on this firmware, which is normal. On Download Mode's screen
there is also an `OEM LOCK` line (not checked on that phone).

## 4. Flash the patched TWRP with `odin4`
After the stock flash the phone must **be online, with the *OEM unlocking* / bootloader unlock item visible in Developer
options**. On the author's phone that item appears only once the phone has been connected to the internet, and **until it
appears Odin refuses a custom recovery**:
```
Upload Binaries
recovery.img
Fail request receive -5
FAIL! (Auth)
Fail uploadBinaries
```
This failure happened with the bootloader already reporting `flash.locked=0` and `orange`, and with `sys.oem_unlock_allowed=1`, so
those properties do **not** tell you the flash will pass. The practical rule is: online first, item visible in Developer
options, then flash.

Download Mode again, then:
```sh
odin4 -a twrp-3.7.0_9-0-starqltechn-settings-cache.tar
```
The release carries that file ready to use ([`tools/twrp/README.md`](../tools/twrp/README.md)). Success looks like this:
```
Check file : …/twrp-3.7.0_9-0-starqltechn-settings-cache.tar
Setup Connection
initializeConnection
Receive PIT Info
success getpit
Upload Binaries
recovery.img
Close Connection
```
`odin4` does not restart the phone here. Do **not let Android start first**: the firmware has a `flash_recovery` service that
can restore the stock recovery on a normal boot (on the author's phone it should find nothing to restore, because there is
no `recovery-from-boot.p`, but going straight to TWRP costs nothing). Power off with Volume Down + Power (hold about ten
seconds until the screen goes dark) and, right away, hold **Volume Up + Bixby + Power** until the TWRP logo shows.

The next steps (disabler ZIP, Ubuntu ZIP) are in [`installing.md`](installing.md).

## Going back to Android from this port
Same as above: Download Mode and the four stock files with `CSC` (not `HOME_CSC`). Nothing of Ubuntu stays on the phone
afterwards, because the Ubuntu root image sits in `userdata` and the boot image is replaced by the stock one.
