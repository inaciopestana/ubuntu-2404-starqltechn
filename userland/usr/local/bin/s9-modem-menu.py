#!/usr/bin/env python3
# Intermediario dbusmenu: espelha o item do nm-applet e acrescenta "Dados moveis" depois do bloco da wlan0.
import os, sys, time, shutil, subprocess, threading, traceback
import dbus, dbus.service, dbus.exceptions, dbus.mainloop.glib
from gi.repository import GLib

dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
dbus.mainloop.glib.threads_init()

SNI = "org.kde.StatusNotifierItem"
DM = "com.canonical.dbusmenu"
WATCHER = "org.kde.StatusNotifierWatcher"
ITEM_PATH = "/org/ayatana/NotificationItem/nm_applet_s9"
MENU_PATH = ITEM_PATH + "/Menu"
BASE = 1000000
SUB = [BASE + n for n in (2, 3, 4, 5, 6, 7, 8, 9, 10, 13, 11, 12)]
SM = ["sudo", "-n", "/usr/local/sbin/s9-modem"]
SC = ["sudo", "-n", "/usr/local/sbin/s9-cast"]
S9_CAST_V1 = True
CAST = BASE + 30
CSUB = [BASE + n for n in (31, 32, 39, 34, 40, 41, 42, 43, 44, 45, 46, 47, 48, 55, 49, 50, 33, 35, 56, 36, 37, 38, 54, 51, 52, 57, 58, 59, 60, 61, 62, 63)]
S9_CAST_V5D = True
S9_CAST_V6 = True
WIFI = BASE + 70
WSUB = [BASE + n for n in (71, 72, 73, 74, 75, 76, 77, 78, 79, 80, 81, 82, 83, 84, 85, 86)]
WDEV = [BASE + n for n in range(75, 81)]
WTARGETS_FILE = "/run/s9-cast/mira-targets.json"
AVDELAYS = {BASE + 59: 0, BASE + 60: 150, BASE + 61: 300, BASE + 62: 500, BASE + 63: 800}
S9_CAST_V5 = True
CDEV = [BASE + n for n in range(41, 49)]
S9_CAST_V2 = True
TARGETS_FILE = "/run/s9-cast/targets.json"
READY = "/tmp/s9-modem-menu.ready.%d" % os.getuid()
MY_ID = "nm-applet-s9"
POLL = 15

def log(*a):
    print("S9-MENU", *a, file=sys.stderr, flush=True)

def parse(out):
    d = {}
    for line in out.splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            d[k.strip()] = v.strip()
    return d

class Mobile:
    def __init__(self):
        self.st = {}
        self.busy = None
        self.on_change = lambda: None

    def sh(self, *args, timeout=300):
        try:
            r = subprocess.run(SM + list(args), capture_output=True, text=True, timeout=timeout)
            return r.returncode, (r.stdout + r.stderr).strip()
        except Exception as e:
            return 1, str(e)

    def refresh(self):
        if not self.busy:
            threading.Thread(target=self._poll, daemon=True).start()
        return True

    def _poll(self):
        rc, out = self.sh("status", timeout=30)
        GLib.idle_add(self._apply, rc, out)

    def _apply(self, rc, out):
        self.st = {"error": out[:100]} if rc != 0 else parse(out)
        self.on_change()
        return False

    def act(self, label, *args):
        if self.busy:
            return
        self.busy = label
        self.on_change()
        def work():
            rc, out = self.sh(*args)
            GLib.idle_add(self._done, label, rc, out)
        threading.Thread(target=work, daemon=True).start()

    def _done(self, label, rc, out):
        self.busy = None
        last = out.splitlines()[-1] if out else ""
        if shutil.which("notify-send"):
            subprocess.Popen(["notify-send", "-i", "network-cellular-signal-good-symbolic", "Mobile Data",
                              ("%s: ok" % label) if rc == 0 else ("%s: ERROR - %s" % (label, last))])
        self.on_change()
        self.refresh()
        return False

    def line1(self):
        st = self.st
        if "error" in st: return "Cannot query modem"
        if st.get("state") != "on": return "Modem off (ofono stopped)"
        if st.get("online") != "true": return "Modem radio off - not registered"
        if st.get("reg") != "registered": return "Searching network (%s)" % (st.get("reg") or "?")
        return "%s · %s" % (st.get("operator", "?"), st.get("tech", "?").upper())

    def line2(self):
        st = self.st
        if "error" in st: return st["error"]
        if st.get("data") == "true": return "Data: on (%s %s)" % (st.get("iface", ""), st.get("ip", ""))
        return "Data: off"

    def title(self):
        st = self.st
        if st.get("data") == "true": return "Mobile Data (on)"
        if st.get("online") == "true": return "Mobile Data (off)"
        if st.get("state") == "on": return "Mobile Data (modem not registered)"
        return "Mobile Data (modem off)"

class Cast:
    # S9_CAST_V2: transmissao da tela por SRT (PC/VLC) ou para TVs Google Cast / DLNA (helper /usr/local/sbin/s9-cast via sudo -n)
    def __init__(self):
        self.st = {}
        self.busy = None
        self.on_change = lambda: None
        self.targets = []
        self.scanning = False
        self.last_scan = 0.0
        self._fast = False
        self._prev_tv = False
        self.wtargets = []
        self.wscanning = False
        self.wlast_scan = 0.0
        self.load_targets()
        self.load_wtargets()

    def sh(self, *args, timeout=60):
        try:
            r = subprocess.run(SC + list(args), capture_output=True, text=True, timeout=timeout)
            return r.returncode, (r.stdout + r.stderr).strip()
        except Exception as e:
            return 1, str(e)

    def load_targets(self):
        try:
            import json
            with open(TARGETS_FILE) as f:
                data = json.load(f)
            ok = [t for t in data if isinstance(t, dict) and t.get("id") and t.get("name") and ("cast" in t or "dlna" in t)]
            self.targets = ok[:len(CDEV)]
        except Exception:
            self.targets = []

    def load_wtargets(self):
        try:
            import json
            with open(WTARGETS_FILE) as f:
                data = json.load(f)
            ok = [t for t in data if isinstance(t, dict) and t.get("id") and t.get("name")]
            self.wtargets = ok[:len(WDEV)]
        except Exception:
            self.wtargets = []

    def wscan_maybe(self, force=False):
        if self.wscanning or self.won():
            return
        if not force and time.time() - self.wlast_scan < 20:
            return
        self.wscanning = True
        self.on_change()
        def work():
            self.sh("wifi-scan", timeout=60)
            GLib.idle_add(self._wscan_done)
        threading.Thread(target=work, daemon=True).start()

    def _wscan_done(self):
        self.wscanning = False
        self.wlast_scan = time.time()
        self.load_wtargets()
        self.on_change()
        return False

    def don(self):
        return self.on() and self.mode() != "wifi"

    def won(self):
        return self.on() and self.mode() == "wifi"

    def wtitle(self):
        b = "Screen Cast (WIFI)"
        if "error" in self.st: return b + " - unavailable"
        if not self.won(): return b
        if self.st.get("state") == "streaming" and self.st.get("target"): return b + " - on %s" % self.st["target"][:24]
        return b + " - connecting..."

    def wline1(self):
        st = self.st
        if "error" in st: return "Cannot query: " + st["error"][:60]
        if self.won():
            who = (st.get("target") or "display")[:28]
            if st.get("state") == "streaming":
                return "Casting to %s%s" % (who, (" (%s)" % st["res"]) if st.get("res") else "")
            return st.get("step") or ("Connecting to %s..." % who)
        if self.wscanning: return "Searching for displays..."
        return "Not casting"

    def proto_of(self, t):
        pref = self.st.get("pref", "gcast")
        if pref == "dlna" and "dlna" in t: return "dlna"
        if pref == "gcast" and "cast" in t: return "gcast"
        return "gcast" if "cast" in t else "dlna"

    def dev_label(self, t):
        return "%s (%s)" % (t["name"][:32], "Google Cast" if self.proto_of(t) == "gcast" else "DLNA")

    def refresh(self):
        if not self.busy:
            threading.Thread(target=self._poll, daemon=True).start()
        return True

    def _poll(self):
        rc, out = self.sh("status", timeout=20)
        GLib.idle_add(self._apply, rc, out)

    def _apply(self, rc, out):
        self.st = {"error": out[:100]} if rc != 0 else parse(out)
        tv = self.st.get("mode") in ("tv", "web", "wifi")
        if self._prev_tv and not tv and self.st.get("lasterr"):
            self.notify("Stopped: " + self.st["lasterr"])
        self._prev_tv = tv
        self.on_change()
        if self.st.get("state") == "connecting" and not self._fast:
            self._fast = True
            GLib.timeout_add_seconds(2, self._fast_poll)
        return False

    def _fast_poll(self):
        self._fast = False
        self.refresh()
        return False

    def scan_maybe(self):
        if self.scanning or time.time() - self.last_scan < 8:
            return
        self.scanning = True
        self.on_change()
        def work():
            self.sh("scan", timeout=45)
            GLib.idle_add(self._scan_done)
        threading.Thread(target=work, daemon=True).start()

    def _scan_done(self):
        self.scanning = False
        self.last_scan = time.time()
        self.load_targets()
        self.on_change()
        return False

    def act(self, label, *args):
        if self.busy:
            return
        self.busy = label
        self.on_change()
        def work():
            rc, out = self.sh(*args)
            GLib.idle_add(self._done, label, rc, out)
        threading.Thread(target=work, daemon=True).start()

    @staticmethod
    def notify(msg):
        if shutil.which("notify-send"):
            subprocess.Popen(["notify-send", "-i", "video-display-symbolic", "Screen Cast", msg])
        return False

    def _done(self, label, rc, out):
        self.busy = None
        last = out.splitlines()[-1] if out else ""
        if rc != 0:
            self.notify("%s: ERROR - %s" % (label, last))
        elif last.startswith("srt://"):
            self.notify("Screen cast on: %s - waiting for a viewer" % last.split(" ")[0])
        elif last.startswith("wifi:"):
            self.notify(last[5:].strip())
        elif last.startswith("tv:"):
            self.notify(label + "...")
        elif last.startswith("web:"):
            self.notify("Open this address in the tablet's browser: " + last[4:].strip())
        else:
            self.notify("%s: ok" % label)
        self.on_change()
        self.refresh()
        return False

    def copy_cmd(self):
        def work():
            rc, out = self.sh("cmd", timeout=20)
            ok = False
            if rc == 0 and out:
                try:
                    p = subprocess.run(["xclip", "-selection", "clipboard"], input=out, text=True, timeout=10,
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    ok = p.returncode == 0
                except Exception as e:
                    log("xclip:", e)
                if not ok:
                    try:
                        path = os.path.expanduser("~/s9-cast-viewer.txt")
                        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
                        with os.fdopen(fd, "w") as f:
                            f.write(out + "\n")
                        GLib.idle_add(self.notify, "Clipboard unavailable; viewer command saved to ~/s9-cast-viewer.txt")
                        return
                    except Exception as e:
                        log("salvar comando:", e)
            GLib.idle_add(self.notify, "Viewer command copied to the clipboard" if ok else "Could not get the viewer command")
        threading.Thread(target=work, daemon=True).start()

    def copy_web(self):
        def work():
            rc, out = self.sh("weburl", timeout=20)
            ok = False
            if rc == 0 and out.startswith("http"):
                try:
                    p = subprocess.run(["xclip", "-selection", "clipboard"], input=out, text=True, timeout=10,
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    ok = p.returncode == 0
                except Exception as e:
                    log("xclip:", e)
                if not ok:
                    try:
                        path = os.path.expanduser("~/s9-cast-web-address.txt")
                        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
                        with os.fdopen(fd, "w") as f:
                            f.write(out + "\n")
                        GLib.idle_add(self.notify, "Clipboard unavailable; address saved to ~/s9-cast-web-address.txt")
                        return
                    except Exception as e:
                        log("salvar endereco:", e)
            GLib.idle_add(self.notify, ("Browser address copied: " + out) if ok else "Could not get the browser address")
        threading.Thread(target=work, daemon=True).start()

    def on(self):
        return self.st.get("state") in ("waiting", "streaming", "connecting")

    def mode(self):
        return self.st.get("mode", "")

    def title(self):
        s = self.st.get("state")
        b = "Screen Cast (DLNA)"
        if "error" in self.st: return b + " - unavailable"
        if self.mode() == "wifi": return b
        if self.mode() == "web":
            return b + (" - on browser" if s == "streaming" else " - waiting for browser")
        if self.mode() == "tv":
            if s == "streaming" and self.st.get("target"): return b + " - on %s" % self.st["target"][:24]
            return b + " - connecting..."
        if s == "streaming": return b + " - streaming"
        if s == "waiting": return b + " - waiting for viewer"
        return b

    def line1(self):
        st = self.st
        if "error" in st: return "Cannot query: " + st["error"][:60]
        if self.mode() == "wifi": return "Not casting here (a Wi-Fi display is active)"
        if self.mode() == "web":
            n = st.get("clients", "0")
            if st.get("state") == "streaming":
                return "Showing in a browser (%s viewer%s)" % (n, "" if n == "1" else "s")
            return "Waiting for a browser to open this address:"
        if self.mode() == "tv":
            who = st.get("target") or "TV"
            if st.get("state") == "streaming":
                return "Casting to %s (%s)" % (who[:28], "Google Cast" if st.get("proto") == "gcast" else "DLNA")
            return "Connecting to %s..." % who[:28]
        if st.get("state") == "streaming":
            txt = "Streaming"
            try: txt += " %d fps" % round(float(st.get("fps", "")))
            except Exception: pass
            if st.get("bitrate"): txt += ", " + st["bitrate"]
            return txt
        if st.get("state") == "waiting": return "Waiting for a viewer"
        if st.get("lasterr"): return "Error: " + st["lasterr"][:60]
        return "Not casting"

    def line2(self):
        st = self.st
        if self.mode() == "web" and st.get("weburl"): return st["weburl"]
        return "srt://%s:%s (encrypted)" % (st.get("ip") or "?", st.get("port", "5000"))

class Item(dbus.service.Object):
    def __init__(self, bus, rsvc, rpath):
        dbus.service.Object.__init__(self, bus, ITEM_PATH)
        self.rsvc, self.rpath = rsvc, rpath
        obj = bus.get_object(rsvc, rpath)
        self.remote = dbus.Interface(obj, SNI)
        self.rprops = dbus.Interface(obj, dbus.PROPERTIES_IFACE)
        self.props = {}
        self.reload()
        bus.add_signal_receiver(self._on_remote, dbus_interface=SNI, bus_name=rsvc, path=rpath, member_keyword="member")

    def reload(self):
        try:
            d = self.rprops.GetAll(SNI)
        except Exception as e:
            log("GetAll do item remoto falhou:", e); return
        p = dict(d)
        p["Id"] = dbus.String(MY_ID)
        p["Menu"] = dbus.ObjectPath(MENU_PATH)
        self.props = p

    def _on_remote(self, *args, member=None):
        try:
            self.reload()
            fn = getattr(self, member, None)
            if member in ("NewTitle", "NewIcon", "NewAttentionIcon", "NewOverlayIcon", "NewToolTip", "NewStatus", "XAyatanaNewLabel") and fn:
                fn(*args)
        except Exception:
            log(traceback.format_exc())

    def _fwd(self, name, *a):
        getattr(self.remote, name)(*a, reply_handler=lambda *x: None, error_handler=lambda e: log("fwd", name, e))

    @dbus.service.method(dbus.PROPERTIES_IFACE, in_signature="ss", out_signature="v")
    def Get(self, iface, name):
        if name in self.props: return self.props[name]
        raise dbus.exceptions.DBusException("no such property", name="org.freedesktop.DBus.Error.InvalidArgs")

    @dbus.service.method(dbus.PROPERTIES_IFACE, in_signature="s", out_signature="a{sv}")
    def GetAll(self, iface):
        return dbus.Dictionary(self.props if iface == SNI else {}, signature="sv")

    @dbus.service.method(dbus.PROPERTIES_IFACE, in_signature="ssv", out_signature="")
    def Set(self, iface, name, value):
        pass

    @dbus.service.method(SNI, in_signature="ii", out_signature="")
    def Activate(self, x, y): self._fwd("Activate", x, y)
    @dbus.service.method(SNI, in_signature="ii", out_signature="")
    def ContextMenu(self, x, y): self._fwd("ContextMenu", x, y)
    @dbus.service.method(SNI, in_signature="ii", out_signature="")
    def SecondaryActivate(self, x, y): self._fwd("SecondaryActivate", x, y)
    @dbus.service.method(SNI, in_signature="is", out_signature="")
    def Scroll(self, d, o): self._fwd("Scroll", d, o)

    @dbus.service.signal(SNI, signature="")
    def NewTitle(self): pass
    @dbus.service.signal(SNI, signature="")
    def NewIcon(self): pass
    @dbus.service.signal(SNI, signature="")
    def NewAttentionIcon(self): pass
    @dbus.service.signal(SNI, signature="")
    def NewOverlayIcon(self): pass
    @dbus.service.signal(SNI, signature="")
    def NewToolTip(self): pass
    @dbus.service.signal(SNI, signature="s")
    def NewStatus(self, s): pass
    @dbus.service.signal(SNI, signature="ss")
    def XAyatanaNewLabel(self, a, b): pass

class Menu(dbus.service.Object):
    def __init__(self, bus, rsvc, rmenu, mob, cast=None):
        dbus.service.Object.__init__(self, bus, MENU_PATH)
        self.r = dbus.Interface(bus.get_object(rsvc, rmenu), DM)
        self.mob = mob
        self.cast = cast if cast is not None else Cast()
        self.rev = int(time.time()) & 0x7fffffff
        self.cur = self.compute()
        self.rule_logged = False
        bus.add_signal_receiver(self._r_layout, "LayoutUpdated", DM, rsvc, rmenu)
        bus.add_signal_receiver(self._r_props, "ItemsPropertiesUpdated", DM, rsvc, rmenu)
        bus.add_signal_receiver(self._r_act, "ItemActivationRequested", DM, rsvc, rmenu)
        mob.on_change = self.update_ours
        self.cast.on_change = self.update_ours

    # ---- nosso submenu ----
    def compute(self):
        m = self.mob
        st = m.st
        on = st.get("state") == "on"
        data = st.get("data") == "true"
        busy = bool(m.busy)
        online = st.get("online") == "true"
        def it(label, enabled=True, visible=True):
            return {"label": dbus.String(label), "enabled": dbus.Boolean(enabled), "visible": dbus.Boolean(visible)}
        def sep(visible=True):
            return {"type": dbus.String("separator"), "visible": dbus.Boolean(visible)}
        P = {}
        P[BASE + 1] = {"label": dbus.String(m.title()), "children-display": dbus.String("submenu"),
                       "enabled": dbus.Boolean(True), "visible": dbus.Boolean(True)}
        P[BASE + 2] = it(m.line1(), enabled=False)
        P[BASE + 3] = it(m.line2(), enabled=False)
        P[BASE + 4] = sep()
        P[BASE + 5] = it((m.busy or "") + "...", enabled=False, visible=busy)
        P[BASE + 6] = it("Turn data off", visible=data and not busy)
        P[BASE + 7] = it("Use SIM as primary connection", visible=data and not busy)
        P[BASE + 8] = it("Use SIM as Wi-Fi backup", visible=data and not busy)
        P[BASE + 9] = it("Turn data on (Wi-Fi backup)", visible=(not data) and not busy)
        P[BASE + 10] = it("Turn data on (primary)", visible=(not data) and not busy)
        P[BASE + 11] = sep(visible=on and not busy)
        P[BASE + 12] = it("Power off modem (stop ofono)", visible=on and not busy)
        P[BASE + 13] = it("Power on modem (register only)", visible=(not online) and not busy)
        P[BASE + 20] = sep()
        # ---- Screen Cast (S9_CAST_V2) ----
        c = self.cast
        cs = c.st
        con = c.don()
        cbusy = bool(c.busy)
        q = cs.get("quality", "normal")
        pref = cs.get("pref", "gcast")
        def rad(label, checked, enabled=True, visible=True):
            return {"label": dbus.String(label), "enabled": dbus.Boolean(enabled), "visible": dbus.Boolean(visible),
                    "toggle-type": dbus.String("radio"), "toggle-state": dbus.Int32(1 if checked else 0)}
        P[CAST] = {"label": dbus.String(c.title()), "children-display": dbus.String("submenu"),
                   "enabled": dbus.Boolean(True), "visible": dbus.Boolean(True)}
        P[BASE + 31] = it(c.line1(), enabled=False)
        P[BASE + 32] = it(c.line2(), enabled=False, visible=con and c.mode() in ("srt", "web"))
        P[BASE + 39] = it((c.busy or "") + "...", enabled=False, visible=cbusy)
        P[BASE + 34] = it("Stop casting", visible=con and not cbusy)
        P[BASE + 40] = it("Cast screen to:", enabled=False)
        for k, slot in enumerate(CDEV):
            if k < len(c.targets):
                t = c.targets[k]
                P[slot] = rad(c.dev_label(t), con and c.mode() == "tv" and cs.get("target_id") == t["id"], enabled=not cbusy)
            else:
                P[slot] = rad("", False, enabled=False, visible=False)
        P[BASE + 55] = rad("Web browser (tablet, any device)", con and c.mode() == "web", enabled=not cbusy)
        P[BASE + 49] = it("Searching for TVs..." if c.scanning else "No TVs found on this network",
                          enabled=False, visible=c.scanning or not c.targets)
        P[BASE + 50] = sep()
        P[BASE + 33] = it("Start SRT stream (PC / VLC)", visible=(not con) and not cbusy)
        P[BASE + 35] = it("Copy SRT viewer command", visible=not cbusy)
        P[BASE + 56] = it("Copy browser address", visible=not cbusy)
        P[BASE + 36] = sep()
        P[BASE + 37] = rad("Quality: Normal (1080p)", q == "normal", enabled=not cbusy)
        P[BASE + 38] = rad("Quality: Light (720p)", q == "light", enabled=not cbusy)
        P[BASE + 54] = sep()
        P[BASE + 51] = rad("TV protocol: Google Cast", pref == "gcast", enabled=not cbusy)
        P[BASE + 52] = rad("TV protocol: DLNA", pref == "dlna", enabled=not cbusy)
        try:
            avo = int(cs.get("av_offset", "0"))
        except ValueError:
            avo = 0
        P[BASE + 57] = sep()
        P[BASE + 58] = it("Sound delay (sync with picture):" if avo in AVDELAYS.values() else "Sound delay: %+d ms (custom)" % avo, enabled=False)
        for k, v in AVDELAYS.items():
            P[k] = rad("None" if v == 0 else "Delay sound %d ms" % v, avo == v, enabled=not cbusy)
        # ---- Screen Cast (WIFI) (S9_CAST_V6): Miracast / Wi-Fi Direct ----
        won = c.won()
        P[WIFI] = {"label": dbus.String(c.wtitle()), "children-display": dbus.String("submenu"),
                   "enabled": dbus.Boolean(True), "visible": dbus.Boolean(True)}
        P[BASE + 71] = it(c.wline1(), enabled=False)
        P[BASE + 72] = it((c.busy or "") + "...", enabled=False, visible=cbusy)
        P[BASE + 73] = it("Stop casting", visible=won and not cbusy)
        P[BASE + 74] = it("Cast screen to:", enabled=False)
        for k, slot in enumerate(WDEV):
            if k < len(c.wtargets):
                t = c.wtargets[k]
                P[slot] = rad(t["name"][:32], won and cs.get("target_id") == t["id"], enabled=not cbusy)
            else:
                P[slot] = rad("", False, enabled=False, visible=False)
        P[BASE + 81] = it("Searching for displays..." if c.wscanning else "No Wi-Fi displays found",
                          enabled=False, visible=c.wscanning or not c.wtargets)
        P[BASE + 82] = sep()
        P[BASE + 83] = rad("Quality: Normal (1080p if supported)", q == "normal", enabled=not cbusy)
        P[BASE + 84] = rad("Quality: Light (720p)", q == "light", enabled=not cbusy)
        P[BASE + 85] = sep()
        P[BASE + 86] = it("Search for displays again", visible=(not won) and (not cbusy) and (not c.wscanning))
        return P

    def update_ours(self):
        try:
            new = self.compute()
            updated, removed = [], []
            for i, p in new.items():
                old = self.cur.get(i, {})
                ch = {k: v for k, v in p.items() if old.get(k) != v}
                if ch:
                    updated.append(dbus.Struct((dbus.Int32(i), dbus.Dictionary(ch, signature="sv")), signature="ia{sv}"))
                gone = [k for k in old if k not in p]
                if gone:
                    removed.append(dbus.Struct((dbus.Int32(i), dbus.Array(gone, signature="s")), signature="ias"))
            self.cur = new
            if updated or removed:
                self.ItemsPropertiesUpdated(dbus.Array(updated, signature="(ia{sv})"), dbus.Array(removed, signature="(ias)"))
        except Exception:
            log(traceback.format_exc())
        return False

    def refresh_all(self):
        self.mob.refresh()
        self.cast.refresh()
        self.cast.scan_maybe()
        self.cast.wscan_maybe()

    def click(self, i):
        m = self.mob
        acts = {BASE + 6: ("Turning data off", "down"), BASE + 7: ("Switching to primary", "up", "primary"),
                BASE + 8: ("Switching to backup", "up", "backup"), BASE + 9: ("Turning data on", "up", "backup"),
                BASE + 10: ("Turning data on", "up", "primary"), BASE + 12: ("Powering off modem", "off"), BASE + 13: ("Powering on modem", "on")}
        if i in acts:
            m.act(*acts[i])
            return
        cacts = {BASE + 33: ("Starting screen cast", "start"), BASE + 34: ("Stopping screen cast", "stop"),
                 BASE + 37: ("Setting quality", "quality", "normal"), BASE + 38: ("Setting quality", "quality", "light"),
                 BASE + 51: ("Setting protocol", "proto", "gcast"), BASE + 52: ("Setting protocol", "proto", "dlna")}
        c = self.cast
        if i in WDEV:
            k = WDEV.index(i)
            if k < len(c.wtargets):
                t = c.wtargets[k]
                if c.won() and c.st.get("target_id") == t["id"]:
                    c.act("Stopping screen cast", "stop")
                else:
                    c.act("Connecting to " + t["name"][:28], "wifi", t["id"])
            return
        if i == BASE + 73:
            c.act("Stopping screen cast", "stop"); return
        if i == BASE + 83:
            c.act("Setting quality", "quality", "normal"); return
        if i == BASE + 84:
            c.act("Setting quality", "quality", "light"); return
        if i == BASE + 86:
            c.wscan_maybe(True); return
        if i in cacts:
            c.act(*cacts[i])
        elif i in AVDELAYS:
            c.act("Setting sound delay", "avoffset", str(AVDELAYS[i]))
        elif i == BASE + 35:
            c.copy_cmd()
        elif i == BASE + 56:
            c.copy_web()
        elif i == BASE + 55:
            if c.on() and c.mode() == "web":
                c.act("Stopping screen cast", "stop")
            else:
                c.act("Starting web viewer", "web")
        elif i in CDEV:
            k = CDEV.index(i)
            if k < len(c.targets):
                t = c.targets[k]
                if c.on() and c.mode() == "tv" and c.st.get("target_id") == t["id"]:
                    c.act("Stopping screen cast", "stop")
                else:
                    c.act("Connecting to " + t["name"][:28], "tv", t["id"])

    def our_node(self, i, depth, level=0):
        kids = []
        if i == BASE + 1 and depth != 0:
            cd = depth - 1 if depth > 0 else -1
            kids = [self.our_node(c, cd, 1) for c in SUB]
        elif i == CAST and depth != 0:
            cd = depth - 1 if depth > 0 else -1
            kids = [self.our_node(c, cd, 1) for c in CSUB]
        elif i == WIFI and depth != 0:
            cd = depth - 1 if depth > 0 else -1
            kids = [self.our_node(c, cd, 1) for c in WSUB]
        return dbus.Struct((dbus.Int32(i), dbus.Dictionary(self.cur[i], signature="sv"), dbus.Array(kids, signature="v")),
                           signature="ia{sv}av", variant_level=level)

    def clone(self, node, level):
        kids = [self.clone(c, 1) for c in node[2]]
        return dbus.Struct((dbus.Int32(node[0]), dbus.Dictionary(node[1], signature="sv"), dbus.Array(kids, signature="v")),
                           signature="ia{sv}av", variant_level=level)

    def insert_pos(self, ch):
        def lab(c): return str(c[1].get("label", ""))
        def is_sep(c): return str(c[1].get("type", "")) == "separator"
        n = len(ch)
        start, rule = None, "fim"
        for k, c in enumerate(ch):
            if "(wlan0)" in lab(c):
                start, rule = k, "wlan0"; break
        if start is None:
            for k, c in enumerate(ch):
                if lab(c).replace("_", "") in ("Disconnect", "Desconectar"):
                    start, rule = k, "bloco conectado"; break
        pos = n
        if start is not None:
            for k in range(start, n):
                if is_sep(ch[k]):
                    pos = k + 1; break
        if not self.rule_logged:
            log("posicao do submenu: regra=%s indice=%d de %d" % (rule, pos, n))
            self.rule_logged = True
        return pos

    # ---- dbusmenu ----
    @dbus.service.method(DM, in_signature="iias", out_signature="u(ia{sv}av)")
    def GetLayout(self, parent, depth, names):
        try:
            if parent >= BASE:
                return dbus.UInt32(self.rev), self.our_node(parent, depth)
            rev, node = self.r.GetLayout(parent, depth, names)
            kids = [self.clone(c, 1) for c in node[2]]
            if parent == 0 and depth != 0:
                pos = self.insert_pos(node[2])
                cd = depth - 1 if depth > 0 else -1
                kids[pos:pos] = [self.our_node(BASE + 1, cd, 1), self.our_node(CAST, cd, 1), self.our_node(WIFI, cd, 1), self.our_node(BASE + 20, 0, 1)]
            top = dbus.Struct((dbus.Int32(node[0]), dbus.Dictionary(node[1], signature="sv"), dbus.Array(kids, signature="v")),
                              signature="ia{sv}av")
            return dbus.UInt32(self.rev), top
        except Exception:
            log(traceback.format_exc())
            raise

    @dbus.service.method(DM, in_signature="aias", out_signature="a(ia{sv})")
    def GetGroupProperties(self, ids, names):
        res = []
        others = [int(i) for i in ids if i < BASE]
        if not ids or others:
            try:
                res += list(self.r.GetGroupProperties(others, names))
            except Exception as e:
                log("GetGroupProperties remoto:", e)
        want = [int(i) for i in ids if i >= BASE] if ids else list(self.cur.keys())
        for i in want:
            p = self.cur.get(i)
            if p is None: continue
            if names: p = {k: v for k, v in p.items() if k in names}
            res.append(dbus.Struct((dbus.Int32(i), dbus.Dictionary(p, signature="sv")), signature="ia{sv}"))
        return dbus.Array(res, signature="(ia{sv})")

    @dbus.service.method(DM, in_signature="is", out_signature="v")
    def GetProperty(self, i, name):
        if i >= BASE:
            v = self.cur.get(i, {}).get(name)
            if v is None:
                raise dbus.exceptions.DBusException("no such property", name="org.freedesktop.DBus.Error.InvalidArgs")
            return v
        return self.r.GetProperty(i, name)

    @dbus.service.method(DM, in_signature="isvu", out_signature="")
    def Event(self, i, event_id, data, ts):
        if i >= BASE:
            if event_id == "clicked":
                self.click(int(i))
            return
        self.r.Event(i, event_id, data, ts, reply_handler=lambda *x: None, error_handler=lambda e: log("Event fwd", e))

    @dbus.service.method(DM, in_signature="a(isvu)", out_signature="ai")
    def EventGroup(self, events):
        for (i, ev, data, ts) in events:
            self.Event(i, ev, data, ts)
        return dbus.Array([], signature="i")

    @dbus.service.method(DM, in_signature="i", out_signature="b")
    def AboutToShow(self, i):
        if i == 0 or i >= BASE:
            self.refresh_all()
        if i >= BASE:
            return False
        try:
            return bool(self.r.AboutToShow(i))
        except Exception:
            return False

    @dbus.service.method(DM, in_signature="ai", out_signature="aiai")
    def AboutToShowGroup(self, ids):
        need = []
        for i in ids:
            if i < BASE:
                try:
                    if self.r.AboutToShow(i): need.append(int(i))
                except Exception:
                    pass
            else:
                self.refresh_all()
        return dbus.Array(need, signature="i"), dbus.Array([], signature="i")

    def _p(self):
        return {"Version": dbus.UInt32(3), "TextDirection": dbus.String("ltr"), "Status": dbus.String("normal"),
                "IconThemePath": dbus.Array([], signature="s")}

    @dbus.service.method(dbus.PROPERTIES_IFACE, in_signature="ss", out_signature="v")
    def Get(self, iface, name):
        d = self._p()
        if name in d: return d[name]
        raise dbus.exceptions.DBusException("no such property", name="org.freedesktop.DBus.Error.InvalidArgs")

    @dbus.service.method(dbus.PROPERTIES_IFACE, in_signature="s", out_signature="a{sv}")
    def GetAll(self, iface):
        return dbus.Dictionary(self._p() if iface == DM else {}, signature="sv")

    @dbus.service.method(dbus.PROPERTIES_IFACE, in_signature="ssv", out_signature="")
    def Set(self, iface, name, value):
        pass

    @dbus.service.signal(DM, signature="a(ia{sv})a(ias)")
    def ItemsPropertiesUpdated(self, updated, removed): pass
    @dbus.service.signal(DM, signature="ui")
    def LayoutUpdated(self, rev, parent): pass
    @dbus.service.signal(DM, signature="iu")
    def ItemActivationRequested(self, i, ts): pass

    def _r_layout(self, rev, parent):
        try:
            self.rev = (self.rev + 1) & 0x7fffffff
            self.LayoutUpdated(dbus.UInt32(self.rev), dbus.Int32(parent))
        except Exception:
            log(traceback.format_exc())

    def _r_props(self, updated, removed):
        try: self.ItemsPropertiesUpdated(updated, removed)
        except Exception: log(traceback.format_exc())

    def _r_act(self, i, ts):
        try: self.ItemActivationRequested(i, ts)
        except Exception: log(traceback.format_exc())

def find_remote(bus):
    try:
        w = bus.get_object(WATCHER, "/StatusNotifierWatcher")
        items = dbus.Interface(w, dbus.PROPERTIES_IFACE).Get(WATCHER, "RegisteredStatusNotifierItems")
    except Exception:
        return None
    for it in items:
        s = str(it)
        if s.endswith("/org/ayatana/NotificationItem/nm_applet"):
            svc, rest = s.split("/", 1)
            return svc, "/" + rest
    return None

def find_remote_pid(bus):
    # S9_NOREG: o nm-applet original nao se registra mais no watcher (shim LD_PRELOAD);
    # acha o servico dele pelo PID do processo.
    try:
        import subprocess
        out = subprocess.run(["pgrep", "-u", str(os.getuid()), "-x", "nm-applet"],
                             capture_output=True, text=True).stdout.split()
        pids = {int(x) for x in out}
        if not pids: return None
        d = dbus.Interface(bus.get_object("org.freedesktop.DBus", "/org/freedesktop/DBus"), "org.freedesktop.DBus")
        path = "/org/ayatana/NotificationItem/nm_applet"
        for n in d.ListNames():
            n = str(n)
            if not n.startswith(":"): continue
            try:
                if int(d.GetConnectionUnixProcessID(n)) not in pids: continue
                dbus.Interface(bus.get_object(n, path), dbus.PROPERTIES_IFACE).Get(SNI, "Id")
                return n, path
            except Exception:
                continue
    except Exception:
        return None
    return None

def main():
    bus = dbus.SessionBus()
    remote = None
    for _ in range(120):
        remote = find_remote_pid(bus) or find_remote(bus)
        if remote: break
        time.sleep(2)
    if not remote:
        log("nm-applet nao encontrado; saindo"); return 1
    rsvc, rpath = remote
    log("nm-applet em", rsvc, rpath)
    mob = Mobile()
    cast = Cast()
    item = Item(bus, rsvc, rpath)
    rmenu = str(item.props.get("Menu", rpath + "/Menu"))
    # o Menu do item espelhado aponta para o NOSSO caminho; o do nm-applet vem do GetAll remoto
    rmenu = str(dbus.Interface(bus.get_object(rsvc, rpath), dbus.PROPERTIES_IFACE).Get(SNI, "Menu"))
    menu = Menu(bus, rsvc, rmenu, mob, cast)
    loop = GLib.MainLoop()
    state = {"registered": False}

    def register():
        try:
            w = bus.get_object(WATCHER, "/StatusNotifierWatcher")
            dbus.Interface(w, WATCHER).RegisterStatusNotifierItem(ITEM_PATH)
            log("item registrado no watcher")
            if not state["registered"]:
                state["registered"] = True
                open(READY, "w").write(str(os.getpid()))
        except Exception as e:
            log("registro falhou:", e)
        return False

    def on_watcher(owner):
        if owner:
            GLib.timeout_add_seconds(1, register)

    def on_remote(owner):
        if not owner:
            log("nm-applet saiu; encerrando para o launcher reiniciar")
            loop.quit()

    bus.watch_name_owner(WATCHER, on_watcher)
    bus.watch_name_owner(rsvc, on_remote)
    def refresh_all():
        mob.refresh()
        cast.refresh()
        return True
    refresh_all()
    GLib.timeout_add_seconds(POLL, refresh_all)
    try:
        loop.run()
    finally:
        try: os.unlink(READY)
        except OSError: pass
    return 0

if __name__ == "__main__":
    sys.exit(main())
