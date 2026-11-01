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
* **NetworkManager applet**: only one tray instance, via a small launch shim.
* **Notifications**: `xfce4-notifyd` works through the patched Mir (notification windows are
  recognised so they are not framed or stolen focus from).
* **Menus closing slowly** was an X11 unmap handling issue in the Mir XWM, fixed in the lib.

## Performance housekeeping
* CPU/GPU governor `performance` is applied on purpose (a timer re-applies it because the
  Android HAL changes it).
* `module-suspend-on-idle` for the droid sinks and a logrotate rule for the compositor log
  removed the largest idle CPU/IO sources (see `audio-and-boot-reliability.md`).
* Load average counts uninterruptible kernel threads (`secdp_event_thread`, a `kworker`
  sleeping in `msleep`); it is not CPU use.
