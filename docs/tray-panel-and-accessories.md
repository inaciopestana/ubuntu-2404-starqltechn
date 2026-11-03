# The S9 tray panel and other accessories

## `s9-panel` (system-tray launcher)
A single tray icon opens a 480x800 window with six tiles: **Telephony**, **SMS**,
**Screen Cast (DLNA)**, **Screen Cast (Wi-Fi Direct)**, **Mobile Data**, **DeX Station Fan**.
* Python/GTK3 `Gtk.Application` (single instance). Closing the window only hides it.
* Tray icon: a hand-written StatusNotifierItem over Gio/D-Bus with `ItemIsMenu=false`.
  XFCE 4.18 calls `Activate(x,y)` on click (it double-fires within 1 s, so the handler
  debounces 0.6 s). AppIndicator cannot be used because it only opens menus.
* Phone/SMS pages embed a second copy of the phone app (`s9-telefone --embed`) using
  `Gtk.Socket.add_id(xid)`; this works under Xwayland/MirAL with `GDK_BACKEND=x11`. The
  embedded copy is silent (the background instance rings and notifies).
* `s9-panel.service` waits for the user's `xfce4-panel`, copies its graphic environment and
  runs the panel as that user.

### GTK pitfalls found
1. `Gtk.Stack` makes the first *already visible* page the initial one; call `show_all()` then
   `set_visible_child_name('home')`.
2. `Gtk.Socket` is only realized when visible; show its page before calling `add_id`.
3. A just-created child window may not exist on the X server yet; call `Display.sync()` in
   the child and retry the plug a few times.

## DeX Station fan
`s9-dex-fan` sends the fan level to the DeX dock over USB-PD vendor messages, driven by the
phone's temperature (levels off/low/medium/high with hysteresis and a minimum dwell time,
configurable in `/etc/s9-dex-fan.conf`; changes are re-read every cycle). A tray control
offers Auto/High/Medium/Low/Off via fixed `sudo` commands.

## Other tray applets
* **Bluetooth (blueman)**: the black-window problem was an apport crash handler; started
  through a launcher that sets the right environment.
* **NetworkManager applet**: the stock `nm-applet`, unmodified, started by `s9-nm-applet.service`
  (`s9-nm-applet-autostart` only waits for the XFCE session and copies its environment). It handles Wi-Fi, Wi-Fi networks and
  VPNs; it has no mobile-data entry. See [Network icon and mobile data](#network-icon-and-mobile-data).
* **Notifications**: `xfce4-notifyd` works through the patched Mir (notification windows are
  recognised so they are not framed or stolen focus from).
* **Menus closing slowly** was an X11 unmap handling issue in the Mir XWM, fixed in the lib.

## Network icon and mobile data
**Now:** two separate things, each with a single job.
* The tray icon of the stock `nm-applet` is the network icon (Wi-Fi). Nothing is injected into it.
* **Mobile data** (and the screen-cast choices) are tiles of `s9-panel`. The *Mobile Data* tile runs the fixed
  `sudo -n s9-modem status | up [primary|backup] | down | on | off` commands (see
  [`telephony-and-modem.md`](telephony-and-modem.md)); the screen-cast tiles use `s9-cast`. NetworkManager still cannot talk to
  ofono, so it never shows the mobile connection.

**Before (historical):** mobile data and screen cast were entries of a *modified* `nm-applet` menu, so there was one network icon
in the tray. That needed three extra pieces:
* `s9-modem-menu.py` (+ `s9-modem-menu-launcher`, `s9-modem-menu.service`): a StatusNotifier item that mirrored the nm-applet
  dbusmenu over D-Bus and added the "Mobile Data" submenu after the Wi-Fi block;
* a small `LD_PRELOAD` library (`s9-sni-noregister.so`, about 30 lines of C, built on the phone) that made `nm-applet` skip
  `RegisterStatusNotifierItem`, so the XFCE panel did not draw a second, original icon;
* the panel `hidden-items` list was edited so the original icon did not show in the overflow arrow either.

The three pieces are not used any more. `s9-modem-menu.service` is not in [`installer/enabled-units.txt`](../installer/enabled-units.txt)
and `s9-nm-applet-autostart` starts a plain `nm-applet`. The files of the old route are still in the repository
(`s9-modem-menu.py`, `s9-modem-menu-launcher`, `s9-modem-menu.service`), only for reference; the shim library and its source are
not in the repository.

## Performance housekeeping
* CPU/GPU governor `performance` is applied on purpose (a timer re-applies it because the
  Android HAL changes it).
* `module-suspend-on-idle` for the droid sinks and a logrotate rule for the compositor log
  removed the largest idle CPU/IO sources (see `audio-and-boot-reliability.md`).
* Load average counts uninterruptible kernel threads (`secdp_event_thread`, a `kworker`
  sleeping in `msleep`); it is not CPU use.
