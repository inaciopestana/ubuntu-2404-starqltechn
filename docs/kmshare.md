# kmshare: use the PC's keyboard and mouse on the phone

A small Python tool (server on a PC, client on the phone) that grabs `/dev/input/event*` on the
PC (`EVIOCGRAB`, works under GNOME Wayland) and replays the events on the phone through
`/dev/uinput`, all inside an SSH tunnel. Toggle with ScrollLock; if the SSH link drops the
PC returns to local control and all keys are released. Not included: shared clipboard,
edge-of-screen switching, autostart.

The phone must have the `uinput` module loaded, the user in the `input` group and a udev rule
for `/dev/uinput` (`kmshare.py setup` does this once). The tool is optional and independent of the rest of the project.
