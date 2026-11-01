# Security policy

This is experimental hobby software for one phone model. It changes boot,
display, audio and permission settings at a low level. Do **not** use it for
anything where device compromise would be costly.

## Reporting a vulnerability

Please open a **private security advisory** on GitHub
("Security" tab -> "Report a vulnerability"). Do not post exploit details in
public issues. Expect a best-effort response; this is a one-person project.

## Things to know before installing

* The installer creates a normal user with the password **you** choose. There
  are no default credentials in this repository and none must be added.
* A few helper programs run as root through narrow `sudoers` rules
  (`system/etc/sudoers.d/`: DeX fan, modem, screen cast, power-off menu). Review them
  before installing; the account may run those listed commands as root without a password.
* The shipped LightDM snippet (`system/etc/lightdm/lightdm.conf.d/50-s9.conf`) **logs the
  account in automatically**, which is convenient on a phone but means anyone holding it
  unlocked-at-boot gets your session. Remove that file if you want a login prompt (a graphical
  login/lock screen is not implemented yet).
* No SSH server is configured by this repository. The USB gadget script (`s9-usb-rndis`)
  offers a USB network interface to a connected computer; do not enable remote login on it
  without setting up keys.
* Never publish logs, `/etc/NetworkManager/system-connections`, IMEI/serial
  numbers, EFS/modem backups or Wi-Fi/APN settings in issues. Run
  `tools/scan-privacy.sh` on anything you plan to attach.
