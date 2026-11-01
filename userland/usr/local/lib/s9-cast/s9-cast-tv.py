#!/usr/bin/env python3
# s9-cast-tv: transmite a tela do S9 para uma TV na rede local (Google Cast ou DLNA/UPnP).
#   s9-cast-tv scan   -> procura aparelhos (mDNS _googlecast + SSDP MediaRenderer) e grava $RUN/targets.json
#   s9-cast-tv run    -> le o id em $RUN/tv.target, captura a tela, serve por HTTP e manda a TV tocar
#                        (id 'web': so serve, e o navegador de um tablet/PC abre http://IP:8099/v/TOKEN/)
# So biblioteca padrao do Python 3 (o protocolo Cast v2 e codificado a mao).
import os, sys, json, time, socket, struct, ssl, threading, queue, subprocess, hashlib, re, signal
import urllib.request, urllib.parse
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

RUN = os.environ.get("S9_CAST_RUN", "/run/s9-cast")
STATE = os.environ.get("S9_CAST_STATE", "/var/lib/s9-cast")
SOCK = os.environ.get("S9_CAST_SOCK", "/run/s9-miral/mir_socket")
HTTP_PORT = int(os.environ.get("S9_CAST_HTTP_PORT", "8099"))
TARGETS = RUN + "/targets.json"
STATUSF = RUN + "/tv.status"
ERRF = RUN + "/tv.error"
AUDIO = os.environ.get("S9_CAST_AUDIO", "/usr/local/sbin/s9-cast-audio")
WEB_IDLE = int(os.environ.get("S9_CAST_WEB_IDLE", "300"))   # segundos sem espectador ate encerrar o modo web
APP_ID = "CC1AD845"      # Default Media Receiver
NS_CONN = "urn:x-cast:com.google.cast.tp.connection"
NS_HB = "urn:x-cast:com.google.cast.tp.heartbeat"
NS_RECV = "urn:x-cast:com.google.cast.receiver"
NS_MEDIA = "urn:x-cast:com.google.cast.media"


def log(*a):
    print("s9-cast-tv:", *a, file=sys.stderr, flush=True)


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


def myip():
    if os.environ.get("S9_CAST_HOST_IP"):
        return os.environ["S9_CAST_HOST_IP"]
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("1.1.1.1", 53))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


# ------------------------------------------------------------------ descoberta
def dns_name(d, o):
    labels = []
    end = None
    hops = 0
    while True:
        if o >= len(d):
            raise ValueError("nome truncado")
        l = d[o]
        if l == 0:
            o += 1
            break
        if l & 0xC0 == 0xC0:
            p = ((l & 0x3F) << 8) | d[o + 1]
            if end is None:
                end = o + 2
            o = p
            hops += 1
            if hops > 30:
                raise ValueError("loop de compressao")
            continue
        o += 1
        labels.append(d[o:o + l].decode("utf8", "replace"))
        o += l
    return ".".join(labels), (end if end is not None else o)


def dns_parse(d):
    """Devolve lista de (nome, tipo, rdata_offset, rdata_len) de todos os registros."""
    qd, an, ns, ar = struct.unpack(">HHHH", d[4:12])
    o = 12
    for _ in range(qd):
        _, o = dns_name(d, o)
        o += 4
    out = []
    for _ in range(an + ns + ar):
        name, o = dns_name(d, o)
        t, c, ttl, rl = struct.unpack(">HHIH", d[o:o + 10])
        o += 10
        out.append((name, t, o, rl))
        o += rl
    return out


def cast_from_packet(d):
    """Se o pacote mDNS descreve um Google Cast, devolve {'port','fn','md','id'}."""
    try:
        rrs = dns_parse(d)
    except Exception:
        return None
    if not any("_googlecast._tcp" in n for n, t, o, l in rrs):
        return None
    info = {"port": 8009, "fn": "", "md": "", "id": ""}
    got = False
    for n, t, o, l in rrs:
        if "_googlecast._tcp" not in n:
            continue
        if t == 33 and l >= 6:       # SRV
            info["port"] = struct.unpack(">H", d[o + 4:o + 6])[0]
            got = True
        elif t == 16:                # TXT
            p = o
            while p < o + l:
                n1 = d[p]
                s = d[p + 1:p + 1 + n1].decode("utf8", "replace")
                p += 1 + n1
                if "=" in s:
                    k, v = s.split("=", 1)
                    if k in ("fn", "md", "id"):
                        info[k] = v
                        got = True
    return info if got else None


def mdns_query(name):
    out = b"\x00\x00\x00\x00\x00\x01\x00\x00\x00\x00\x00\x00"
    for p in name.split("."):
        out += bytes([len(p)]) + p.encode()
    return out + b"\x00" + struct.pack(">HH", 12, 0x8001)   # PTR, classe IN, bit de resposta unicast


def scan_cast(ip, secs=4.0):
    m = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    m.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 255)
    m.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(ip))
    m.bind((ip, 0))
    m.settimeout(0.4)
    found = {}
    t0 = time.time()
    sent = 0
    while time.time() - t0 < secs:
        if sent < 3 and time.time() - t0 >= sent * 1.2:
            m.sendto(mdns_query("_googlecast._tcp.local"), ("224.0.0.251", 5353))
            sent += 1
        try:
            d, a = m.recvfrom(9000)
        except socket.timeout:
            continue
        info = cast_from_packet(d)
        if info:
            prev = found.get(a[0], {})
            prev.update({k: v for k, v in info.items() if v})
            found[a[0]] = prev
    m.close()
    return found


def lname(tag):
    return tag.rsplit("}", 1)[-1]


def parse_description(xml_text, location):
    """Acha um MediaRenderer com AVTransport; devolve {'name','control','stype'} ou None."""
    root = ET.fromstring(xml_text)
    base = location
    for e in root.iter():
        if lname(e.tag) == "URLBase" and (e.text or "").strip():
            base = e.text.strip()
    for dev in root.iter():
        if lname(dev.tag) != "device":
            continue
        kids = {lname(c.tag): c for c in dev}
        if "MediaRenderer" not in ((kids.get("deviceType").text or "") if kids.get("deviceType") is not None else ""):
            continue
        name = (kids["friendlyName"].text or "").strip() if "friendlyName" in kids else ""
        sl = kids.get("serviceList")
        if sl is None:
            continue
        for sv in sl:
            f = {lname(c.tag): (c.text or "").strip() for c in sv}
            if "AVTransport" in f.get("serviceType", ""):
                return {"name": name, "stype": f["serviceType"],
                        "control": urllib.parse.urljoin(base, f.get("controlURL", ""))}
    return None


def scan_dlna(ip, secs=4.0):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
    s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(ip))
    s.bind((ip, 0))
    s.settimeout(0.4)
    for st in ("urn:schemas-upnp-org:device:MediaRenderer:1", "urn:schemas-upnp-org:service:AVTransport:1"):
        msg = ('M-SEARCH * HTTP/1.1\r\nHOST: 239.255.255.250:1900\r\nMAN: "ssdp:discover"\r\nMX: 2\r\nST: %s\r\n\r\n' % st).encode()
        for _ in range(2):
            s.sendto(msg, ("239.255.255.250", 1900))
    locs = {}
    t0 = time.time()
    while time.time() - t0 < secs:
        try:
            d, a = s.recvfrom(4096)
        except socket.timeout:
            continue
        for line in d.decode("latin1").split("\r\n")[1:]:
            if line.lower().startswith("location:"):
                locs[line.split(":", 1)[1].strip()] = a[0]
    s.close()
    found = {}
    for loc, src in locs.items():
        if src in found:
            continue
        try:
            x = urllib.request.urlopen(loc, timeout=3).read().decode("utf8", "replace")
            r = parse_description(x, loc)
        except Exception:
            continue
        if r:
            found[src] = r
    return found


def merge_targets(cast, dlna, old, now):
    by_ip = {}
    for ip, c in cast.items():
        e = by_ip.setdefault(ip, {"ip": ip})
        e["cast"] = {"port": c.get("port", 8009), "model": c.get("md", "")}
        if c.get("fn"):
            e["name"] = c["fn"]
    for ip, dv in dlna.items():
        e = by_ip.setdefault(ip, {"ip": ip})
        e["dlna"] = {"control": dv["control"], "stype": dv["stype"]}
        e.setdefault("name", dv.get("name") or "")
    for ip, e in by_ip.items():
        e["seen"] = now
    # mantem por 2 minutos o que sumiu de uma busca (mDNS/SSDP perdem respostas)
    for t in old:
        if t.get("ip") not in by_ip and now - t.get("seen", 0) < 120:
            by_ip[t["ip"]] = t
    out = []
    for ip, e in by_ip.items():
        e["id"] = hashlib.sha1(("s9cast-" + ip).encode()).hexdigest()[:8]
        e["name"] = (e.get("name") or ip)[:40]
        out.append(e)
    out.sort(key=lambda t: (t["name"].lower(), t["ip"]))
    return out


def do_scan():
    ip = myip()
    res = {}

    def a():
        try:
            res["cast"] = scan_cast(ip)
        except Exception as e:
            log("scan cast:", e)
            res["cast"] = {}

    def b():
        try:
            res["dlna"] = scan_dlna(ip)
        except Exception as e:
            log("scan dlna:", e)
            res["dlna"] = {}
    th = [threading.Thread(target=a), threading.Thread(target=b)]
    for t in th:
        t.start()
    for t in th:
        t.join()
    try:
        old = json.loads(readf(TARGETS, "[]"))
    except Exception:
        old = []
    tg = merge_targets(res.get("cast", {}), res.get("dlna", {}), old, int(time.time()))
    atomic_write(TARGETS, json.dumps(tg))
    print("%d aparelho(s): %s" % (len(tg), ", ".join("%s%s%s" % (t["name"], "[cast]" if "cast" in t else "", "[dlna]" if "dlna" in t else "") for t in tg)))


# ------------------------------------------------------------------ Google Cast (CASTV2 a mao)
def varint(n):
    out = b""
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            out += bytes([b | 0x80])
        else:
            return out + bytes([b])


def ld(tag, b):
    return bytes([tag]) + varint(len(b)) + b


def cast_encode(src, dst, ns, payload):
    m = b"\x08\x00" + ld(0x12, src.encode()) + ld(0x1a, dst.encode()) + ld(0x22, ns.encode()) + b"\x28\x00" + \
        ld(0x32, json.dumps(payload).encode())
    return struct.pack(">I", len(m)) + m


def cast_decode(m):
    out = {}
    o = 0
    while o < len(m):
        key, o = read_varint(m, o)
        field, wt = key >> 3, key & 7
        if wt == 0:
            v, o = read_varint(m, o)
            out[field] = v
        elif wt == 2:
            n, o = read_varint(m, o)
            out[field] = m[o:o + n]
            o += n
        else:
            raise ValueError("wire type %d" % wt)
    return out


def read_varint(m, o):
    n = 0
    s = 0
    while True:
        b = m[o]
        o += 1
        n |= (b & 0x7F) << s
        if not b & 0x80:
            return n, o
        s += 7


class CastCtl:
    def __init__(self, ip, port):
        self.ip, self.port = ip, port
        self.sock = None
        self.cond = threading.Condition()
        self.recv_status = None
        self.media = None
        self.errors = []
        self.last_rx = time.time()
        self.closed = False
        self.was_playing = False
        self.transport = self.session = None
        self.rid = 0
        self.wlock = threading.Lock()

    def _id(self):
        self.rid += 1
        return self.rid

    def send(self, dst, ns, payload):
        with self.wlock:
            self.sock.sendall(cast_encode("sender-0", dst, ns, payload))

    def _read(self, n):
        b = b""
        while len(b) < n:
            c = self.sock.recv(n - len(b))
            if not c:
                raise ConnectionError("conexao fechada pela TV")
            b += c
        return b

    def _reader(self):
        try:
            while not self.closed:
                n = struct.unpack(">I", self._read(4))[0]
                if n > 1 << 20:
                    raise ValueError("mensagem grande demais")
                m = cast_decode(self._read(n))
                self.last_rx = time.time()
                try:
                    p = json.loads(m.get(6, b"{}").decode("utf8", "replace"))
                except Exception:
                    p = {}
                ty = p.get("type", "")
                if ty == "PING":
                    self.send(m.get(2, b"receiver-0").decode(), NS_HB, {"type": "PONG"})
                    continue
                with self.cond:
                    if ty == "RECEIVER_STATUS":
                        self.recv_status = p.get("status", {})
                    elif ty == "MEDIA_STATUS":
                        st = p.get("status") or []
                        if st:
                            self.media = st[0]
                            if self.media.get("playerState") in ("PLAYING", "BUFFERING"):
                                self.was_playing = True
                    elif ty in ("LOAD_FAILED", "INVALID_REQUEST", "LOAD_CANCELLED", "INVALID_PLAYER_STATE"):
                        self.errors.append("%s %s" % (ty, p.get("reason", "")))
                    elif ty == "CLOSE":
                        self.errors.append("a TV encerrou a sessao (CLOSE)")
                    self.cond.notify_all()
        except Exception as e:
            if not self.closed:
                with self.cond:
                    self.errors.append("conexao com a TV caiu: %s" % e)
                    self.cond.notify_all()

    def _heartbeat(self):
        while not self.closed:
            time.sleep(5)
            try:
                self.send("receiver-0", NS_HB, {"type": "PING"})
            except Exception:
                return

    def wait(self, pred, timeout, what):
        end = time.time() + timeout
        with self.cond:
            while True:
                if self.errors:
                    raise RuntimeError(self.errors[0])
                r = pred()
                if r:
                    return r
                left = end - time.time()
                if left <= 0:
                    raise RuntimeError("tempo esgotado esperando: " + what)
                self.cond.wait(min(left, 1.0))

    def play(self, url, ctype):
        raw = socket.create_connection((self.ip, self.port), 6)
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        self.sock = ctx.wrap_socket(raw)
        self.sock.settimeout(None)
        threading.Thread(target=self._reader, daemon=True).start()
        threading.Thread(target=self._heartbeat, daemon=True).start()
        self.send("receiver-0", NS_CONN, {"type": "CONNECT"})
        self.send("receiver-0", NS_RECV, {"type": "LAUNCH", "appId": APP_ID, "requestId": self._id()})

        def app():
            for a in (self.recv_status or {}).get("applications", []):
                if a.get("appId") == APP_ID and a.get("transportId"):
                    return a
        a = self.wait(app, 25, "o receptor de midia abrir na TV")
        self.transport, self.session = a["transportId"], a.get("sessionId")
        self.send(self.transport, NS_CONN, {"type": "CONNECT"})
        self.send(self.transport, NS_MEDIA, {
            "type": "LOAD", "requestId": self._id(), "sessionId": self.session, "autoplay": True, "currentTime": 0,
            "media": {"contentId": url, "streamType": "LIVE", "contentType": ctype,
                      "metadata": {"metadataType": 0, "title": "S9 Screen Cast"}}})
        self.wait(lambda: self.media and self.media.get("playerState") in ("PLAYING", "BUFFERING"), 30, "a TV abrir o video")

    def alive(self):
        if self.errors or self.closed:
            return False, (self.errors[0] if self.errors else "fechado")
        if time.time() - self.last_rx > 25:
            return False, "a TV parou de responder"
        with self.cond:
            apps = (self.recv_status or {}).get("applications", None)
            if apps is not None and not any(a.get("appId") == APP_ID for a in apps):
                return False, "a TV saiu do receptor (outro app ou parou pelo controle)"
            if self.media and self.was_playing and self.media.get("playerState") == "IDLE":
                return False, "reproducao encerrada na TV (%s)" % self.media.get("idleReason", "IDLE")
        return True, ""

    def stop(self):
        try:
            if self.sock and self.session:
                self.send("receiver-0", NS_RECV, {"type": "STOP", "sessionId": self.session, "requestId": self._id()})
                time.sleep(0.3)
        except Exception:
            pass
        self.closed = True
        try:
            self.sock.close()
        except Exception:
            pass


# ------------------------------------------------------------------ DLNA / UPnP AVTransport
class DlnaCtl:
    def __init__(self, control, stype):
        self.control, self.stype = control, stype
        self.was_playing = False

    def soap(self, action, inner="", timeout=6):
        body = ('<?xml version="1.0" encoding="utf-8"?><s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
                's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/"><s:Body><u:%s xmlns:u="%s"><InstanceID>0</InstanceID>%s'
                '</u:%s></s:Body></s:Envelope>') % (action, self.stype, inner, action)
        rq = urllib.request.Request(self.control, body.encode(), {
            "Content-Type": 'text/xml; charset="utf-8"', "SOAPAction": '"%s#%s"' % (self.stype, action)})
        try:
            return urllib.request.urlopen(rq, timeout=timeout).read().decode("utf8", "replace")
        except urllib.error.HTTPError as e:
            raise RuntimeError("DLNA %s: HTTP %d %s" % (action, e.code, e.read()[:160].decode("utf8", "replace")))

    def play(self, url, ctype):
        didl = ('<DIDL-Lite xmlns="urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/" xmlns:dc="http://purl.org/dc/elements/1.1/" '
                'xmlns:upnp="urn:schemas-upnp-org:metadata-1-0/upnp/"><item id="0" parentID="-1" restricted="1">'
                '<dc:title>S9 Screen Cast</dc:title><upnp:class>object.item.videoItem</upnp:class>'
                '<res protocolInfo="http-get:*:%s:*">%s</res></item></DIDL-Lite>') % (ctype, escape(url))
        try:
            self.soap("Stop")
        except Exception:
            pass
        self.soap("SetAVTransportURI", "<CurrentURI>%s</CurrentURI><CurrentURIMetaData>%s</CurrentURIMetaData>" % (escape(url), escape(didl)))
        self.soap("Play", "<Speed>1</Speed>")

    def state(self):
        x = self.soap("GetTransportInfo")
        m = re.search(r"<CurrentTransportState>(.*?)</CurrentTransportState>", x)
        return m.group(1) if m else "?"

    def alive(self):
        try:
            s = self.state()
        except Exception as e:
            return False, "a TV nao responde: %s" % e
        if s in ("PLAYING", "TRANSITIONING"):
            self.was_playing = True
        if s in ("STOPPED", "NO_MEDIA_PRESENT") and self.was_playing:
            return False, "reproducao encerrada na TV"
        return True, ""

    def stop(self):
        try:
            self.soap("Stop", timeout=4)
        except Exception:
            pass


# ------------------------------------------------------------------ captura, codificacao e servidor HTTP
def read_exact(f, n):
    b = b""
    while len(b) < n:
        c = f.read(n - len(b))
        if not c:
            raise EOFError
        b += c
    return b


WEB_PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="robots" content="noindex">
<title>S9 Screen</title>
<style>
html,body{margin:0;height:100%;background:#000;overflow:hidden;-webkit-user-select:none;user-select:none}
video{position:fixed;inset:0;width:100%;height:100%;object-fit:contain;background:#000}
#msg{position:fixed;top:14px;left:12px;right:12px;text-align:center;font:16px system-ui,sans-serif;color:#9cf;text-shadow:0 1px 3px #000}
#bar{position:fixed;left:0;right:0;bottom:0;display:flex;gap:12px;justify-content:center;padding:14px 12px 18px;background:linear-gradient(transparent,rgba(0,0,0,.65));transition:opacity .4s}
#bar.hide{opacity:0;pointer-events:none}
button{font:16px system-ui,sans-serif;padding:10px 20px;border-radius:10px;border:1px solid #777;background:#222;color:#eee}
</style></head><body>
<video id="v" autoplay muted playsinline></video>
<div id="msg">Connecting...</div>
<div id="bar"><button id="snd">Sound on</button><button id="fs">Fullscreen</button></div>
<script>
(function(){
var base=location.pathname.replace(/\/?$/,'/');
var v=document.getElementById('v'),msg=document.getElementById('msg'),bar=document.getElementById('bar');
var snd=document.getElementById('snd'),fs=document.getElementById('fs');
function say(t){msg.textContent=t;msg.style.display=t?'block':'none';}
function retry(t){say(t+' Retrying...');setTimeout(function(){location.reload();},3000);}
var barT;function showBar(){bar.classList.remove('hide');clearTimeout(barT);barT=setTimeout(function(){bar.classList.add('hide');},3500);}
document.addEventListener('pointerdown',showBar);showBar();
snd.onclick=function(){v.muted=!v.muted;snd.textContent=v.muted?'Sound on':'Sound off';var p=v.play();if(p&&p.catch)p.catch(function(){});};
fs.onclick=function(){var e=document.documentElement,f=e.requestFullscreen||e.webkitRequestFullscreen;if(f)f.call(e);};
fetch(base+'info',{cache:'no-store'}).then(function(r){if(!r.ok)throw 0;return r.json();}).then(start).catch(function(){retry('The screen cast is not available.');});
function start(info){
  if(!info.audio)snd.style.display='none';
  var mime='video/mp4; codecs="'+info.codecs+'"';
  var MS=window.MediaSource||window.WebKitMediaSource;
  if(!MS||!MS.isTypeSupported(mime)){say('This browser cannot play the stream (needs MediaSource with H.264).');return;}
  var ms=new MS();v.src=URL.createObjectURL(ms);
  ms.addEventListener('sourceopen',function(){
    var sb=ms.addSourceBuffer(mime),q=[],started=false,dead=false;
    function pump(){
      if(dead||sb.updating||!q.length||ms.readyState!=='open')return;
      try{sb.appendBuffer(q[0]);q.shift();}
      catch(e){if(e.name==='QuotaExceededError'){trim(true);}else{dead=true;retry('Playback error.');}}
    }
    function trim(force){
      if(sb.updating||!sb.buffered.length)return false;
      var s=sb.buffered.start(0),keep=force?2:6;
      if(v.currentTime-s>keep+2){try{sb.remove(s,v.currentTime-keep);return true;}catch(e){}}
      return false;
    }
    function sync(){
      if(!sb.buffered.length)return;
      var e=sb.buffered.end(sb.buffered.length-1);
      if(!started){started=true;v.currentTime=Math.max(sb.buffered.start(0),e-0.3);say('');}
      else if(e-v.currentTime>1.5){v.currentTime=e-0.3;}
      if(v.paused){var p=v.play();if(p&&p.catch)p.catch(function(){});}
    }
    sb.addEventListener('updateend',function(){sync();if(!trim(false))pump();});
    var last=-1,still=0;
    setInterval(function(){
      if(!started||document.hidden)return;
      if(v.currentTime===last){if(++still>=3)location.reload();}else{still=0;last=v.currentTime;}
    },4000);
    fetch(base+'s.mp4',{cache:'no-store'}).then(function(r){
      if(!r.ok||!r.body){retry('The stream is not available.');return;}
      var rd=r.body.getReader();
      (function loop(){
        rd.read().then(function(x){
          if(x.done){retry('The stream ended.');return;}
          q.push(x.value);pump();loop();
        }).catch(function(){retry('Connection lost.');});
      })();
    }).catch(function(){retry('Connection lost.');});
  });
}
})();
</script></body></html>
"""


def web_token():
    f = STATE + "/webtoken"
    t = readf(f)
    if not re.fullmatch(r"[0-9a-f]{8}", t):
        t = os.urandom(4).hex()
        os.makedirs(STATE, exist_ok=True)
        atomic_write(f, t + "\n", 0o600)
    return t


def codecs_from_init(init):
    """string de codecs para o MediaSource do navegador, lida do segmento de inicializacao (avcC / mp4a)."""
    v = "avc1.640029"
    i = init.find(b"avcC")
    if i >= 0 and len(init) >= i + 8:
        v = "avc1.%02x%02x%02x" % (init[i + 5], init[i + 6], init[i + 7])
    aud = init.find(b"mp4a") >= 0
    return (v + ",mp4a.40.2") if aud else v, aud


class Hub:
    def __init__(self, fmt):
        self.fmt = fmt
        self.lock = threading.Lock()
        self.clients = set()
        self.init = b""
        self.last = None
        self.ready = threading.Event()
        self.alive = True
        self.seen_client = False

    def join(self):
        q = queue.Queue(150)
        with self.lock:
            self.clients.add(q)
            self.seen_client = True
            return q, self.init, self.last

    def leave(self, q):
        with self.lock:
            self.clients.discard(q)

    def count(self):
        with self.lock:
            return len(self.clients)

    def publish(self, chunk, keep=False):
        with self.lock:
            if keep:
                self.last = chunk
            for q in self.clients:
                try:
                    q.put_nowait(chunk)
                except queue.Full:
                    try:
                        while True:
                            q.get_nowait()
                    except queue.Empty:
                        pass
                    q.put_nowait(chunk)


def reader(proc, hub):
    f = proc.stdout
    try:
        if hub.fmt == "mp4":
            init = b""
            frag = b""
            started = False
            while True:
                h = read_exact(f, 8)
                size, typ = struct.unpack(">I4s", h)
                hdr = h
                if size == 1:
                    ext = read_exact(f, 8)
                    size = struct.unpack(">Q", ext)[0]
                    hdr = h + ext
                box = hdr + read_exact(f, size - len(hdr))
                if typ == b"moof":
                    if not started:
                        started = True
                        hub.init = init
                        hub.ready.set()
                    frag = box
                elif typ == b"mdat" and started:
                    hub.publish(frag + box, keep=True)
                    frag = b""
                elif started:
                    frag += box
                else:
                    init += box
        else:
            buf = b""
            while True:
                c = os.read(f.fileno(), 65536)
                if not c:
                    raise EOFError
                buf += c
                n = len(buf) - len(buf) % 188
                if n:
                    hub.ready.set()
                    hub.publish(buf[:n])
                    buf = buf[n:]
    except Exception as e:
        log("leitura do codificador terminou:", e)
    hub.alive = False
    hub.ready.set()


def make_handler(hub, path, ctype, token=None):
    class H(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.0"

        def log_message(self, *a):
            pass

        def _route(self):
            p = self.path.split("?")[0]
            if token:
                pre = "/v/" + token
                if p in (pre, pre + "/"):
                    return "page"
                if p == pre + "/info":
                    return "info"
                if p == pre + "/s.mp4":
                    return "stream"
                return None
            return "stream" if p == path else None

        def _head(self, ct=None):
            self.send_response(200)
            self.send_header("Content-Type", ct or ctype)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Cache-Control", "no-cache, no-store")
            self.send_header("transferMode.dlna.org", "Streaming")
            self.send_header("contentFeatures.dlna.org", "DLNA.ORG_OP=00;DLNA.ORG_CI=0;DLNA.ORG_FLAGS=01700000000000000000000000000000")
            self.send_header("Connection", "close")
            self.end_headers()

        def _small(self, body, ct):
            data = body.encode()
            self.send_response(200)
            self.send_header("Content-Type", ct)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-cache, no-store")
            self.send_header("Connection", "close")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(data)

        def do_OPTIONS(self):
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Headers", "*")
            self.end_headers()

        def do_HEAD(self):
            r = self._route()
            if r is None:
                self.send_error(404)
            elif r == "stream":
                self._head()
            elif r == "page":
                self._small(WEB_PAGE, "text/html; charset=utf-8")
            else:
                self._small("{}", "application/json")

        def do_GET(self):
            r = self._route()
            if r is None:
                self.send_error(404)
                return
            if r == "page":
                self._small(WEB_PAGE, "text/html; charset=utf-8")
                return
            if not hub.ready.wait(20) or not hub.alive:
                self.send_error(503)
                return
            if r == "info":
                codecs, aud = codecs_from_init(hub.init)
                self._small(json.dumps({"codecs": codecs, "audio": aud}), "application/json")
                return
            q, init, last = hub.join()
            log("cliente conectou no stream:", self.client_address[0])
            try:
                self._head()
                if init:
                    self.wfile.write(init)
                if last:
                    self.wfile.write(last)
                while hub.alive:
                    try:
                        item = q.get(timeout=2)
                    except queue.Empty:
                        continue
                    self.wfile.write(item)
            except OSError:
                pass
            finally:
                hub.leave(q)
                log("cliente saiu do stream:", self.client_address[0])
    return H


def probe():
    r = subprocess.run(["mirscreencast", "-m", SOCK, "--query"], capture_output=True, text=True, timeout=15)
    o = r.stdout
    m1 = re.search(r"Colorspace:\s*(\w+)", o)
    m2 = re.search(r"Output size:\s*(\d+)x(\d+)", o)
    m3 = re.search(r"Capture rate \(Hz\):\s*(\d+)", o)
    if not (m1 and m2 and m3) or m1.group(1).lower() not in ("rgba", "bgra"):
        raise RuntimeError("nao consegui consultar a tela (mirscreencast --query)")
    return int(m2.group(1)), int(m2.group(2)), int(m3.group(1)), m1.group(1).lower()


def quality():
    return "light" if readf(STATE + "/quality") == "light" else "normal"


def audio_offset():
    """atraso do som em segundos (positivo = som depois); arquivo $STATE/av_offset em milissegundos"""
    try:
        v = int(readf(STATE + "/av_offset", "0"))
    except ValueError:
        v = 0
    return max(-1000, min(3000, v)) / 1000.0


def audio_ok():
    if readf(STATE + "/audio") == "off":
        return False
    try:
        return subprocess.run([AUDIO, "check"], capture_output=True, timeout=15).returncode == 0
    except Exception:
        return False


def pipeline_cmd(fmt, gop=30):
    W, H, HZ, PF = probe()
    inter = max(1, (HZ + 15) // 30)
    mw, mh, br = (1280, 720, "3M") if quality() == "light" else (1920, 1080, "6M")
    bufs = "%dM" % (int(br[:-1]) * 2)
    if fmt == "mp4":
        mux = "-movflags +frag_keyframe+empty_moov+default_base_moof -f mp4"
    else:
        mux = "-f mpegts -mpegts_flags +resend_headers -muxdelay 0 -muxpreload 0 -flush_packets 1"
    aud = audio_ok()
    aoff = audio_offset()
    ain = ("-thread_queue_size 1024 -f s16le -ar 48000 -ac 2 -use_wallclock_as_timestamps 1 %s-i <(exec '%s') " % (("-itsoffset %.3f " % aoff) if aoff < 0 else "", AUDIO)) if aud else ""
    # som atrasado: adelay (silencio de verdade no inicio); o muxer MP4 fragmentado descarta um -itsoffset positivo
    adl = (",adelay=%d|%d" % (round(aoff * 1000), round(aoff * 1000))) if aoff > 0 else ""
    amap = "-map 0:v:0 -map 1:a:0 -c:a aac -b:a 128k -ar 48000 -ac 2 -af 'aresample=async=1000%s' " % adl if aud else ""
    cmd = ("exec mirscreencast -m '%s' --cap-interval %d --stdout 2>/dev/null | "
           "ffmpeg -nostdin -hide_banner -loglevel warning -thread_queue_size 512 -use_wallclock_as_timestamps 1 -f rawvideo -pix_fmt %s -video_size %dx%d -i - " + ain +
           "-vf \"fps=30,scale=w='min(iw,%d)':h='min(ih,%d)':force_original_aspect_ratio=decrease:force_divisible_by=2,format=yuv420p\" "
           "-c:v libx264 -preset ultrafast -tune zerolatency -profile:v high -level 4.1 -g %d -keyint_min %d -sc_threshold 0 -bf 0 "
           "-b:v %s -maxrate %s -bufsize %s " + amap + "%s pipe:1") % (SOCK, inter, PF, W, H, mw, mh, gop, gop, br, br, bufs, mux)
    log("tela %dx%d @ %d Hz (%s), qualidade %s, formato %s, audio %s%s" % (W, H, HZ, PF, quality(), fmt, "sim" if aud else "nao", (" (atraso do som %+d ms)" % round(aoff * 1000)) if aud and aoff else ""))
    return cmd


def status(**kv):
    atomic_write(STATUSF, "".join("%s=%s\n" % (k, v) for k, v in kv.items()))


def fail(msg):
    log("ERRO:", msg)
    atomic_write(ERRF, msg[:160] + "\n")
    try:
        os.unlink(STATUSF)
    except OSError:
        pass


def do_run():
    tid = readf(RUN + "/tv.target").split()
    web = bool(tid) and tid[0] == "web"
    if web:
        tid = "web"
        t = None
        proto = "web"
        name = "Web browser"
        fmt = "mp4"
    else:
        if not tid or not re.fullmatch(r"[0-9a-f]{8}", tid[0]):
            fail("alvo invalido")
            return 1
        tid = tid[0]
        try:
            targets = json.loads(readf(TARGETS, "[]"))
        except Exception:
            targets = []
        t = next((x for x in targets if x.get("id") == tid), None)
        if not t:
            fail("aparelho nao encontrado; abra o menu para atualizar a lista")
            return 1
        pref = readf(STATE + "/proto")
        proto = pref if pref in ("gcast", "dlna") and ((pref == "gcast" and "cast" in t) or (pref == "dlna" and "dlna" in t)) else \
            ("gcast" if "cast" in t else "dlna")
        name = t["name"]
        fmt = "mp4" if proto == "gcast" else ("mp4" if readf(STATE + "/dlnafmt") == "mp4" else "ts")
    ext, ctype = ("mp4", "video/mp4") if fmt == "mp4" else ("ts", "video/mpeg")
    stopping = {"v": False}
    signal.signal(signal.SIGTERM, lambda *a: stopping.__setitem__("v", True))
    signal.signal(signal.SIGINT, lambda *a: stopping.__setitem__("v", True))
    try:
        os.unlink(ERRF)
    except OSError:
        pass
    base = dict(target=name, target_id=tid, proto=proto)
    status(state="waiting" if web else "connecting", **base)
    hub = Hub(fmt)
    proc = None
    ctl = None
    srv = None
    keeper = None
    muted = False
    try:
        if audio_ok() and readf(STATE + "/phone_audio") != "on":
            r = subprocess.run([AUDIO, "setup"], capture_output=True, text=True, timeout=40)
            if r.returncode == 0:
                muted = True
                keeper = subprocess.Popen([AUDIO, "keep"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, preexec_fn=os.setsid)
                log("audio do celular desviado para o sink 'Screen Cast' (o celular fica mudo durante a transmissao)")
            else:
                log("nao consegui desviar o audio do celular:", (r.stderr or r.stdout).strip()[:120])
        cmd = pipeline_cmd(fmt, 15 if web else 30)
        proc = subprocess.Popen(["bash", "-c", cmd], stdout=subprocess.PIPE, stderr=open(RUN + "/tv-ffmpeg.log", "wb"), preexec_fn=os.setsid)
        threading.Thread(target=reader, args=(proc, hub), daemon=True).start()
        path = "/s9." + ext
        srv = ThreadingHTTPServer(("0.0.0.0", HTTP_PORT), make_handler(hub, path, ctype, web_token() if web else None))
        srv.daemon_threads = True
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        if not hub.ready.wait(25) or not hub.alive:
            raise RuntimeError("o codificador nao produziu video (veja %s/tv-ffmpeg.log)" % RUN)
        t_play = time.time()
        if web:
            log("visualizador web: http://%s:%d/v/%s/" % (myip(), HTTP_PORT, web_token()))
            t_idle = time.time()
            while not stopping["v"]:
                time.sleep(1)
                if stopping["v"]:
                    break
                if proc.poll() is not None or not hub.alive:
                    raise RuntimeError("o codificador parou")
                n = hub.count()
                if n:
                    t_idle = time.time()
                elif time.time() - t_idle > WEB_IDLE:
                    raise RuntimeError("ninguem assistiu por %s; transmissao encerrada" % (("%d minutos" % (WEB_IDLE // 60)) if WEB_IDLE >= 120 else ("%d segundos" % WEB_IDLE)))
                status(state="streaming" if n else "waiting", clients=n, **base)
        else:
            url = "http://%s:%d%s" % (myip(), HTTP_PORT, path)
            log("alvo %s (%s) %s -> %s" % (name, t["ip"], proto, url))
            ctl = CastCtl(t["ip"], t["cast"]["port"]) if proto == "gcast" else DlnaCtl(t["dlna"]["control"], t["dlna"]["stype"])
            ctl.play(url, ctype)
            while not stopping["v"]:
                time.sleep(1)
                if stopping["v"]:
                    break
                if proc.poll() is not None or not hub.alive:
                    raise RuntimeError("o codificador parou")
                ok, why = ctl.alive()
                if not ok:
                    raise RuntimeError(why)
                n = hub.count()
                if n == 0 and time.time() - t_play > 30 and not hub.seen_client:
                    raise RuntimeError("a TV aceitou o comando mas nao abriu o video (tente trocar o protocolo no menu)")
                status(state="streaming" if n else "connecting", clients=n, **base)
        rc = 0
    except Exception as e:
        fail(str(e))
        rc = 1
    finally:
        if ctl:
            ctl.stop()
        hub.alive = False
        if srv:
            srv.shutdown()
        if proc and proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except Exception:
                pass
        if keeper and keeper.poll() is None:
            try:
                os.killpg(keeper.pid, signal.SIGTERM)
            except Exception:
                pass
        if muted:
            try:
                subprocess.run([AUDIO, "restore"], capture_output=True, timeout=40)
                log("audio do celular restaurado")
            except Exception as e:
                log("falha ao restaurar o audio:", e)
        try:
            os.unlink(STATUSF)
        except OSError:
            pass
    return rc


def main():
    os.makedirs(RUN, exist_ok=True)
    c = sys.argv[1] if len(sys.argv) > 1 else ""
    if c == "scan":
        do_scan()
        return 0
    if c == "run":
        return do_run()
    print("uso: s9-cast-tv scan|run")
    return 1


if __name__ == "__main__":
    sys.exit(main())
