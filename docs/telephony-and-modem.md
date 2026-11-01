# Mobile data, calls and SMS

## Architecture
Android runs as an LXC container with HALs only (no framework). The radio HALs
(`android.hardware.radio@1.2::IRadio/slot1|slot2`, `radio.config@1.1`) are reachable
through the host's `/dev/hwbinder`. The Linux side talks to them with **ofono-sailfish**
(not Ubuntu's ofono 1.31) and its binder plugin; ModemManager finds no modem and
NetworkManager cannot talk to ofono, so routing/DNS are applied by a script.

Packages come from the UBports repo (`ofono-sailfish`, `ofono-binder-plugin`,
`ofono-sailfish-scripts`, `libgbinder-tools`); simulate first with `apt-get -s`.

## Components (all under `system/` and `userland/`)
| Piece | Role |
|---|---|
| `ofono.service` drop-in `s9-binder.conf` | runs `ofonod` with the `ril` plugin directly; the packaged wrapper disables the binder plugin because a helper binary is missing |
| `/etc/ofono/binder.conf` | `Identity=root:root`, `ExpectSlots=slot1,slot2`, **`path=/ril_N` per slot** (without it "Missing path for slot") |
| `s9-modem` (root) | `up [primary\|backup]`, `down`, `on`, `off`, `status`; sets APN, waits for attach, activates the context, installs route (metric 900 as backup to Wi-Fi at 600, or 50 as primary) and the operator's DNS |
| `s9-phoned` (root daemon, UNIX socket) | calls, SMS, history, notifications; switches the Pulse card profile to `voicecall` during a call |
| `s9-phone` | command-line client |
| `s9-telefone` | GTK3 dialer/messages/contacts app (single instance) |
| `s9-pre-shutdown.service` | hangs up, takes data down, sets `Online=false`, syncs - before the Android container is killed |
| sudoers rules | the normal user may run only fixed `s9-modem` sub-commands without a password |

Only root can talk to ofono on the system bus (a D-Bus policy did not help), hence the
root daemon + socket design.

## Hard-won facts
* Writing the APN makes ofono detach/re-attach the radio; activating the context immediately
  fails with *GPRS is not attached*. Wait for `Attached=true`.
* The carrier does not answer ICMP. Test connectivity with HTTPS/DNS, never with ping.
* **Never call `org.ofono.NetworkMonitor.GetServingCellInformation`.** It enables 500 ms cell
  polling and `ofonod` aborts shortly afterwards. A status poller that used it killed ofono
  every 15 s. `org.nemomobile.ofono.CellInfo.GetCells` did not crash it.
* ofono run with `-d` prints IMEI/IMSI; mask anything with 8+ digits before sharing logs.
* A modem that is not shut down cleanly (`modem fatal error` -> RCU stall -> watchdog) is one
  cause of inconsistent reboots. Do **not** use `systemctl stop ofono` inside a shutdown job
  (it deadlocks on itself); set `Online=false` over D-Bus instead.

## Call audio
Switching the droid card to `voicecall`/`communication`/`ringtone` crashed PulseAudio
(`pa_sink_assert_ref` at `park_profile()`), because the UBports `module-droid-discover` loads
the card with the quirk `-output_deep_buffer`, leaving the primary mapping without a sink
(the S9 primary mix port has `PRIMARY|DEEP_BUFFER`). Work-around, no rebuild needed: load the
card explicitly in `/etc/s9-ubports-audio.pa`:
```
load-module module-droid-card-29
load-module module-droid-hidl
```
After a call the sink port stays on `output-parking`; `s9-phoned` restores the best available
non-parking, non-earpiece port (speaker) 1.5 s after the profile returns to `default`.
Speaker/earpiece is `pactl set-sink-port <primary sink> output-speaker|output-earpiece`.

## Tray icons for GTK programs
`Gtk.StatusIcon` menus and tooltips open in the middle of the screen: the patched Mir only
preserves requested popup positions for windows owned by the XFCE panel plugin wrapper.
Always use an **AppIndicator / StatusNotifierItem** so the panel draws the menu itself.
