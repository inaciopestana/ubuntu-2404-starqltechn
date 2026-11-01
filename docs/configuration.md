# Configuration: `/etc/s9-ubports.conf`

Every script and unit in this repository reads user-specific values from one file instead of
hard-coding them. It is created by the first-boot installer (`installer/s9-firstboot`) and can be
edited later; most values are read each time a script runs.

```sh
# /etc/s9-ubports.conf   (shell syntax, no spaces around '=')
S9_USER=alice            # the normal desktop user
S9_UID=1000
S9_HOME=/home/alice
S9_KEYMAP=br             # XKB layout used by the compositor (e.g. us, br, de, fr)
S9_KEYMAP_VARIANT=abnt2  # optional
S9_LOCALE=en_US.UTF-8
S9_TZ=America/Sao_Paulo
S9_HOSTNAME=s9
S9_DISPLAY_LAYOUT=auto   # auto | internal-only | external-ultrawide
S9_UW_HZ=60              # refresh rate for 3840x1080 (see display-ultrawide.md)
```
How the values are used today:

* `S9_USER`, `S9_UID`, `S9_HOME` are filled into the scripts, units, sudoers and polkit rules
  **when the overlay is installed** (`installer/s9-apply-overlay`); changing them later means
  re-running the installer.
* `S9_KEYMAP`, `S9_KEYMAP_VARIANT` and `S9_USER` are also read at run time by the window manager
  (`shell/`): environment first, then this file. The default layout without a file is `br`.
* `S9_LOCALE`, `S9_TZ`, `S9_HOSTNAME` are applied once by the installer to the usual system files.
* `S9_DISPLAY_LAYOUT` and `S9_UW_HZ` are **reserved: no script reads them yet.** The ultrawide mode is
  chosen in `/etc/s9-miral.display` (see `display-ultrawide.md`).

Secrets (Wi-Fi, APN passwords) never go in this file: use NetworkManager connections and the
`s9-modem` settings on the device, and keep them out of anything you publish.
