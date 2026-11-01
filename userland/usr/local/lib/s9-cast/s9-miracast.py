#!/usr/bin/env python3
# s9-miracast: "Screen Cast (WIFI)" = o S9 como SOURCE Miracast (Wi-Fi Direct) para TVs/tablets receptores.
#   s9-miracast scan            -> procura receptores Miracast (P2P find pelo NetworkManager) e grava $RUN/mira-targets.json
#   s9-miracast run             -> le o id em $RUN/mira.target, cria o grupo P2P (NetworkManager), serve o RTSP do Miracast
#                                  (porta 7236) e transmite a tela (mirscreencast -> ffmpeg -> RTP/MPEG-TS) + audio
#   s9-miracast cleanup         -> idempotente: apaga a conexao s9-miracast, remove grupos P2P, deixa a swlan0 desligada, restaura o audio
#   s9-miracast name <id>       -> imprime o nome do receptor
# Teste local sem P2P: S9_MIRA_LOCAL=1 s9-miracast run  (so serve o RTSP na 7236, o "receptor" conecta em 127.0.0.1).
# Fatos que importam (descobertos nos testes 1-25):
#  - a swlan0 precisa estar DOWN e nao gerenciada; o grupo P2P tem que ser criado pelo proprio NetworkManager (conexao wifi-p2p),
#    senao ele derruba o grupo; se formos GO (TV) subimos 192.168.49.1/24 e um servidor DHCP proprio;
#  - o RECEPTOR conecta por TCP na nossa porta 7236 (nos somos o servidor RTSP e falamos primeiro: M1 OPTIONS);
#  - o MPEG-TS precisa dos PIDs do Miracast (PMT 0x100, video 0x1011, audio 0x1100) e o audio e obrigatorio (AAC);
#    o muxer rtp_mpegts IGNORA -mpegts_* soltos: usar -streamid e -mpegts_muxer_options.
import os, sys, re, json, time, socket, struct, signal, subprocess, hashlib, threading, asyncio, traceback

RUN = os.environ.get("S9_CAST_RUN", "/run/s9-cast")
STATE = os.environ.get("S9_CAST_STATE", "/var/lib/s9-cast")
SOCK = os.environ.get("S9_CAST_SOCK", "/run/s9-miral/mir_socket")
AUDIO = os.environ.get("S9_CAST_AUDIO", "/usr/local/sbin/s9-cast-audio")
LOGF = os.environ.get("S9_MIRA_LOG", "/var/tmp/s9-miracast.log")
SCANLOG = "/var/tmp/s9-miracast-scan.log"
TARGETS = RUN + "/mira-targets.json"
STATUSF = RUN + "/mira.status"
ERRF = RUN + "/mira.error"
TARGETF = RUN + "/mira.target"
FFLOG = RUN + "/mira-ffmpeg.log"
UNIT = "s9-miracast.service"
LOCAL = bool(os.environ.get("S9_MIRA_LOCAL"))
RTSP_PORT = int(os.environ.get("S9_MIRA_PORT", "7236"))
WC = ["wpa_cli", "-p", "/run/wpa_supplicant", "-i", "wlan0"]
WFD_SRC = "00000600101c440050"      # source, sessao disponivel, porta 7236, throughput 80
CONN_ID = "s9-miracast"
UIBC_PORT = 7237        # EXPERIMENTO UIBC (entrada do receptor -> celular): porta TCP que anunciamos no M4
SELF = os.path.abspath(__file__)
_logfile = None


def log(*a):
    t = time.time()
    line = time.strftime("%H:%M:%S", time.localtime(t)) + ".%03d " % int((t % 1) * 1000) + " ".join(str(x) for x in a)
    print("s9-miracast:", line, file=sys.stderr, flush=True)
    if _logfile:
        try:
            _logfile.write(line + "\n"); _logfile.flush()
        except Exception:
            pass


def openlog(path):
    global _logfile
    try:
        _logfile = open(path, "w")
        os.chmod(path, 0o644)
    except Exception:
        _logfile = None


def readf(path, default=""):
    try:
        with open(path) as f:
            return f.read().strip()
    except Exception:
        return default


def atomic_write(path, text, mode=0o644):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = "%s.%d.tmp" % (path, os.getpid())
    with open(tmp, "w") as f:
        f.write(text)
    os.chmod(tmp, mode)
    os.replace(tmp, path)


def sh(cmd, timeout=30):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, (r.stdout + r.stderr).strip()
    except Exception as e:
        return 1, str(e)


def mask_mac(m):
    a = (m or "?").split(":")
    return ":".join(a[:3] + ["xx", "xx", a[5]]) if len(a) == 6 else (m or "?")


def tid_of(hw):
    return hashlib.sha1(("s9mira-" + hw.lower()).encode()).hexdigest()[:8]


def status(**kv):
    atomic_write(STATUSF, "".join("%s=%s\n" % (k, v) for k, v in kv.items()))


def fail(msg):
    log("ERRO:", msg)
    atomic_write(ERRF, msg[:160] + "\n")


def load_targets():
    try:
        d = json.loads(readf(TARGETS, "[]"))
        return [t for t in d if isinstance(t, dict) and t.get("id") and t.get("hw") and t.get("name")]
    except Exception:
        return []


# ------------------------------------------------------------------ preparo do Wi-Fi Direct
def swlan0_off():
    sh(["nmcli", "device", "set", "swlan0", "managed", "no"], 10)
    sh(["ip", "link", "set", "swlan0", "down"], 10)


def p2p_state():
    rc, out = sh(["nmcli", "-t", "-f", "DEVICE,STATE", "device"], 15)
    for line in out.splitlines():
        if line.startswith("p2p-dev-wlan0:"):
            return line.split(":", 1)[1]
    return ""


def remove_groups():
    rc, out = sh(WC + ["interface"], 10)
    for g in out.split():
        if g.startswith("p2p-wlan0"):
            sh(WC + ["p2p_group_remove", g], 10)


def prep_wpa():
    remove_groups()
    sh(WC + ["set", "device_name", "S9-Ubuntu"], 10)
    sh(WC + ["set", "wifi_display", "1"], 10)
    sh(WC + ["set", "wfd_subelems", WFD_SRC], 10)
    sh(WC + ["set", "p2p_go_intent", "0"], 10)


def p2p_works():
    """O P2P esta utilizavel? (o estado 'disconnected' do NM e a chamada StartFind enganam: apos o boot pode faltar a interface de gerencia P2P
    do supplicant; ai o NM so loga 'Could not find P2P mgmt interface' e o wpa_cli p2p_find responde FAIL.)"""
    rc, ifs = sh(WC + ["interface"], 10)
    has_dev = "p2p-dev-wlan0" in ifs.split()
    rc, out = sh(WC + ["p2p_find", "3"], 10)
    find_ok = "OK" in out.split()
    sh(WC + ["p2p_stop_find"], 10)
    ok = has_dev or find_ok
    return ok, "interfaces do supplicant: %s; p2p_find: %s" % (" ".join(ifs.split()[-3:]), out.strip().splitlines()[-1] if out.strip() else "?")


def restart_nm():
    log("reiniciando o NetworkManager para recuperar o dispositivo P2P")
    try:
        os.makedirs(RUN, exist_ok=True)
        open(RUN + "/nm-restarted", "w").write(str(int(time.time())))
    except Exception:
        pass
    sh(["systemctl", "restart", "NetworkManager"], 60)
    for _ in range(6):
        swlan0_off(); time.sleep(1)
    st = ""
    for _ in range(40):
        st = p2p_state()
        if st and st != "unavailable":
            break
        time.sleep(1)
    time.sleep(2)
    log("p2p-dev-wlan0 depois do restart:", st or "ausente")


def nm_restart_allowed(min_gap):
    try:
        return time.time() - float(readf(RUN + "/nm-restarted", "0")) > min_gap
    except ValueError:
        return True


def ensure_p2p(allow_restart):
    """O P2P do NetworkManager precisa funcionar de verdade; se nao, reinicia o NM (uma vez, com intervalo minimo)."""
    st = p2p_state()
    log("p2p-dev-wlan0 no NM:", st or "ausente")
    ok = st not in ("", "unavailable", "unmanaged")
    if ok:
        ok, err = p2p_works()
        if not ok:
            log("o P2P nao responde:", err)
    if not ok and allow_restart:
        restart_nm()
        st = p2p_state()
        ok = st not in ("", "unavailable", "unmanaged")
        if ok:
            ok, err = p2p_works()
            if not ok:
                log("o P2P continua sem responder:", err)
        if not ok:
            log("segundo estagio: reiniciando o wpa_supplicant (a wlan0 reconecta sozinha em alguns segundos)")
            sh(["systemctl", "restart", "wpa_supplicant"], 60)
            time.sleep(4)
            restart_nm()
            st = p2p_state()
            ok = st not in ("", "unavailable", "unmanaged")
            if ok:
                ok, err = p2p_works()
                log("depois do segundo estagio: %s (%s)" % ("P2P ok" if ok else "P2P ainda sem responder", err))
    swlan0_off()
    return ok


def wlan0_connected():
    rc, out = sh(["iw", "dev", "wlan0", "link"], 10)
    return out.startswith("Connected")


# ------------------------------------------------------------------ libnm (processos auxiliares: scan e nmconnect)
def parse_wfd(b):
    """WFD IE do peer -> (e_sink, texto). Subelemento 0: id(1) len(2) devinfo(2) porta(2) throughput(2); tipo = devinfo & 3."""
    try:
        if len(b) >= 5 and b[0] == 0:
            dev = (b[3] << 8) | b[4]
            return (dev & 3) in (1, 3)
    except Exception:
        pass
    return False


def nm_find(secs):
    import gi
    gi.require_version("NM", "1.0")
    from gi.repository import NM, GLib
    c = NM.Client.new(None)
    dev = next((d for d in c.get_devices() if d.get_iface() == "p2p-dev-wlan0"), None)
    if dev is None:
        raise RuntimeError("sem p2p-dev-wlan0 no NetworkManager")
    loop = GLib.MainLoop()
    res = {}
    errs = []

    def collect():
        for p in dev.get_peers():
            ies = p.get_wfd_ies()
            b = ies.get_data() if ies is not None else b""
            hw = (p.get_hw_address() or "").lower()
            if not hw:
                continue
            res[hw] = {"name": p.get_name() or hw, "hw": hw, "strength": p.get_strength(), "sink": parse_wfd(b), "wfd": b.hex()}

    def find_done(d, r, data):
        try:
            d.start_find_finish(r)
        except Exception as e:
            log("StartFind falhou:", e)
            errs.append(str(e))
            loop.quit()

    def poll():
        collect()
        return True

    def end():
        collect()
        try:
            dev.stop_find(None, lambda d, r, x: (d.stop_find_finish(r), loop.quit()), None)
        except Exception as e:
            log("stop_find:", e)
        GLib.timeout_add(1500, lambda: (loop.quit(), False)[1])
        return False

    dev.start_find(None, None, find_done, None)
    GLib.timeout_add(500, poll)
    GLib.timeout_add(int(secs * 1000), end)
    loop.run()
    if errs:
        raise RuntimeError("StartFind falhou: " + errs[0])
    return res


def do_scan():
    os.makedirs(RUN, exist_ok=True)
    openlog(SCANLOG)
    if sh(["systemctl", "is-active", UNIT], 10)[1].strip() in ("active", "activating"):
        print("ocupado: transmitindo")
        return 0
    swlan0_off()
    prep_wpa()
    if not ensure_p2p(nm_restart_allowed(300)):
        log("dispositivo P2P do NetworkManager indisponivel")
        print("indisponivel")
        return 1
    try:
        found = nm_find(5.5)
    except Exception as e:
        log("scan falhou:", e)
        print("falhou: %s" % e)
        return 1
    now = time.time()
    old = {t["hw"]: t for t in load_targets()}
    out = {}
    for hw, p in found.items():
        log("peer: %r hw=%s forca=%s sink=%s wfd=%s" % (p["name"], mask_mac(hw), p["strength"], p["sink"], p["wfd"]))
        if not p["sink"]:
            continue
        out[hw] = {"id": tid_of(hw), "name": p["name"], "hw": hw, "strength": p["strength"], "seen": now}
    for hw, t in old.items():
        if hw not in out and now - float(t.get("seen", 0)) < 180:
            out[hw] = t
    lst = sorted(out.values(), key=lambda t: t["name"].lower())
    atomic_write(TARGETS, json.dumps(lst))
    print("receptores: " + ", ".join(t["name"] for t in lst) if lst else "nenhum receptor")
    return 0


def nm_connect(hw):
    """Cria e ativa a conexao wifi-p2p para o peer (o NetworkManager forma o grupo). Sai com 0 se ATIVADA."""
    import gi
    gi.require_version("NM", "1.0")
    from gi.repository import NM, GLib
    T0 = time.time()

    def plog(*a):
        print("[%5.1fs]" % (time.time() - T0), *a, flush=True)

    c = NM.Client.new(None)
    dev = next((d for d in c.get_devices() if d.get_iface() == "p2p-dev-wlan0"), None)
    if dev is None:
        plog("sem p2p-dev-wlan0 no NetworkManager")
        return 2
    loop = GLib.MainLoop()
    st = {"done": False, "peer": None, "rc": 1}

    def finish(msg, rc):
        if st["done"]:
            return
        st["done"] = True
        st["rc"] = rc
        plog("FIM:", msg)
        GLib.timeout_add(300, lambda: (loop.quit(), False)[1])

    def stop_cb(d, r, data):
        try:
            d.stop_find_finish(r)
        except Exception as e:
            plog("stop_find:", e)

    def on_act(cl, r, data):
        try:
            ac = cl.add_and_activate_connection_finish(r)
        except Exception as e:
            finish("add_and_activate falhou: %s" % e, 1)
            return

        def acs(a, p):
            s = a.get_state()
            plog("conexao ativa ->", s.value_nick, "(%s)" % a.get_state_reason().value_nick)
            if s == NM.ActiveConnectionState.ACTIVATED:
                finish("ATIVADA", 0)
            elif s in (NM.ActiveConnectionState.DEACTIVATED, NM.ActiveConnectionState.DEACTIVATING):
                finish("desativada", 1)
        ac.connect("notify::state", acs)
        acs(ac, None)

    def connect_peer(peer):
        try:
            dev.stop_find(None, stop_cb, None)
        except Exception as e:
            plog("stop_find nao chamado:", e)
        conn = NM.SimpleConnection.new()
        sc = NM.SettingConnection.new()
        sc.set_property(NM.SETTING_CONNECTION_ID, CONN_ID)
        sc.set_property(NM.SETTING_CONNECTION_TYPE, "wifi-p2p")
        sc.set_property(NM.SETTING_CONNECTION_AUTOCONNECT, False)
        conn.add_setting(sc)
        sp = NM.SettingWifiP2P.new()
        sp.set_property("peer", peer.get_hw_address())
        try:
            sp.set_property("wps-method", NM.SettingWirelessSecurityWpsMethod.PBC)
        except Exception as e:
            plog("wps-method:", e)
        sp.set_property("wfd-ies", GLib.Bytes.new(bytes.fromhex(WFD_SRC)))
        conn.add_setting(sp)
        s4 = NM.SettingIP4Config.new(); s4.set_property("method", "disabled"); conn.add_setting(s4)
        s6 = NM.SettingIP6Config.new(); s6.set_property("method", "ignore"); conn.add_setting(s6)
        plog("ativando a conexao wifi-p2p (aceite o pedido na tela do receptor)")
        c.add_and_activate_connection_async(conn, dev, peer.get_path(), None, on_act, None)

    def find_done(d, r, data):
        try:
            d.start_find_finish(r)
            plog("StartFind ok")
        except Exception as e:
            finish("StartFind falhou: %s" % e, 1)

    def poll():
        if st["done"] or st["peer"]:
            return False
        for p in dev.get_peers():
            if (p.get_hw_address() or "").lower() == hw.lower():
                st["peer"] = p
                plog("receptor encontrado: %r forca=%s" % (p.get_name(), p.get_strength()))
                connect_peer(p)
                return False
        return True

    dev.start_find(None, None, find_done, None)
    GLib.timeout_add(500, poll)
    GLib.timeout_add_seconds(25, lambda: (None if st["peer"] or st["done"] else finish("receptor nao apareceu em 25 s", 3)) or False)
    GLib.timeout_add_seconds(120, lambda: (finish("tempo esgotado", 4) if not st["done"] else None) or False)
    loop.run()
    return st["rc"]


# ------------------------------------------------------------------ DHCP (quando somos o GO)
class Dhcp(threading.Thread):
    def __init__(self, iface, gw):
        super().__init__(daemon=True)
        self.iface, self.gw, self.stop = iface, gw, False
        self.net = gw.rsplit(".", 1)[0]
        self.leases = {}

    @staticmethod
    def opts(d):
        o = {}; i = 240
        while i < len(d) and d[i] != 255:
            if d[i] == 0:
                i += 1; continue
            if i + 1 >= len(d):
                break
            l = d[i + 1]; o[d[i]] = d[i + 2:i + 2 + l]; i += 2 + l
        return o

    def build(self, req, typ, yi):
        gw = self.gw
        h = bytearray(240)
        h[0] = 2; h[1] = 1; h[2] = 6
        h[4:8] = req[4:8]; h[10:12] = req[10:12]
        h[16:20] = socket.inet_aton(yi); h[20:24] = socket.inet_aton(gw); h[28:44] = req[28:44]
        h[236:240] = bytes([99, 130, 83, 99])
        o = (bytes([53, 1, typ, 54, 4]) + socket.inet_aton(gw) + bytes([51, 4]) + struct.pack("!I", 3600) + bytes([1, 4]) + socket.inet_aton("255.255.255.0")
             + bytes([3, 4]) + socket.inet_aton(gw) + bytes([6, 4]) + socket.inet_aton(gw) + bytes([255]))
        return bytes(h) + o

    def run(self):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            s.setsockopt(socket.SOL_SOCKET, 25, self.iface.encode())    # SO_BINDTODEVICE
            s.bind(("0.0.0.0", 67)); s.settimeout(0.5)
        except Exception as e:
            log("DHCP: nao consegui abrir a porta 67:", e)
            return
        log("servidor DHCP em %s (%s/24)" % (self.iface, self.gw))
        while not self.stop:
            try:
                d, a = s.recvfrom(1500)
            except socket.timeout:
                continue
            except OSError as e:
                log("DHCP erro:", e); break
            if len(d) < 241 or d[0] != 1 or d[236:240] != bytes([99, 130, 83, 99]):
                continue
            o = self.opts(d); mt = o.get(53, b"\0")[0]; mac = d[28:34].hex(":"); m = mac[:8] + ":xx:xx:xx"
            ip = self.leases.setdefault(mac, "%s.%d" % (self.net, 100 + len(self.leases)))
            try:
                if mt == 1:
                    s.sendto(self.build(d, 2, ip), ("255.255.255.255", 68)); log("DHCP DISCOVER de %s -> OFFER %s" % (m, ip))
                elif mt == 3:
                    want = o.get(50) or d[12:16]
                    if want != socket.inet_aton(ip):
                        s.sendto(self.build(d, 6, "0.0.0.0"), ("255.255.255.255", 68)); log("DHCP REQUEST de %s -> NAK" % m)
                    else:
                        s.sendto(self.build(d, 5, ip), ("255.255.255.255", 68)); log("DHCP REQUEST de %s -> ACK %s" % (m, ip))
            except OSError as e:
                log("DHCP envio:", e)
        try:
            s.close()
        except Exception:
            pass


# ------------------------------------------------------------------ captura + codificacao
MODES = {   # bit CEA: (largura, altura, fps, nivel minimo exigido (bit da mascara de nivel), bitrate)
    0x80: (1920, 1080, 30, 0x04, "6M"),
    0x20: (1280, 720, 30, 0x01, "4M"),
    0x01: (640, 480, 60, 0x01, "2M"),
}
LEVELS = {0x01: "3.1", 0x02: "3.2", 0x04: "4.0", 0x08: "4.1", 0x10: "4.2"}


def quality():
    return "light" if readf(STATE + "/quality") == "light" else "normal"


def uibc_mode():
    """EXPERIMENTO: $STATE/mira_uibc = late | m4 | generic (vazio/off = desligado)."""
    v = readf(STATE + "/mira_uibc")
    return v if v in ("late", "m4", "generic") else ""


GEN_IDS = {0: "TouchDown", 1: "TouchUp", 2: "TouchMove", 3: "KeyDown", 4: "KeyUp", 5: "Zoom", 6: "ScrollV", 7: "ScrollH", 8: "Rotate"}


def uibc_parse(buf):
    """Decodifica pacotes UIBC: cabecalho 16 bits (versao 3, T 1, reservado 8, categoria 4) + tamanho 16 bits (+ timestamp 16 se T=1).
    Retorna (linhas de texto, bytes restantes). Melhor esforco: o objetivo do experimento e VER o que o receptor manda."""
    out = []
    while len(buf) >= 4:
        v = (buf[0] << 8) | buf[1]
        ver, t, cat = (v >> 13) & 7, (v >> 12) & 1, v & 0xf
        ln = (buf[2] << 8) | buf[3]
        if ln < 4 or ln > 4096 or ver != 0:
            out.append("formato inesperado (versao=%d tamanho=%d); bytes: %s" % (ver, ln, buf[:48].hex()))
            return out, b""
        if len(buf) < ln:
            break
        pkt, buf = buf[:ln], buf[ln:]
        hl = 6 if t else 4
        ts = ((pkt[4] << 8) | pkt[5]) if t else None
        body = pkt[hl:]
        desc = "cat=%s len=%d%s" % ({0: "GENERIC", 1: "HIDC"}.get(cat, cat), ln, (" ts=%d" % ts) if ts is not None else "")
        try:
            if cat == 0 and len(body) >= 3:
                mid = body[0]; blen = (body[1] << 8) | body[2]; pl = body[3:]
                desc += " %s" % GEN_IDS.get(mid, "msg%d" % mid)
                if mid in (0, 1, 2) and pl:
                    n = pl[0]; pts = []
                    for k in range(n):
                        o = 1 + k * 5
                        if o + 5 <= len(pl):
                            pts.append("id%d(%d,%d)" % (pl[o], (pl[o + 1] << 8) | pl[o + 2], (pl[o + 3] << 8) | pl[o + 4]))
                    desc += " " + " ".join(pts)
                elif mid in (3, 4) and len(pl) >= 5:
                    desc += " tecla1=0x%04x tecla2=0x%04x" % ((pl[1] << 8) | pl[2], (pl[3] << 8) | pl[4])
                elif mid in (6, 7) and len(pl) >= 2:
                    desc += " quantidade=%d" % int.from_bytes(pl[-2:], "big", signed=True)
        except Exception as e:
            desc += " (erro ao decodificar: %s)" % e
        out.append(desc + " | " + pkt[:40].hex())
    return out, buf


class SynWatch(threading.Thread):
    """EXPERIMENTO: registra quem abre conexoes TCP no grupo P2P (descobrir se o receptor conecta e em que porta)."""
    def __init__(self, iface):
        super().__init__(daemon=True)
        self.iface, self.stop, self.seen = iface, False, set()

    def run(self):
        try:
            s = socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.htons(3))
            s.bind((self.iface, 0)); s.settimeout(0.5)
        except Exception as e:
            log("UIBC/sniff: nao consegui abrir a captura:", e)
            return
        while not self.stop:
            try:
                pkt = s.recv(2048)
            except socket.timeout:
                continue
            except OSError:
                break
            if len(pkt) < 54 or pkt[12:14] != b"\x08\x00":
                continue
            ihl = (pkt[14] & 0xf) * 4
            if pkt[23] != 6 or len(pkt) < 14 + ihl + 14:
                continue
            tcp = pkt[14 + ihl:]
            flags = tcp[13]
            if (flags & 0x12) != 0x02:        # so SYN puro (inicio de conexao)
                continue
            src, dst = socket.inet_ntoa(pkt[26:30]), socket.inet_ntoa(pkt[30:34])
            sp, dp = (tcp[0] << 8) | tcp[1], (tcp[2] << 8) | tcp[3]
            key = (src, dst, dp)
            if key not in self.seen:
                self.seen.add(key)
                log("TCP novo no grupo: %s:%d -> %s:%d" % (src, sp, dst, dp))
        try:
            s.close()
        except Exception:
            pass


def pick_video(v):
    """Escolhe o modo a partir da oferta (M3). Retorna (texto do M4, W, H, fps, nivel x264, bitrate) ou None."""
    try:
        f = v.split(",")[0].split()
        prof = int(f[2], 16); lvl = int(f[3], 16); cea = int(f[4], 16)
    except Exception:
        return None
    order = [0x80, 0x20, 0x01] if quality() == "normal" else [0x20, 0x01]
    pb = 1 if prof & 1 else (prof & -prof)
    for bit in order:
        if not (cea & bit):
            continue
        w, h, fps, need, br = MODES[bit]
        cand = [b for b in (0x01, 0x02, 0x04, 0x08, 0x10) if (lvl & b) and b >= need]
        if not cand:
            continue
        lb = cand[0]
        return ("00 00 %02x %02x %08x 00000000 00000000 00 0000 0000 00 none none" % (pb, lb, bit), w, h, fps, LEVELS[lb], br)
    return None


def screen_probe():
    r = subprocess.run(["mirscreencast", "-m", SOCK, "--query"], capture_output=True, text=True, timeout=15)
    o = r.stdout
    m1 = re.search(r"Colorspace:\s*(\w+)", o)
    m2 = re.search(r"Output size:\s*(\d+)x(\d+)", o)
    m3 = re.search(r"Capture rate \(Hz\):\s*(\d+)", o)
    if not (m1 and m2 and m3) or m1.group(1).lower() not in ("rgba", "bgra"):
        raise RuntimeError("nao consegui consultar a tela (mirscreencast --query)")
    return int(m2.group(1)), int(m2.group(2)), int(m3.group(1)), m1.group(1).lower()


def audio_ok():
    if readf(STATE + "/audio") == "off":
        return False
    try:
        return subprocess.run([AUDIO, "check"], capture_output=True, timeout=15).returncode == 0
    except Exception:
        return False


def av_offset():
    try:
        v = int(readf(STATE + "/mira_av_offset", "0"))
    except ValueError:
        v = 0
    return max(-1000, min(3000, v)) / 1000.0


def pipeline_cmd(sink, rport, vid, have_audio):
    W, H, HZ, PF = screen_probe()
    inter = max(1, (HZ + 15) // 30)
    tw, th, fps, lvl, br = vid[1], vid[2], vid[3], vid[4], vid[5]
    bufs = "%dM" % max(1, int(br[:-1]) // 2)
    aoff = av_offset()
    if have_audio:
        ain = "-thread_queue_size 1024 -f s16le -ar 48000 -ac 2 -use_wallclock_as_timestamps 1 %s-i <(exec '%s') " % (("-itsoffset %.3f " % aoff) if aoff < 0 else "", AUDIO)
    else:
        ain = "-re -f lavfi -i anullsrc=r=48000:cl=stereo "      # o receptor exige faixa de audio: manda silencio
    adl = (",adelay=%d|%d" % (round(aoff * 1000), round(aoff * 1000))) if (have_audio and aoff > 0) else ""
    vf = ("fps=%d,scale=w='min(iw,%d)':h='min(ih,%d)':force_original_aspect_ratio=decrease:force_divisible_by=2,"
          "pad=%d:%d:(ow-iw)/2:(oh-ih)/2:black,format=yuv420p") % (fps, tw, th, tw, th)
    cmd = ("exec mirscreencast -m '%s' --cap-interval %d --stdout 2>/dev/null | "
           "ffmpeg -nostdin -hide_banner -loglevel warning -thread_queue_size 512 -use_wallclock_as_timestamps 1 -f rawvideo -pix_fmt %s -video_size %dx%d -i - %s"
           "-map 0:v:0 -map 1:a:0 -vf \"%s\" "
           "-c:v libx264 -profile:v baseline -level %s -preset ultrafast -tune zerolatency -g %d -keyint_min %d -sc_threshold 0 -bf 0 "
           "-b:v %s -maxrate %s -bufsize %s -x264-params repeat-headers=1:aud=1 "
           "-c:a aac -b:a 128k -ar 48000 -ac 2 -af 'aresample=async=1000%s' "
           "-streamid 0:4113 -streamid 1:4352 -muxdelay 0.1 -mpegts_muxer_options mpegts_pmt_start_pid=256:pcr_period=40 "
           "-f rtp_mpegts 'rtp://%s:%d?localport=5000&pkt_size=1328'") % (
        SOCK, inter, PF, W, H, ain, vf, lvl, fps, fps, br, br, bufs, adl, sink, rport)
    log("tela %dx%d @ %d Hz (%s) -> %dx%d@%d nivel %s %s, audio %s%s" % (
        W, H, HZ, PF, tw, th, fps, lvl, br, "capturado" if have_audio else "silencio",
        (" (atraso do som %+d ms)" % round(aoff * 1000)) if have_audio and aoff else ""))
    return cmd


# ------------------------------------------------------------------ sessao
PUBLIC = "org.wfa.wfd1.0, GET_PARAMETER, SET_PARAMETER, SETUP, PLAY, PAUSE, TEARDOWN"
M3_PARAMS = ["wfd_video_formats", "wfd_audio_codecs", "wfd_3d_video_formats", "wfd_content_protection", "wfd_display_edid", "wfd_coupled_sink",
             "wfd_client_rtp_ports", "wfd_I2C", "wfd_uibc_capability", "wfd_connector_type", "wfd_standby_resume_capability"]
SESSION = "6B8B4567"


def params(body):
    d = {}
    for line in body.replace("\r\n", "\n").split("\n"):
        if ":" in line:
            k, v = line.split(":", 1); d[k.strip()] = v.strip()
    return d


class Mira:
    def __init__(self, tid, tgt):
        self.tid, self.tgt = tid, tgt
        self.name = tgt["name"]
        self.base = dict(target=self.name, target_id=tid)
        self.stop = asyncio.Event()
        self.group = None
        self.role = None
        self.gone = asyncio.Event()       # sessao terminou (RTSP/ffmpeg/grupo)
        self.reason = None                # mensagem de erro (None = fim normal)
        self.evq = asyncio.Queue()
        self.jproc = None
        self.nmproc = None
        self.dhcp = None
        self.pipe = None
        self.keeper = None
        self.muted = False
        self.playing = False
        self.uibc = uibc_mode()
        self.uibc_srv = None
        self.uibc_n = 0
        self.uibc_lines = 0
        self.uibc_sink_port = None
        self.sink_ip = None
        self.syn = None
        self.step("Starting")

    def step(self, txt, state="connecting", **kw):
        d = dict(self.base); d.update(kw)
        status(state=state, step=txt, **d)
        log("estado:", state, "-", txt)

    def end(self, reason=None):
        if reason and not self.reason:
            self.reason = reason
        self.gone.set()

    # ---- eventos do wpa_supplicant (journal)
    async def journal(self):
        self.jproc = await asyncio.create_subprocess_exec("journalctl", "-u", "wpa_supplicant", "-f", "-n", "0", "-o", "cat",
                                                           stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
        while True:
            line = await self.jproc.stdout.readline()
            if not line:
                break
            l = line.decode("utf8", "replace").strip()
            if any(k in l for k in ("P2P-GROUP-STARTED", "P2P-GROUP-REMOVED", "P2P-GO-NEG-FAILURE", "P2P-GROUP-FORMATION-FAILURE", "P2P-INVITATION-RESULT")):
                await self.evq.put(l)
                if "PBC-OVERLAP" in l:
                    log("sobreposicao de PBC")
            if self.group and l.startswith("P2P-GROUP-REMOVED") and self.group in l:
                self.end("Wi-Fi Direct group dropped")

    async def nmlog(self):
        while True:
            line = await self.nmproc.stdout.readline()
            if not line:
                break
            log("nm:", line.decode("utf8", "replace").rstrip()[:200])

    # ---- rede do grupo
    async def setup_net(self, l):
        parts = l.split()
        self.group = parts[1]
        self.role = parts[2]
        ip = (re.search(r"ip_addr=([0-9.]+)", l) or [None, None])[1]
        log("grupo %s, nosso papel: %s" % (self.group, self.role))
        for _ in range(50):
            if os.path.isdir("/sys/class/net/" + self.group):
                break
            await asyncio.sleep(0.1)
        sh(["ip", "link", "set", self.group, "up"], 10)
        if self.role == "GO":
            sh(["ip", "-4", "addr", "flush", "dev", self.group], 10)
            rc, out = sh(["ip", "addr", "add", "192.168.49.1/24", "dev", self.group], 10)
            if rc:
                log("ip addr add:", out)
            self.dhcp = Dhcp(self.group, "192.168.49.1"); self.dhcp.start()
        else:
            rc, out = sh(["ip", "-4", "-o", "addr", "show", self.group], 10)
            if "inet " not in out and ip:
                sh(["ip", "addr", "add", ip + "/24", "dev", self.group], 10)

    # ---- EXPERIMENTO UIBC
    def uibc_m4(self, cap):
        log("UIBC: oferta do receptor (M3): %r" % cap)
        if not cap or cap.strip().lower() == "none" or "input_category_list" not in cap:
            log("UIBC: o receptor nao oferece UIBC (%r)" % cap)
            return None
        kv = {}
        for part in cap.split(";"):
            if "=" in part:
                k, v = part.split("=", 1); kv[k.strip()] = v.strip()
        m = re.search(r"port=(\d+)", cap)
        self.uibc_sink_port = int(m.group(1)) if m else None
        cats, gen, hid = kv.get("input_category_list", "GENERIC"), kv.get("generic_cap_list", "none"), kv.get("hidc_cap_list", "none")
        if self.uibc == "generic":
            cats, hid = "GENERIC", "none"
        return "wfd_uibc_capability: input_category_list=%s; generic_cap_list=%s; hidc_cap_list=%s; port=%d" % (cats, gen, hid, UIBC_PORT)

    def uibc_line(self, txt):
        self.uibc_lines += 1
        if self.uibc_lines <= 600:
            log("UIBC:", txt)
        elif self.uibc_lines == 601:
            log("UIBC: (muitas linhas; o resto nao e mostrado)")

    async def uibc_reader(self, r, w, who):
        buf = b""
        try:
            while not self.gone.is_set():
                d = await asyncio.wait_for(r.read(4096), 60)
                if not d:
                    log("UIBC: conexao fechada pelo receptor (%s)" % who)
                    break
                self.uibc_n += 1
                self.uibc_line("%d bytes brutos: %s" % (len(d), d[:64].hex()))
                buf += d
                lines, buf = uibc_parse(buf)
                for l in lines:
                    self.uibc_line(l)
        except asyncio.TimeoutError:
            log("UIBC: sem dados por 60 s (%s)" % who)
        except Exception as e:
            log("UIBC: erro de leitura (%s): %r" % (who, e))
        try:
            w.close()
        except Exception:
            pass

    async def uibc_handle(self, r, w):
        peer = w.get_extra_info("peername")
        log("UIBC: o receptor CONECTOU na nossa porta %d (%s:%s)" % (UIBC_PORT, peer[0], peer[1]))
        await self.uibc_reader(r, w, "entrada")

    async def uibc_enable(self, st):
        if self.uibc in ("late", "generic"):
            await asyncio.sleep(1.5)
            if self.gone.is_set():
                return
            log("UIBC: enviando wfd_uibc_setting: enable")
            st["req"]("SET_PARAMETER", "rtsp://localhost/wfd1.0", [("Content-Type", "text/parameters")], "wfd_uibc_setting: enable\r\n", "UIBC")
        await asyncio.sleep(5)
        if self.gone.is_set() or self.uibc_n:
            return
        if self.uibc_sink_port and self.sink_ip:
            log("UIBC: o receptor nao conectou; tentando conectar nele (%s:%d)" % (self.sink_ip, self.uibc_sink_port))
            try:
                r, w = await asyncio.wait_for(asyncio.open_connection(self.sink_ip, self.uibc_sink_port), 5)
                await self.uibc_reader(r, w, "saida")
            except Exception as e:
                log("UIBC: nao consegui conectar no receptor: %r" % e)
        else:
            log("UIBC: ate agora nenhuma conexao (o receptor anunciou port=%s)" % (self.uibc_sink_port or "none"))

    # ---- RTSP (nos somos o source/servidor; o receptor conecta e nos mandamos M1 primeiro)
    async def handle(self, r, w):
        peer = w.get_extra_info("peername")[0]
        me = w.get_extra_info("sockname")[0]
        log("CONEXAO RTSP: receptor %s -> %s:%d" % (peer, me, RTSP_PORT))
        self.sink_ip = peer
        self.step("Negotiating with the display")
        st = {"cseq": 0, "pend": {}, "m1": False, "m2": False, "m3": False}
        buf = b""

        async def recv(tmo):
            nonlocal buf
            while b"\r\n\r\n" not in buf:
                d = await asyncio.wait_for(r.read(4096), tmo)
                if not d:
                    return None
                buf += d
            head, _, rest = buf.partition(b"\r\n\r\n")
            m = re.search(rb"Content-Length:\s*(\d+)", head, re.I); n = int(m.group(1)) if m else 0
            while len(rest) < n:
                d = await asyncio.wait_for(r.read(4096), tmo)
                if not d:
                    break
                rest += d
            buf = rest[n:]
            lines = head.decode("utf8", "replace").split("\r\n")
            hd = {}
            for l in lines[1:]:
                if ":" in l:
                    k, v = l.split(":", 1); hd[k.strip().lower()] = v.strip()
            return lines[0], hd, rest[:n].decode("utf8", "replace")

        def req(method, uri, hdrs, body, tag):
            st["cseq"] += 1; c = st["cseq"]; st["pend"][c] = tag
            hs = "CSeq: %d\r\n" % c + "".join("%s: %s\r\n" % kv for kv in hdrs)
            if body:
                hs += "Content-Length: %d\r\n" % len(body.encode())
            w.write(("%s %s RTSP/1.0\r\n%s\r\n%s" % (method, uri, hs, body)).encode())
            log(">> %s %s %s" % (tag, method, body.replace("\r\n", " | ")[:300]))

        def reply(cs, extra="", code="200 OK"):
            w.write(("RTSP/1.0 %s\r\nCSeq: %s\r\n%s\r\n" % (code, cs, extra)).encode())

        st["req"] = req
        req("OPTIONS", "*", [("Require", "org.wfa.wfd1.0")], "", "M1")
        t_start = time.time(); idle = 0
        try:
            while not self.gone.is_set():
                try:
                    m = await recv(5)
                    idle = 0
                except asyncio.TimeoutError:
                    idle += 5
                    if self.playing:
                        if self.pipe is not None and self.pipe.returncode is not None:
                            self.end("The video encoder stopped"); break
                        continue
                    if idle >= 30:
                        self.end("The display stopped answering during setup"); break
                    continue
                if m is None:
                    log("o receptor fechou a conexao RTSP")
                    self.end("The display ended the connection" if self.playing else "The display closed the connection during setup")
                    break
                start, hd, body = m; cs = hd.get("cseq", "0")
                if start.startswith("RTSP/"):
                    tag = st["pend"].pop(int(cs) if cs.isdigit() else -1, "?")
                    log("<< resposta a %s: %s %s" % (tag, start, body.replace("\r\n", " | ")[:500] if tag == "M3" else ""))
                    if tag == "M1":
                        st["m1"] = True
                    elif tag == "M3":
                        c = params(body)
                        vid = pick_video(c.get("wfd_video_formats", ""))
                        if vid is None:
                            self.end("The display offers no compatible video mode"); break
                        if "AAC" not in c.get("wfd_audio_codecs", ""):
                            self.end("The display does not accept AAC audio"); break
                        mm = re.search(r"unicast\s+(\d+)", c.get("wfd_client_rtp_ports", ""))
                        st["vid"] = vid
                        st["rport"] = int(mm.group(1)) if mm else 19000
                        b = ["wfd_video_formats: " + vid[0], "wfd_audio_codecs: AAC 00000001 00", "wfd_content_protection: none",
                             "wfd_presentation_URL: rtsp://%s/wfd1.0/streamid=0 none" % me,
                             "wfd_client_rtp_ports: RTP/AVP/UDP;unicast %d 0 mode=play" % st["rport"]]
                        if self.uibc:
                            ul = self.uibc_m4(c.get("wfd_uibc_capability", ""))
                            if ul:
                                b.append(ul)
                                if self.uibc == "m4":
                                    b.append("wfd_uibc_setting: enable")
                        req("SET_PARAMETER", "rtsp://localhost/wfd1.0", [("Content-Type", "text/parameters")], "\r\n".join(b) + "\r\n", "M4")
                    elif tag == "M4":
                        req("SET_PARAMETER", "rtsp://localhost/wfd1.0", [("Content-Type", "text/parameters")], "wfd_trigger_method: SETUP\r\n", "M5")
                    elif tag == "M5":
                        log("M5 aceito; esperando o SETUP do receptor")
                else:
                    meth = start.split()[0]
                    log("<< pedido %s %s" % (start[:110], body.replace("\r\n", " | ")[:160]))
                    if meth == "OPTIONS":
                        reply(cs, "Public: %s\r\n" % PUBLIC); st["m2"] = True
                    elif meth == "SETUP":
                        tr = hd.get("transport", ""); mm = re.search(r"client_port=([\d-]+)", tr)
                        cp = mm.group(1) if mm else str(st.get("rport", 19000))
                        st["rport"] = int(cp.split("-")[0])
                        reply(cs, "Session: %s;timeout=30\r\nTransport: RTP/AVP/UDP;unicast;client_port=%s;server_port=5000-5001\r\n" % (SESSION, cp))
                    elif meth == "PLAY":
                        reply(cs, "Session: %s\r\n" % SESSION)
                        if "vid" not in st:
                            self.end("PLAY before the format negotiation"); break
                        await w.drain()
                        await self.start_stream(peer, st["rport"], st["vid"])
                        if self.uibc and st.get("uibc_started") is None:
                            st["uibc_started"] = True
                            asyncio.ensure_future(self.uibc_enable(st))
                    elif meth == "TEARDOWN":
                        reply(cs, "Session: %s\r\n" % SESSION); log("TEARDOWN do receptor")
                        await w.drain()
                        self.end("The display ended the session" if self.playing else None)
                        break
                    elif meth in ("GET_PARAMETER", "SET_PARAMETER", "PAUSE"):
                        reply(cs, ("Session: %s\r\n" % SESSION) if self.playing else "")
                    else:
                        reply(cs, "", "501 Not Implemented")
                if st["m1"] and st["m2"] and not st["m3"]:
                    st["m3"] = True
                    req("GET_PARAMETER", "rtsp://localhost/wfd1.0", [("Content-Type", "text/parameters")], "\r\n".join(M3_PARAMS) + "\r\n", "M3")
                await w.drain()
        except Exception as e:
            log("erro na sessao RTSP: %r" % e)
            self.end("RTSP error: %s" % e)
        try:
            w.close()
        except Exception:
            pass

    async def start_stream(self, sink, rport, vid):
        if self.playing:
            return
        self.step("Starting the video")
        loop = asyncio.get_running_loop()
        have_audio = await loop.run_in_executor(None, audio_ok)
        if have_audio and readf(STATE + "/phone_audio") != "on":
            def mute():
                r = subprocess.run([AUDIO, "setup"], capture_output=True, text=True, timeout=40)
                return r
            r = await loop.run_in_executor(None, mute)
            if r.returncode == 0:
                self.muted = True
                self.keeper = subprocess.Popen([AUDIO, "keep"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, preexec_fn=os.setsid)
                log("audio do celular desviado para o sink 'Screen Cast' (o celular fica mudo durante a transmissao)")
            else:
                log("nao consegui desviar o audio do celular:", (r.stderr or r.stdout).strip()[:120])
        cmd = pipeline_cmd(sink, rport, vid, have_audio)
        self.pipe = await asyncio.create_subprocess_exec("bash", "-c", cmd, stdout=asyncio.subprocess.DEVNULL, stderr=open(FFLOG, "wb"), start_new_session=True)
        self.playing = True
        self.step("Casting", state="streaming", res="%dx%d@%d" % (vid[1], vid[2], vid[3]))
        asyncio.ensure_future(self.watch_pipe())

    async def watch_pipe(self):
        while not self.gone.is_set():
            await asyncio.sleep(1)
            if self.pipe.returncode is not None:
                tail = readf(FFLOG)[-300:]
                log("o codificador terminou (codigo %s): %s" % (self.pipe.returncode, tail))
                self.end("The video encoder stopped")
                return

    # ---- ciclo completo
    async def main(self):
        if not LOCAL:
            asyncio.ensure_future(self.journal())
        srv = await asyncio.start_server(self.handle, "0.0.0.0", RTSP_PORT, reuse_address=True)
        log("servidor RTSP (Miracast source) escutando na porta %d" % RTSP_PORT)
        if self.uibc:
            self.uibc_srv = await asyncio.start_server(self.uibc_handle, "0.0.0.0", UIBC_PORT, reuse_address=True)
            log("EXPERIMENTO UIBC (modo %s): escutando na porta %d" % (self.uibc, UIBC_PORT))
        waiter = asyncio.ensure_future(self.stop.wait())
        if LOCAL:
            log("modo local (S9_MIRA_LOCAL): sem Wi-Fi Direct; aguardando o receptor em 127.0.0.1")
            self.step("Local test")
        else:
            self.step("Waiting for you to accept the request on the display")
            self.nmproc = await asyncio.create_subprocess_exec(sys.executable, SELF, "nmconnect", self.tgt["hw"],
                                                               stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
            asyncio.ensure_future(self.nmlog())
            t0 = time.time(); got = None; nm_done_at = None
            while got is None and not self.stop.is_set() and not self.gone.is_set():
                try:
                    l = await asyncio.wait_for(self.evq.get(), 1)
                except asyncio.TimeoutError:
                    l = None
                if l:
                    log("wpa:", re.sub(r'ssid="[^"]*"', 'ssid="***"', l)[:200])
                    if "P2P-GROUP-STARTED" in l:
                        got = l
                    elif "FAILURE" in l:
                        log("falha de negociacao P2P (aguardando o NetworkManager decidir)")
                if self.nmproc.returncode is not None and got is None:
                    nm_done_at = nm_done_at or time.time()
                    if time.time() - nm_done_at > 6:
                        self.end("Could not connect to the display (%s)" % ("not found" if self.nmproc.returncode == 3 else "NetworkManager error %s" % self.nmproc.returncode)); break
                if time.time() - t0 > 100 and got is None:
                    self.end("The display did not accept the connection in time"); break
            if got:
                await self.setup_net(got)
                if self.uibc:
                    self.syn = SynWatch(self.group); self.syn.start()
                self.step("Negotiating with the display")
                t1 = time.time()
        # espera o fim: pedido de parada, fim da sessao ou timeout de negociacao
        while not self.stop.is_set() and not self.gone.is_set():
            await asyncio.sleep(0.5)
            if not LOCAL and self.group and not self.playing and time.time() - t1 > 60:
                self.end("The display did not start the video session")
        srv.close()
        if self.uibc_srv:
            self.uibc_srv.close()
        if self.syn:
            self.syn.stop = True
        if self.uibc:
            log("UIBC: resumo: %d leituras de dados do receptor" % self.uibc_n)
        waiter.cancel()
        if self.stop.is_set():
            log("parada pedida")


def teardown(m=None):
    """Limpeza (sincrona e idempotente)."""
    try:
        if m is not None:
            if m.dhcp:
                m.dhcp.stop = True
            for p in (m.pipe,):
                if p is not None and p.returncode is None:
                    try:
                        os.killpg(p.pid, signal.SIGTERM)
                    except Exception:
                        pass
            if m.keeper is not None and m.keeper.poll() is None:
                try:
                    os.killpg(m.keeper.pid, signal.SIGTERM)
                except Exception:
                    pass
            for p in (m.nmproc, m.jproc):
                if p is not None and p.returncode is None:
                    try:
                        p.terminate()
                    except Exception:
                        pass
    except Exception:
        log("teardown:", traceback.format_exc())
    sh(["pkill", "-f", "rtp_mpegts"], 10)
    if not LOCAL:
        sh(["nmcli", "connection", "delete", "id", CONN_ID], 15)
        remove_groups()
        swlan0_off()
    rc, out = sh([AUDIO, "restore"], 45)
    if "restaurado" in out:
        log("audio do celular restaurado")


def do_run():
    os.makedirs(RUN, exist_ok=True)
    openlog(LOGF)
    for f in (ERRF, STATUSF, FFLOG):
        try:
            os.unlink(f)
        except OSError:
            pass
    tid = readf(TARGETF).split()
    tid = tid[0] if tid else ""
    if not re.fullmatch(r"[0-9a-f]{8}", tid):
        fail("invalid target")
        return 1
    tgt = next((t for t in load_targets() if t["id"] == tid), None)
    if LOCAL and not tgt:
        tgt = {"id": tid, "name": "Local test", "hw": "00:00:00:00:00:00"}
    if not tgt:
        fail("display not found; open the menu to refresh the list")
        return 1
    log("alvo: %s (%s) qualidade %s" % (tgt["name"], mask_mac(tgt["hw"]), quality()))
    if not LOCAL:
        swlan0_off()
        sh(["nmcli", "connection", "delete", "id", CONN_ID], 15)
        prep_wpa()
        if not ensure_p2p(True):
            fail("Wi-Fi Direct is unavailable in NetworkManager")
            return 1
    rc = 0
    m = Mira(tid, tgt)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    for s in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(s, m.stop.set)
    try:
        loop.run_until_complete(m.main())
    except Exception:
        log("ERRO:", traceback.format_exc())
        m.reason = m.reason or "internal error"
    finally:
        teardown(m)
        if m.reason:
            fail(m.reason)
            rc = 0
        for f in (STATUSF,):
            try:
                os.unlink(f)
            except OSError:
                pass
        t = readf(FFLOG)
        if t:
            log("ffmpeg (ultimas linhas):", t[-400:].replace("\n", " | "))
        log("sessao encerrada")
    return rc


def main():
    c = sys.argv[1] if len(sys.argv) > 1 else ""
    if c == "scan":
        return do_scan()
    if c == "run":
        return do_run()
    if c == "nmconnect" and len(sys.argv) > 2:
        return nm_connect(sys.argv[2])
    if c == "p2pcheck":
        try:
            nm_find(1.5)
            print("ok")
            return 0
        except Exception as e:
            print(str(e)[:200])
            return 1
    if c == "prep":
        # no boot: deixa o Wi-Fi Direct pronto (swlan0 desligada, ajustes WFD, P2P do NM funcionando)
        openlog("/var/tmp/s9-miracast-prep.log")
        swlan0_off()
        prep_wpa()
        ok = ensure_p2p(True)
        log("pronto" if ok else "P2P indisponivel")
        return 0 if ok else 1
    if c == "cleanup":
        teardown()
        try:
            os.unlink(STATUSF)
        except OSError:
            pass
        return 0
    if c == "name" and len(sys.argv) > 2:
        t = next((t for t in load_targets() if t["id"] == sys.argv[2]), None)
        print(t["name"] if t else "display")
        return 0
    print("uso: s9-miracast scan|run|cleanup|name <id>")
    return 1


if __name__ == "__main__":
    sys.exit(main())
