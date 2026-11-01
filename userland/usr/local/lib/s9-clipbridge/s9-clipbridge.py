#!/usr/bin/env python3
# S9_CLIPBRIDGE_V1: lado X11 da ponte de clipboard Mir <-> X11 (texto e imagens, CLIPBOARD).
#
# Fala com o Mir por um socket Unix (quadros: 1 byte de tipo + 4 bytes de tamanho BE + carga):
#   Mir -> aqui: 'W' texto da selecao Wayland (ex.: Chrome)   'I' imagem "mime\0bytes"
#                'C' selecao Wayland sem texto nem imagem
#   aqui -> Mir: 'X' texto do CLIPBOARD do X11               'Y' imagem "mime\0bytes"
# Fala com o Xwayland (:0) por ctypes + libX11/libXfixes (sem dependencias de pip).
# Reconecta sozinho ao Mir; se o X morrer, o processo sai e o systemd reinicia.

import ctypes
import hashlib
import os
import select
import signal
import socket
import struct
import sys
import time
from ctypes import (POINTER, Structure, Union, byref, c_char_p, c_int, c_long, c_size_t, c_ubyte,
                    c_uint, c_ulong, c_void_p, cast, string_at)

SOCK_PATH = os.environ.get("S9_CLIP_SOCKET", "/run/s9-miral/clip.sock")
DEBUG = os.environ.get("S9_CLIP_DEBUG", "") not in ("", "0")
MAX_TEXT = 32 * 1024 * 1024   # limite de texto/imagem por transferencia
IMAGE_PREFER = ("image/png", "image/jpeg", "image/bmp")
CHUNK = 64 * 1024            # tamanho de cada pedaco no INCR
INCR_THRESHOLD = 200 * 1024  # acima disso, responde por INCR
CONVERT_TIMEOUT = 3.0
INCR_TIMEOUT = 10.0


def log(msg):
    print("s9-clipbridge: " + msg, flush=True)


def dbg(msg):
    if DEBUG:
        log("[dbg] " + msg)


# ---------------------------------------------------------------- Xlib via ctypes
Atom = c_ulong
Window = c_ulong
Time = c_ulong
Bool = c_int

PropertyChangeMask = 1 << 22
PropertyNotify = 28
SelectionClear = 29
SelectionRequest = 30
SelectionNotify = 31
PropertyNewValue = 0
PropertyDelete = 1
PropModeReplace = 0
CurrentTime = 0
XA_ATOM = 4
XA_INTEGER = 19
XA_STRING = 31
AnyPropertyType = 0
XFixesSetSelectionOwnerNotifyMask = 1


class XSelectionRequestEvent(Structure):
    _fields_ = [("type", c_int), ("serial", c_ulong), ("send_event", Bool), ("display", c_void_p),
                ("owner", Window), ("requestor", Window), ("selection", Atom), ("target", Atom),
                ("property", Atom), ("time", Time)]


class XSelectionEvent(Structure):
    _fields_ = [("type", c_int), ("serial", c_ulong), ("send_event", Bool), ("display", c_void_p),
                ("requestor", Window), ("selection", Atom), ("target", Atom), ("property", Atom),
                ("time", Time)]


class XSelectionClearEvent(Structure):
    _fields_ = [("type", c_int), ("serial", c_ulong), ("send_event", Bool), ("display", c_void_p),
                ("window", Window), ("selection", Atom), ("time", Time)]


class XPropertyEvent(Structure):
    _fields_ = [("type", c_int), ("serial", c_ulong), ("send_event", Bool), ("display", c_void_p),
                ("window", Window), ("atom", Atom), ("time", Time), ("state", c_int)]


class XFixesSelectionNotifyEvent(Structure):
    _fields_ = [("type", c_int), ("serial", c_ulong), ("send_event", Bool), ("display", c_void_p),
                ("window", Window), ("subtype", c_int), ("owner", Window), ("selection", Atom),
                ("timestamp", Time), ("selection_timestamp", Time)]


class XEvent(Union):
    _fields_ = [("type", c_int), ("xselectionrequest", XSelectionRequestEvent),
                ("xselection", XSelectionEvent), ("xselectionclear", XSelectionClearEvent),
                ("xproperty", XPropertyEvent), ("xfixes", XFixesSelectionNotifyEvent),
                ("pad", c_long * 24)]


class XErrorEvent(Structure):
    _fields_ = [("type", c_int), ("display", c_void_p), ("resourceid", c_ulong), ("serial", c_ulong),
                ("error_code", c_ubyte), ("request_code", c_ubyte), ("minor_code", c_ubyte)]


XErrorHandler = ctypes.CFUNCTYPE(c_int, c_void_p, POINTER(XErrorEvent))


def load_libs():
    x11 = ctypes.CDLL("libX11.so.6")
    xfixes = ctypes.CDLL("libXfixes.so.3")
    x11.XOpenDisplay.restype = c_void_p
    x11.XOpenDisplay.argtypes = [c_char_p]
    x11.XCloseDisplay.argtypes = [c_void_p]
    x11.XDefaultRootWindow.restype = Window
    x11.XDefaultRootWindow.argtypes = [c_void_p]
    x11.XCreateSimpleWindow.restype = Window
    x11.XCreateSimpleWindow.argtypes = [c_void_p, Window, c_int, c_int, c_uint, c_uint, c_uint, c_ulong, c_ulong]
    x11.XDestroyWindow.argtypes = [c_void_p, Window]
    x11.XInternAtom.restype = Atom
    x11.XInternAtom.argtypes = [c_void_p, c_char_p, Bool]
    x11.XSelectInput.argtypes = [c_void_p, Window, c_long]
    x11.XSetSelectionOwner.argtypes = [c_void_p, Atom, Window, Time]
    x11.XGetSelectionOwner.restype = Window
    x11.XGetSelectionOwner.argtypes = [c_void_p, Atom]
    x11.XConvertSelection.argtypes = [c_void_p, Atom, Atom, Atom, Window, Time]
    x11.XNextEvent.argtypes = [c_void_p, POINTER(XEvent)]
    x11.XPending.restype = c_int
    x11.XPending.argtypes = [c_void_p]
    x11.XConnectionNumber.restype = c_int
    x11.XConnectionNumber.argtypes = [c_void_p]
    x11.XSendEvent.restype = c_int
    x11.XSendEvent.argtypes = [c_void_p, Window, Bool, c_long, POINTER(XEvent)]
    x11.XChangeProperty.argtypes = [c_void_p, Window, Atom, Atom, c_int, c_int, c_void_p, c_int]
    x11.XGetWindowProperty.restype = c_int
    x11.XGetWindowProperty.argtypes = [c_void_p, Window, Atom, c_long, c_long, Bool, Atom,
                                       POINTER(Atom), POINTER(c_int), POINTER(c_ulong),
                                       POINTER(c_ulong), POINTER(POINTER(c_ubyte))]
    x11.XDeleteProperty.argtypes = [c_void_p, Window, Atom]
    x11.XFree.argtypes = [c_void_p]
    x11.XFlush.argtypes = [c_void_p]
    x11.XSync.argtypes = [c_void_p, Bool]
    x11.XSetErrorHandler.restype = c_void_p
    x11.XSetErrorHandler.argtypes = [XErrorHandler]
    xfixes.XFixesQueryExtension.restype = Bool
    xfixes.XFixesQueryExtension.argtypes = [c_void_p, POINTER(c_int), POINTER(c_int)]
    xfixes.XFixesSelectSelectionInput.argtypes = [c_void_p, Window, Atom, c_ulong]
    return x11, xfixes


def _error_handler(_dpy, ev):
    e = ev.contents
    dbg("erro X ignorado: code=%d request=%d resource=0x%x" % (e.error_code, e.request_code, e.resourceid))
    return 0


_err_cb = XErrorHandler(_error_handler)


# ---------------------------------------------------------------- ponte
class Bridge:
    def __init__(self):
        self.x11, self.xfixes = load_libs()
        self.x11.XSetErrorHandler(_err_cb)

        name = os.environ.get("DISPLAY", ":0").encode()
        self.dpy = self.x11.XOpenDisplay(name)
        if not self.dpy:
            raise SystemExit("s9-clipbridge: nao consegui abrir o display %s" % name.decode())
        self.xfd = self.x11.XConnectionNumber(self.dpy)

        ev_base, err_base = c_int(0), c_int(0)
        if not self.xfixes.XFixesQueryExtension(self.dpy, byref(ev_base), byref(err_base)):
            raise SystemExit("s9-clipbridge: extensao XFIXES indisponivel")
        self.xfixes_event = ev_base.value  # XFixesSelectionNotify = base + 0

        root = self.x11.XDefaultRootWindow(self.dpy)
        self.win = self.x11.XCreateSimpleWindow(self.dpy, root, -10, -10, 1, 1, 0, 0, 0)
        self.x11.XSelectInput(self.dpy, self.win, PropertyChangeMask)

        a = lambda n: self.x11.XInternAtom(self.dpy, n.encode(), 0)
        self._atom = lambda n: self.x11.XInternAtom(self.dpy, n.encode(), 0)
        self.A = {n: a(n) for n in (
            "CLIPBOARD", "TARGETS", "TIMESTAMP", "UTF8_STRING", "TEXT", "text/plain",
            "text/plain;charset=utf-8", "INCR", "MULTIPLE", "S9_CLIP_PROP", "STRING")}
        self.xfixes.XFixesSelectSelectionInput(
            self.dpy, self.win, self.A["CLIPBOARD"], XFixesSetSelectionOwnerNotifyMask)
        self.x11.XFlush(self.dpy)

        self.atoms = dict(self.A)   # cache nome -> atom
        # estado X
        self.owned = None           # o que publicamos no CLIPBOARD: {"kind": "text"|"image", "data": bytes, ...}
        self.owned_time = CurrentTime
        self.last_x_sent = None     # ("text", str) | ("image", sha1) enviado ao Mir / publicado por nos (anti-eco)
        self.convert = None         # conversao em andamento: dict
        self.incr_out = {}          # (requestor, property) -> dict (INCR de saida)
        self.sock = None
        self.rbuf = b""
        self.next_connect = 0.0

    # ---- utilidades Xlib
    def atom(self, name):
        a = self.atoms.get(name)
        if a is None:
            a = self._atom(name)
            self.atoms[name] = a
        return a

    def atom_name(self, atom):
        for k, v in self.atoms.items():
            if v == atom:
                return k
        return "0x%x" % atom

    def read_property(self, win, prop, delete=True):
        """Le a propriedade inteira. Retorna (tipo, formato, bytes) ou None."""
        actual_type, actual_fmt = Atom(0), c_int(0)
        nitems, after = c_ulong(0), c_ulong(0)
        data = POINTER(c_ubyte)()
        chunks = []
        offset = 0
        atype, afmt = 0, 0
        while True:
            rc = self.x11.XGetWindowProperty(
                self.dpy, win, prop, offset, 65536, 0, AnyPropertyType, byref(actual_type),
                byref(actual_fmt), byref(nitems), byref(after), byref(data))
            if rc != 0 or actual_type.value == 0:
                if data:
                    self.x11.XFree(data)
                return None
            atype, afmt = actual_type.value, actual_fmt.value
            unit = {8: 1, 16: 2, 32: 8}.get(afmt, 1)  # formato 32 usa long (8 bytes)
            n = nitems.value * unit
            chunks.append(string_at(data, n))
            self.x11.XFree(data)
            data = POINTER(c_ubyte)()
            offset += (n + 3) // 4
            if after.value == 0:
                break
        if delete:
            self.x11.XDeleteProperty(self.dpy, win, prop)
        return atype, afmt, b"".join(chunks)

    def set_property(self, win, prop, ptype, fmt, payload, nitems):
        buf = ctypes.create_string_buffer(payload, len(payload)) if payload else ctypes.create_string_buffer(1)
        self.x11.XChangeProperty(self.dpy, win, prop, ptype, fmt, PropModeReplace, buf, nitems)

    def send_notify(self, req, prop):
        ev = XEvent()
        ev.xselection.type = SelectionNotify
        ev.xselection.requestor = req.requestor
        ev.xselection.selection = req.selection
        ev.xselection.target = req.target
        ev.xselection.property = prop
        ev.xselection.time = req.time
        self.x11.XSendEvent(self.dpy, req.requestor, 0, 0, byref(ev))
        self.x11.XFlush(self.dpy)

    # ---- Mir -> X11
    def on_wayland_selection(self, kind, payload):
        if kind == b"W":
            text = payload.decode("utf-8", "replace")
            self.owned = {"kind": "text", "text": text, "data": text.encode("utf-8")}
            self.last_x_sent = ("text", text)  # o que o Wayland acabou de publicar nao deve voltar como "X11"
        else:
            nul = payload.find(b"\0")
            if nul <= 0:
                return
            mime = payload[:nul].decode("ascii", "replace")
            data = payload[nul + 1:]
            self.owned = {"kind": "image", "mime": mime, "data": data}
            self.last_x_sent = ("image", hashlib.sha1(data).hexdigest())
        self.x11.XSetSelectionOwner(self.dpy, self.A["CLIPBOARD"], self.win, CurrentTime)
        self.x11.XFlush(self.dpy)
        dbg("CLIPBOARD X11 agora e nosso (%s, %d bytes)" % (self.owned["kind"], len(self.owned["data"])))

    def on_wayland_no_text(self):
        if self.owned is not None:
            self.owned = None
            if self.x11.XGetSelectionOwner(self.dpy, self.A["CLIPBOARD"]) == self.win:
                self.x11.XSetSelectionOwner(self.dpy, self.A["CLIPBOARD"], 0, CurrentTime)
                self.x11.XFlush(self.dpy)
            dbg("selecao Wayland sem texto/imagem: soltamos o CLIPBOARD X11")

    # ---- X11 -> Mir
    def request_conversion(self, target_name, when):
        self.x11.XDeleteProperty(self.dpy, self.win, self.A["S9_CLIP_PROP"])
        self.x11.XConvertSelection(self.dpy, self.A["CLIPBOARD"], self.atom(target_name),
                                   self.A["S9_CLIP_PROP"], self.win, when)
        self.x11.XFlush(self.dpy)
        self.convert = {"target": target_name, "when": when, "deadline": time.time() + CONVERT_TIMEOUT,
                        "incr": False, "buf": bytearray()}
        dbg("pedido de conversao CLIPBOARD -> %s" % target_name)

    def finish_data(self, raw, target_name):
        self.convert = None
        if len(raw) > MAX_TEXT:
            log("dado do X11 grande demais (%d bytes); ignorado" % len(raw))
            return
        if target_name.startswith("image/"):
            if not raw:
                return
            key = ("image", hashlib.sha1(raw).hexdigest())
            if key == self.last_x_sent:
                dbg("imagem do X11 igual a ultima/propria; nao reenviada")
                return
            self.last_x_sent = key
            self.send_to_mir(b"Y", target_name.encode("ascii") + b"\0" + raw)
            log("imagem do X11 (%s, %d bytes) enviada ao Mir" % (target_name, len(raw)))
            return
        if target_name == "STRING":
            text = raw.decode("latin-1", "replace")
        else:
            text = raw.decode("utf-8", "replace")
        key = ("text", text)
        if text == "" or key == self.last_x_sent or (self.owned and self.owned["kind"] == "text" and self.owned["text"] == text):
            dbg("texto do X11 igual ao ultimo/proprio; nao reenviado")
            return
        self.last_x_sent = key
        self.send_to_mir(b"X", text.encode("utf-8"))
        log("texto do X11 (%d bytes) enviado ao Mir" % len(text.encode("utf-8")))

    def choose_target(self, atoms):
        for cand in ("UTF8_STRING", "STRING") + IMAGE_PREFER:
            if self.atom(cand) in atoms:
                return cand
        return None

    def on_selection_notify(self, ev):
        cv = self.convert
        if cv is None or ev.requestor != self.win or ev.selection != self.A["CLIPBOARD"]:
            return
        if ev.property == 0:  # recusado
            if cv["target"] == "TARGETS":
                self.request_conversion("UTF8_STRING", cv["when"])  # dono nao sabe listar: tenta texto direto
            elif cv["target"] == "UTF8_STRING":
                self.request_conversion("STRING", cv["when"])
            else:
                dbg("dono do CLIPBOARD recusou a conversao")
                self.convert = None
            return
        got = self.read_property(self.win, ev.property, delete=True)
        if got is None:
            self.convert = None
            return
        atype, fmt, payload = got
        if cv["target"] == "TARGETS":
            n = len(payload) // 8
            atoms = set(struct.unpack("<%dQ" % n, payload[:n * 8])) if fmt == 32 else set()
            choice = self.choose_target(atoms)
            if choice is None:
                dbg("dono do CLIPBOARD X11 nao oferece texto nem imagem suportada")
                self.convert = None
            else:
                self.request_conversion(choice, cv["when"])
            return
        if atype == self.A["INCR"]:
            cv["incr"] = True
            cv["deadline"] = time.time() + INCR_TIMEOUT
            dbg("transferencia INCR do X11 iniciada")
            return
        self.finish_data(payload, cv["target"])

    def on_property_notify(self, ev):
        # (a) INCR de entrada
        cv = self.convert
        if (cv and cv["incr"] and ev.window == self.win and ev.atom == self.A["S9_CLIP_PROP"]
                and ev.state == PropertyNewValue):
            got = self.read_property(self.win, self.A["S9_CLIP_PROP"], delete=True)
            if got is None:
                return
            payload = got[2]
            cv["deadline"] = time.time() + INCR_TIMEOUT
            if len(payload) == 0:
                self.finish_data(bytes(cv["buf"]), cv["target"])
            else:
                cv["buf"] += payload
                if len(cv["buf"]) > MAX_TEXT:
                    log("INCR do X11 passou do limite; abortado")
                    self.convert = None
            return
        # (b) INCR de saida: o requisitante apagou a propriedade -> manda o proximo pedaco
        if ev.state == PropertyDelete:
            key = (ev.window, ev.atom)
            job = self.incr_out.get(key)
            if job is not None:
                self.pump_incr(key, job)

    def on_xfixes_notify(self, ev):
        if ev.selection != self.A["CLIPBOARD"]:
            return
        if ev.owner == self.win:
            self.owned_time = ev.selection_timestamp
            return
        if ev.owner == 0:
            dbg("CLIPBOARD X11 ficou sem dono")
            return
        # outro cliente X11 virou dono: lista os alvos e busca texto ou imagem
        when = ev.selection_timestamp or CurrentTime
        self.request_conversion("TARGETS", when)

    # ---- servindo pedidos (somos donos)
    def on_selection_request(self, req):
        if self.owned is None or req.selection != self.A["CLIPBOARD"]:
            self.send_notify(req, 0)
            return
        prop = req.property or req.target
        A = self.A
        own = self.owned

        if own["kind"] == "image":
            mime_atom = self.atom(own["mime"])
            if req.target == A["TARGETS"]:
                targets = (Atom * 3)(A["TARGETS"], A["TIMESTAMP"], mime_atom)
                self.x11.XChangeProperty(self.dpy, req.requestor, prop, XA_ATOM, 32, PropModeReplace,
                                         cast(targets, c_void_p), 3)
                self.send_notify(req, prop)
            elif req.target == A["TIMESTAMP"]:
                val = (c_long * 1)(self.owned_time)
                self.x11.XChangeProperty(self.dpy, req.requestor, prop, XA_INTEGER, 32, PropModeReplace,
                                         cast(val, c_void_p), 1)
                self.send_notify(req, prop)
            elif req.target == mime_atom:
                self.serve_data(req, prop, mime_atom, own["data"])
            else:
                dbg("alvo nao suportado para imagem: %s" % self.atom_name(req.target))
                self.send_notify(req, 0)
            return

        tname = self.atom_name(req.target)
        if req.target == A["TARGETS"]:
            targets = (Atom * 7)(A["TARGETS"], A["TIMESTAMP"], A["UTF8_STRING"], A["STRING"], A["TEXT"],
                                 A["text/plain"], A["text/plain;charset=utf-8"])
            self.x11.XChangeProperty(self.dpy, req.requestor, prop, XA_ATOM, 32, PropModeReplace,
                                     cast(targets, c_void_p), 7)
            self.send_notify(req, prop)
        elif req.target == A["TIMESTAMP"]:
            val = (c_long * 1)(self.owned_time)
            self.x11.XChangeProperty(self.dpy, req.requestor, prop, XA_INTEGER, 32, PropModeReplace,
                                     cast(val, c_void_p), 1)
            self.send_notify(req, prop)
        elif req.target in (A["UTF8_STRING"], A["TEXT"], A["text/plain"], A["text/plain;charset=utf-8"]):
            self.serve_data(req, prop, A["UTF8_STRING"], own["data"])
        elif req.target == A["STRING"]:
            self.serve_data(req, prop, XA_STRING, own["text"].encode("latin-1", "replace"))
        else:
            dbg("alvo nao suportado: %s" % tname)
            self.send_notify(req, 0)

    def serve_data(self, req, prop, ptype, data):
        if len(data) <= INCR_THRESHOLD:
            self.set_property(req.requestor, prop, ptype, 8, data, len(data))
            self.send_notify(req, prop)
            return
        key = (req.requestor, prop)
        self.x11.XSelectInput(self.dpy, req.requestor, PropertyChangeMask)
        size = (c_long * 1)(len(data))
        self.x11.XChangeProperty(self.dpy, req.requestor, prop, self.A["INCR"], 32, PropModeReplace,
                                 cast(size, c_void_p), 1)
        self.incr_out[key] = {"data": data, "pos": 0, "type": ptype, "deadline": time.time() + INCR_TIMEOUT,
                              "done": False}
        self.send_notify(req, prop)
        dbg("respondendo por INCR (%d bytes)" % len(data))

    def pump_incr(self, key, job):
        requestor, prop = key
        job["deadline"] = time.time() + INCR_TIMEOUT
        if job["done"]:
            self.incr_out.pop(key, None)
            return
        chunk = job["data"][job["pos"]:job["pos"] + CHUNK]
        job["pos"] += len(chunk)
        self.set_property(requestor, prop, job["type"], 8, chunk, len(chunk))
        self.x11.XFlush(self.dpy)
        if not chunk:
            job["done"] = True  # pedaco vazio enviado; falta so o requisitante apagar

    def expire(self):
        now = time.time()
        if self.convert and now > self.convert["deadline"]:
            dbg("conversao expirou")
            self.convert = None
        for key in [k for k, j in self.incr_out.items() if now > j["deadline"]]:
            dbg("INCR de saida expirou")
            self.incr_out.pop(key, None)

    def on_selection_clear(self, ev):
        if ev.selection == self.A["CLIPBOARD"]:
            dbg("perdemos o CLIPBOARD X11 para outro cliente")
            self.owned = None

    # ---- X event loop
    def drain_x(self):
        ev = XEvent()
        while self.x11.XPending(self.dpy):
            self.x11.XNextEvent(self.dpy, byref(ev))
            t = ev.type
            if t == SelectionRequest:
                self.on_selection_request(ev.xselectionrequest)
            elif t == SelectionNotify:
                self.on_selection_notify(ev.xselection)
            elif t == SelectionClear:
                self.on_selection_clear(ev.xselectionclear)
            elif t == PropertyNotify:
                self.on_property_notify(ev.xproperty)
            elif t == self.xfixes_event:
                self.on_xfixes_notify(ev.xfixes)

    # ---- socket do Mir
    def connect_mir(self):
        now = time.time()
        if self.sock is not None or now < self.next_connect:
            return
        self.next_connect = now + 1.0
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            s.connect(SOCK_PATH)
        except OSError:
            s.close()
            return
        s.setblocking(False)
        self.sock = s
        self.rbuf = b""
        log("conectado ao Mir em %s" % SOCK_PATH)

    def drop_mir(self):
        if self.sock is not None:
            try:
                self.sock.close()
            except OSError:
                pass
            self.sock = None
            log("desconectado do Mir")

    def send_to_mir(self, kind, payload):
        if self.sock is None:
            return
        frame = kind + struct.pack(">I", len(payload)) + payload
        try:
            self.sock.setblocking(True)
            self.sock.settimeout(2.0)
            self.sock.sendall(frame)
            self.sock.setblocking(False)
        except OSError:
            self.drop_mir()

    def read_mir(self):
        try:
            data = self.sock.recv(65536)
        except BlockingIOError:
            return
        except OSError:
            self.drop_mir()
            return
        if not data:
            self.drop_mir()
            return
        self.rbuf += data
        while len(self.rbuf) >= 5:
            kind = self.rbuf[0:1]
            (n,) = struct.unpack(">I", self.rbuf[1:5])
            if n > MAX_TEXT:
                log("quadro grande demais do Mir; reconectando")
                self.drop_mir()
                return
            if len(self.rbuf) < 5 + n:
                break
            payload = self.rbuf[5:5 + n]
            self.rbuf = self.rbuf[5 + n:]
            if kind in (b"W", b"I"):
                self.on_wayland_selection(kind, payload)
                log("%s do Wayland (%d bytes) publicado no CLIPBOARD X11" % ("texto" if kind == b"W" else "imagem", len(payload)))
            elif kind == b"C":
                self.on_wayland_no_text()

    def run(self):
        stop = {"v": False}
        signal.signal(signal.SIGTERM, lambda *_: stop.__setitem__("v", True))
        signal.signal(signal.SIGINT, lambda *_: stop.__setitem__("v", True))
        log("iniciado (display %s, socket %s)" % (os.environ.get("DISPLAY", ":0"), SOCK_PATH))
        while not stop["v"]:
            self.connect_mir()
            self.drain_x()
            rlist = [self.xfd] + ([self.sock] if self.sock is not None else [])
            try:
                r, _, _ = select.select(rlist, [], [], 0.25)
            except InterruptedError:
                continue
            if self.sock is not None and self.sock in r:
                self.read_mir()
            self.drain_x()
            self.expire()
        self.x11.XCloseDisplay(self.dpy)


def main():
    Bridge().run()


if __name__ == "__main__":
    sys.exit(main())
