# Compositor, window manager and desktop integration

## Process layout
```
Android HWC / KGSL
   └─ lomiri-system-compositor (s9-lsc.service)         owns the physical screens
        └─ MirAL "s9-miral-shell" (s9-miral-nested.service)   nested compositor + window manager
             ├─ Xwayland :0 (rootless, gralloc backend)        for all X11 apps
             ├─ clipboard bridge (s9-clipbridge.service)
             └─ XFCE session (xfce4-panel, Thunar, ...) started as the normal user
   helper: s9-docklike-ewmh.service  (EWMH bridge between Mir's X11 windows and the Docklike dock)
```
The XFCE session ends when `xfce4-panel` exits, so the panel must never be restarted with
`xfce4-panel -r`; restart the helper + MirAL instead.

## Source layout
* `mir/` - patches on top of Mir 1.8.3 (UBports packaging, commit in `mir/BASE.txt`).
  `0001` fixes a GCC 15 / protobuf 3.21 symbol-export problem; `0002` is the cumulative S9
  work: nested input-output transform, external-display policy, software cursor, window
  decorations for non-panel windows, X11 activation, clipboard bridge, XWayland fixes,
  logind seat adjustments.
* `platform/` - patch on UBports `mir-android2-platform` (display modes, hotplug, buffers).
* `shell/` - the custom MirAL shell (`s9_miral_shell.cpp`) built as an example next to
  `miral-shell`: copy it to `examples/s9-miral-shell/` of the patched tree and build.
* `xwayland/` - Xwayland patches (see `gpu-and-display-path.md`).

## Rolling out changes safely
Every change followed the same pattern, which is worth keeping if you extend the project:
1. A script with modes `patch` (preview only) / `build` (apply to the sources inside the ARM64
   chroot, compile only the changed objects and relink) / `deploy` (copy to the phone, do not
   activate) / `check` (grep markers in the binary).
2. The binary goes to its own directory under `/opt/`, never over the running one.
3. A systemd *drop-in* bind-mounts it over the expected path. Drop-ins are applied in
   lexical order, so each new version uses a file name with one more leading `z`; the last
   one wins. Only one library drop-in may be active at a time (the activate script checks).
4. `*-activate --yes` and `*-rollback --yes` scripts; rollback restores the previous drop-in.
   Activating restarts the nested compositor, which closes the XFCE applications.

## What the cumulative patch and shell implement
* **Full-screen**: when the active window (or its parent) is fullscreen the panel is lowered
  from the `above` layer so real full-screen works for every app.
* **Panel roles**: only the thin bar and its transient children count as "panel"; other
  windows of `xfce4-panel` (e.g. Panel Preferences) are ordinary windows and get decorations.
  Mir does not translate `_NET_WM_WINDOW_TYPE`; everything is `freestyle`, so roles are
  inferred from size and parent.
* **Decorations**: Mir's server-side decoration (enabled with `MIR_DECOR`) grew windows by the
  frame size before applying margins, so programs were not squeezed below their minimum size;
  the X11 content size requested by clients is converted back to window size.
* **Dock clicks on X11 windows**: Mir 1.8.3's XWM ignored `_NET_ACTIVE_WINDOW`
  (`// TODO`). The patch raises/restores/focuses on that message, and the Docklike helper
  decides minimize-vs-activate from a snapshot taken when focus leaves the list.
* **Alt+Tab**: `MinimalWindowManager::handle_keyboard_event` was extended with an MRU cycle
  that skips invisible desktop/panel windows (Alt+Shift+Tab reverses).
* **Clipboard**: Mir's `data_device` was a stub. Wayland selections (text, PNG/JPEG/BMP) go
  through a Unix socket to a small Python bridge that owns the X11 `CLIPBOARD`, and back.
  Only CLIPBOARD (no PRIMARY, no files).
* **Dock/menu/notification details**: popup positioning for panel wrappers, desktop menu
  handling, keyboard focus for child dialogs, and a guard against a crash when an X11 window
  disappears while its Mir surface is still being configured.

## Gotchas
* Restart the Docklike helper **and** MirAL together. This only matters if the old Wayland Chrome bridge is switched on
  (see [`chrome.md`](chrome.md); it is off by default): restarting only the helper then breaks it, and every click on the dock
  opens a new Chrome instance.
* `grep -a` is needed on the compositor log (it contains binary bytes).
* Do not edit a library or binary that a running service has mapped; deploy next to it and
  switch through the drop-in.
* The first Mir X11 window is not the desktop: the shell treats desktop and panel windows as
  non-focusable when cycling windows.
