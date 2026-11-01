# Bugs found in Mir 1.8.3 / Xwayland integration, and the fixes

Mir 1.8.3 (UBports build) was never meant to host a full X11 desktop. Most of the work in
`mir/patches/0002-s9-mir-1.8.3-cumulative.patch` is the result of tracking down the bugs below.
Each entry gives the symptom, the root cause and the marker you can `grep` for in the patch
and in the compositor log (use `grep -a`; the log contains binary bytes).

## 1. Wrong keyboard layout in X11 apps after boot (`S9-SEAT`)
* **Symptom:** after a cold boot with the dock/keyboard plugged in late, X11 apps used the `us`
  layout (AltGr was `Mod1` instead of `Mod5`, so `/`, `?`, `ç` failed on a Brazilian keyboard).
  Chrome (Wayland) was fine; restarting only the compositor hid the problem.
* **Cause:** `frontend_wayland/wl_seat.cpp` stored a new keymap but never sent it to the
  `wl_keyboard` objects that already existed. Xwayland starts together with the shell and binds
  to the seat while the keymap is still the default; the real host keyboards appear seconds to
  minutes later.
* **Fix:** when the seat keymap changes, push `wl_keyboard.keymap` to every registered keyboard
  on the Wayland thread. The shell also sets the layout at start (`S9_KEYMAP`, see
  `configuration.md`) and inverts the mouse wheel for non-touchpad devices (`S9-SCROLL`).
* **Not a fix:** `setxkbmap` on a live X server leaves modifier maps inconsistent.

## 2. Tray menus stayed on screen for about a second (`S9-XUNMAP`)
* **Symptom:** GTK menus that are hidden rather than destroyed (Wi-Fi, notification plug-in)
  lingered ~1 s after closing; audio and battery menus closed at once.
* **Cause:** `XWaylandWM::handle_unmap_notify` tested `event->response_type & ~0x80` (true for
  every real event) instead of `& 0x80` (the synthetic-event bit), so a real unmap returned
  before `surface->close()`. The surface only disappeared when Xwayland destroyed it later.
* **Fix:** use `& 0x80`; log `S9-XUNMAP` once.

## 3. Notifications with the wrong size or position (`S9_XWAYLAND_NOTIF_V1..V5`)
* **Goal:** `xfce4-notifyd` popups at the bottom right, above the panel, without frame
  buttons, full size, stacked.
* **Changes:** notification windows are recognised by `_NET_WM_WINDOW_TYPE` or, before it exists,
  by `WM_CLASS`, and are not server-side decorated; they are moved above the panel inset;
  ordinary windows that arrive at (0,0) are centred (`S9-XWCENTER`).
* **Real bug (V5):** in the "no surface yet" branch of `configure_request`, missing fields of a
  request were filled from a cache that was only updated by the asynchronous `ConfigureNotify`.
  With a cached icon `notifyd` sends two back-to-back requests; the second one re-applied the old
  geometry and shrank the popup. The cache is now written before `configure_window`.
* Location and timeout come from the XFCE settings, not from this project.

## 4. Crash: "window ready" callback after the X11 window vanished (`S9_READY_GUARD_V1`, shell)
`BasicWindowManager::add_surface` registers a surface-ready observer that keeps a reference into
a map; if the X11 window disappears before its first commit the callback uses freed memory, and
`info_for()` throws `std::out_of_range` through libwayland's C frames. The shell now guards the
callback.

## 5. Crash: race between the decoration constructor and the executor (`S9_DECOR_CTOR_GUARD_V1`)
* **Symptom:** intermittent `SIGSEGV`/`SIGABRT` of the compositor (heap corruption), more often
  under heavy load. Two cores showed the same program counter inside
  `Renderer::Text::Null` destruction.
* **Cause:** `BasicDecoration`'s constructor does a full `update()` and, with the window-growth
  patch (`S9_DECOR_GROW_V1`), resizes the window. That triggers `window_state_updated()` /
  `input_state_updated()` on the executor thread while the constructor is still modifying the
  same state.
* **Fix:** a global, mutex-protected set of decorations under construction; while an object is in
  it, those two callbacks re-queue themselves and return. No lock is held during construction.
  Only `basic_decoration.cpp` changes (no header change, to keep the ABI). The log line is
  `S9_DECOR_CTOR_GUARD_V1: ... deferred` (first 20 only). `S9_DECOR_BUFFER_GUARD_V1` also refuses
  to draw a frame into a buffer that is too large (`Failed to draw SSD: buffer too large`).
* **Status:** the guard fired many times after deployment, so the race was real. Long-term
  stability is still being observed; a later library adds `S9_XWOBS_WAIT_V1` for a related
  Xwayland-observer race.

## 6. Dock "minimize" never worked (`S9_DOCKLIKE_PANEL_GEOM_V1`, helper)
* **Cause:** the Docklike helper decided whether a click was "on the panel" using the screen
  height cached when it connected; after a late dock/monitor hot-plug that value was stale, so
  every click was rejected (`S9_DOCKLIKE_REJECT reason=not-on-panel`).
* **Fix:** read the current root geometry and only consider thin, mapped `xfce4-panel` windows.
* **Related CPU bug:** the Chrome-bridge switch returned before updating its poll timestamp, so
  the event loop never slept (63-77 % of a core, 1 % after the fix).

## 7. Other Mir changes (short list)
Dock click handling via `_NET_ACTIVE_WINDOW` (`S9_XWACTIVATE_MODE`), focus re-entry
(`S9_FOCUS_REENTER_V1`), size guard for X11 windows (`S9_XWAYLAND_SIZE_GUARD_V1`), a fixed
16 px software cursor (`S9_FIXED_CURSOR_SIZE_16`), host-pointer confinement
(`S9_HOST_POINTER_CONFINE_V1`) and the clipboard bridge (`S9_CLIPBRIDGE_V1`, `S9_CLIP_UID`,
`S9_CLIP_SOCKET`).

## Method that worked
* Prove where the time or the state goes before changing code: timeline of X requests from the
  Mir log, `strace`, and `xinput test-xi2 --root` for modifier state.
* Roll out one library/shell layer at a time with a rollback ready (see
  `compositor-and-window-manager.md`); verify the running build by hashing
  `/proc/<MainPID>/exe` and the mapped library, not the file on disk.
* Keep core dumps (`LimitCORE=infinity`, `core_pattern` to `/var/crash/s9cores`): see
  `system/etc/systemd/system/s9-miral-nested.service.d/90-debug.conf.example`.
