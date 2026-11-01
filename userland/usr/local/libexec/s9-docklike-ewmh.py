#!/usr/bin/python3
# S9_DOCKLIKE_EWMH_BRIDGE

import os
import signal
import time
from Xlib import X, Xatom, display
from Xlib.protocol import event


running = True

def stop(signum, frame):
    global running
    running = False

signal.signal(signal.SIGTERM, stop)
signal.signal(signal.SIGINT, stop)

# Esperar Xwayland quando o MirAL estiver iniciando.
d = None

for attempt in range(60):
    try:
        d = display.Display()
        break
    except Exception as e:
        print(f"XWAYLAND_WAIT={attempt + 1} {e}", flush=True)
        time.sleep(2)

if d is None:
    raise RuntimeError("XWAYLAND_CONNECTION_TIMEOUT")

root = d.screen().root

a_list = d.intern_atom("_NET_CLIENT_LIST")
a_stack = d.intern_atom("_NET_CLIENT_LIST_STACKING")
a_type = d.intern_atom("_NET_WM_WINDOW_TYPE")
a_wm_state = d.intern_atom("WM_STATE")
a_owner = d.intern_atom("_S9_DOCKLIKE_EWMH_OWNER_PID")

a_restore_active = d.intern_atom("_NET_ACTIVE_WINDOW")
a_restore_wm_state = d.intern_atom("WM_STATE")
a_restore_net_state = d.intern_atom("_NET_WM_STATE")
a_restore_hidden = d.intern_atom("_NET_WM_STATE_HIDDEN")
a_restore_change = d.intern_atom("WM_CHANGE_STATE")


pid = os.getpid()

def get_property(atom):
    p = root.get_full_property(atom, X.AnyPropertyType)
    return None if p is None else list(p.value)

def owner():
    p = get_property(a_owner)
    return int(p[0]) if p else None

existing = owner()

if existing is not None:
    try:
        with open(f"/proc/{existing}/cmdline", "rb") as f:
            cmd = f.read()
    except OSError:
        cmd = b""

    if b"s9-docklike-ewmh.py" in cmd:
        raise RuntimeError("ANOTHER_BRIDGE_IS_RUNNING")

elif (
    get_property(a_list) is not None or
    get_property(a_stack) is not None
):
    raise RuntimeError("ANOTHER_EWMH_PROVIDER_EXISTS")

root.change_property(
    a_owner, Xatom.CARDINAL, 32,
    [pid], X.PropModeReplace
)
d.sync()

excluded_classes = {
    "xfce4-panel",
    "xfdesktop",
    "xfce4-notifyd",
}

excluded_types = {
    "_NET_WM_WINDOW_TYPE_DESKTOP",
    "_NET_WM_WINDOW_TYPE_DOCK",
    "_NET_WM_WINDOW_TYPE_MENU",
    "_NET_WM_WINDOW_TYPE_DROPDOWN_MENU",
    "_NET_WM_WINDOW_TYPE_POPUP_MENU",
    "_NET_WM_WINDOW_TYPE_TOOLTIP",
    "_NET_WM_WINDOW_TYPE_NOTIFICATION",
}

tracked = []
last_list = None
last_stack = None

def get_windows():
    result = []

    for w in root.query_tree().children:
        try:
            attr = w.get_attributes()

            # S9_DOCKLIKE_ICONIC_KEEP_V1
            #
            # EWMH client lists must retain minimized windows.
            # A minimized Xwayland client may be unmapped but
            # still exists and has WM_STATE=IconicState (3).
            #
            # Also retain previously tracked clients during
            # transitions between normal/iconic states.
            if attr.map_state != X.IsViewable:
                state = w.get_full_property(
                    a_wm_state, X.AnyPropertyType
                )

                iconic = (
                    state is not None
                    and len(state.value) > 0
                    and int(state.value[0]) == 3
                )

                previously_managed = w.id in tracked

                if not iconic and not previously_managed:
                    continue
            if attr.override_redirect:
                continue

            geo = w.get_geometry()

            if geo.width < 64 or geo.height < 64:
                continue

            cls = w.get_wm_class() or ()

            if not cls:
                continue

            names = {str(x).lower() for x in cls}

            if names & excluded_classes:
                continue

            p = w.get_full_property(
                a_type, X.AnyPropertyType
            )

            if p is not None:
                types = {
                    d.get_atom_name(int(a))
                    for a in p.value
                }

                if types & excluded_types:
                    continue

            result.append((w.id, "/".join(cls)))

        except Exception:
            continue

    return result

def publish(atom, values):
    root.change_property(
        atom, Xatom.WINDOW, 32,
        values, X.PropModeReplace
    )


# S9_DOCKLIKE_RESTORE_CLICK_V1
#
# Observe EWMH activation requests without taking ownership
# of the X11 window manager.
#
# Mir1 supports WM_CHANGE_STATE NormalState in this setup.
# Only restore clients currently marked IconicState.

pending_focus = {}

root.change_attributes(
    event_mask=(
        X.SubstructureNotifyMask |
        X.PropertyChangeMask
    )
)

d.sync()


def s9_wm_state(window):
    p = window.get_full_property(
        a_restore_wm_state,
        X.AnyPropertyType
    )

    if p is None or len(p.value) == 0:
        return -1

    return int(p.value[0])


def s9_is_hidden(window):
    p = window.get_full_property(
        a_restore_net_state,
        X.AnyPropertyType
    )

    return (
        p is not None and
        int(a_restore_hidden) in [int(x) for x in p.value]
    )


def s9_send_activation(window):
    msg = event.ClientMessage(
        window=window,
        client_type=a_restore_active,
        data=(32, [2, X.CurrentTime, 0, 0, 0])
    )

    root.send_event(
        msg,
        event_mask=(
            X.SubstructureRedirectMask |
            X.SubstructureNotifyMask
        ),
        propagate=False
    )

    d.flush()


s9_toggle_guard = {}


# S9_DOCKLIKE_TOGGLE_CLOSE_V2
#
# - source=1: eventos de aplicativos/painel.
# - source=2: eventos sinteticos da nossa propria ponte.
# - IconicState=3: solicitar restauracao.
# - NormalState=1: minimizar somente em clique do Docklike.
# - _NET_CLOSE_WINDOW: encaminhar WM_DELETE_WINDOW.
#
# Nao utiliza xfwm4, nao altera o MirAL e nao modifica WM_STATE.

a_s9_close = d.intern_atom("_NET_CLOSE_WINDOW")
a_s9_protocols = d.intern_atom("WM_PROTOCOLS")
a_s9_delete = d.intern_atom("WM_DELETE_WINDOW")

s9_v2_last_app = 0
s9_v2_last_dock = 0
s9_v2_last_action = ""
s9_v2_click_guard = {}
s9_v2_close_guard = {}


def s9_v2_active_id():
    p = root.get_full_property(
        a_restore_active, X.AnyPropertyType
    )
    return int(p.value[0]) if p is not None and len(p.value) else 0


def s9_v2_observe_focus():
    global s9_v2_last_app
    global s9_v2_last_dock
    global s9_v2_last_action

    wid = s9_v2_active_id()

    if wid not in tracked:
        return

    try:
        w = d.create_resource_object("window", wid)

        if s9_wm_state(w) != 1 or s9_is_hidden(w):
            return

        if s9_v2_last_app != wid:
            if s9_v2_last_dock and s9_v2_last_dock != wid:
                s9_v2_last_dock = 0
                s9_v2_last_action = ""

            s9_v2_last_app = wid

    except Exception:
        pass


def s9_v2_pointer_on_panel():
    # S9_DOCKLIKE_PANEL_GEOM_V1
    # d.screen() e o retrato do momento em que o helper conectou ao X: com dock ligada
    # depois do boot ou hotplug ele fica velho. Usar a geometria ATUAL da raiz e o
    # painel real (janela xfce4-panel mapeada e fina) para decidir se o clique foi nele.
    pointer = root.query_pointer()
    px = int(pointer.root_x)
    py = int(pointer.root_y)

    try:
        geo = root.get_geometry()
        sw, sh = int(geo.width), int(geo.height)
    except Exception:
        sw = int(d.screen().width_in_pixels)
        sh = int(d.screen().height_in_pixels)
    stale_w = int(d.screen().width_in_pixels)
    stale_h = int(d.screen().height_in_pixels)

    n = getattr(s9_v2_pointer_on_panel, "_n", 0)
    if (stale_w, stale_h) != (sw, sh) and n < 3:
        s9_v2_pointer_on_panel._n = n + 1
        print(
            f"S9_DOCKLIKE_PANEL_GEOM stale={stale_w}x{stale_h} "
            f"live={sw}x{sh} (retrato velho da conexao x geometria atual)",
            flush=True
        )

    panels = []

    for w in root.query_tree().children:
        try:
            cls = w.get_wm_class() or ()
            names = {str(c).lower() for c in cls}

            if "xfce4-panel" not in names:
                continue

            if w.get_attributes().map_state != X.IsViewable:
                continue

            g = w.get_geometry()
            x, y, width, height = int(g.x), int(g.y), int(g.width), int(g.height)

            # a barra do painel e fina (<= 64 px) e longa; popups/menus nao contam
            if min(width, height) > 64 or max(width, height) < 100:
                continue

            panels.append((x, y, width, height))
        except Exception:
            continue

    if panels:
        inside = any(
            x <= px < x + width and
            y <= py < y + height
            for x, y, width, height in panels
        )
        if not inside:
            m = getattr(s9_v2_pointer_on_panel, "_m", 0)
            if m < 10:
                s9_v2_pointer_on_panel._m = m + 1
                print(
                    f"S9_DOCKLIKE_PANEL_GEOM fora-do-painel pointer=({px},{py}) "
                    f"paineis={panels} tela={sw}x{sh}",
                    flush=True
                )
        return inside, px, py

    # Painel nao identificavel: heuristica de borda com a resolucao ATUAL.
    if not (py < 36 or py >= sh - 36):
        return False, px, py

    return True, px, py


def s9_v2_change_state(window, state):
    msg = event.ClientMessage(
        window=window,
        client_type=a_restore_change,
        data=(32, [state, 0, 0, 0, 0])
    )

    root.send_event(
        msg,
        event_mask=(
            X.SubstructureRedirectMask |
            X.SubstructureNotifyMask
        ),
        propagate=False
    )

    d.flush()


def s9_v2_close_window(window, timestamp):
    now = time.monotonic()
    wid = window.id

    if now - s9_v2_close_guard.get(wid, 0) < 1.5:
        print(
            f"S9_CLOSE_DUPLICATE_IGNORED window=0x{wid:x}",
            flush=True
        )
        return

    protocols = window.get_wm_protocols() or []

    if int(a_s9_delete) not in [int(v) for v in protocols]:
        print(
            f"S9_CLOSE_UNSUPPORTED window=0x{wid:x}",
            flush=True
        )
        return

    msg = event.ClientMessage(
        window=window,
        client_type=a_s9_protocols,
        data=(32, [
            int(a_s9_delete),
            timestamp,
            0, 0, 0
        ])
    )

    # Enviar ao aplicativo, nao ao root/XWM.
    # O aplicativo continua responsavel pela confirmacao.
    window.send_event(
        msg,
        event_mask=0,
        propagate=False
    )

    d.flush()
    s9_v2_close_guard[wid] = now

    print(
        f"S9_DOCKLIKE_CLOSE_FORWARDED "
        f"window=0x{wid:x} "
        f"protocol=WM_DELETE_WINDOW",
        flush=True
    )


# S9_DOCKLIKE_X11_CLICK_V2
#
# Desde a lib Mir v45 (S9_XWAYLAND_ACTIVATE_V1) o proprio Mir atende _NET_ACTIVE_WINDOW: restaura, levanta e da foco.
# Quando a mensagem chega aqui o estado vivo ja e POSTERIOR ao clique. A decisao usa um instantaneo tirado quando
# o painel/popup rouba o foco (antes do clique):
#   - estava minimizada      -> o Mir ja restaurou com foco; nada a fazer
#   - era a ultima com foco  -> minimizar (toggle)
#   - outro caso             -> so ativar (o Mir ja fez)

s9_v3_snap = None
s9_v3_last_active = -1
s9_v3_null_since = 0.0


def s9_v3_take_snapshot(active_id):
    global s9_v3_snap

    mins = set()

    for wid in list(tracked):
        try:
            w = d.create_resource_object("window", wid)

            if s9_wm_state(w) == 3 or s9_is_hidden(w):
                mins.add(wid)
        except Exception:
            pass

    last_app = s9_v2_last_app

    if last_app in mins:
        last_app = 0

    s9_v3_snap = {
        "t": time.monotonic(),
        "active": active_id,
        "last_app": last_app,
        "min": mins,
    }


def s9_v3_note_active():
    global s9_v3_last_active
    global s9_v3_null_since
    global s9_v2_last_app

    now = time.monotonic()
    a = s9_v2_active_id()

    if a == s9_v3_last_active:
        return

    prev = s9_v3_last_active
    s9_v3_last_active = a

    if a == 0:
        s9_v3_null_since = now
        return

    # O foco ficou fora do X11 por um tempo (ex.: Chrome Wayland) e voltou:
    # nenhuma janela X11 era a "da frente".
    if prev == 0 and s9_v3_null_since and now - s9_v3_null_since > 0.25:
        s9_v2_last_app = 0

    s9_v3_null_since = 0.0

    # Foco em janela fora da lista (painel/popup): estado ainda e o de ANTES do clique.
    if a not in tracked:
        s9_v3_take_snapshot(a)


def s9_v3_reject(wid, reason, source, timestamp, extra=""):
    if source != 1:
        return

    print(
        f"S9_DOCKLIKE_REJECT window=0x{wid:x} "
        f"reason={reason} source={source} "
        f"timestamp={timestamp} {extra}".rstrip(),
        flush=True
    )


def s9_process_activation_requests():
    global s9_v2_last_dock
    global s9_v2_last_action
    global s9_v2_last_app
    global s9_v3_snap

    s9_v2_observe_focus()

    while d.pending_events():

        ev = d.next_event()

        # Chrome Wayland virtual client; skip native X11 handler.
        if s9_chrome_handle_event(ev):
            continue

        if ev.type == X.PropertyNotify:
            if (
                ev.window.id == root.id and
                ev.atom == a_restore_active
            ):
                s9_v3_note_active()
                s9_v2_observe_focus()
            continue

        if ev.type != X.ClientMessage:
            continue

        wid = ev.window.id

        # Nunca atuar em janelas fora da lista gerenciada.
        if wid not in tracked:
            continue

        try:
            window = d.create_resource_object(
                "window", wid
            )

            # ===== FECHAR PELO X DO HOVER =====

            if ev.client_type == a_s9_close:
                timestamp = int(ev.data[1][0])
                s9_v2_close_window(window, timestamp)
                continue

            if ev.client_type != a_restore_active:
                continue

            source = int(ev.data[1][0])
            timestamp = int(ev.data[1][1])
            state = s9_wm_state(window)

            now = time.monotonic()

            # ===== JANELA MINIMIZADA (Mir antigo ainda nao restaurou) =====

            if state == 3:

                # Evitar que eventos repetidos de um unico
                # clique revertam imediatamente a minimizacao.
                if now - s9_v2_click_guard.get(wid, 0) < 0.45:
                    continue

                if wid in pending_focus:
                    continue

                s9_v2_change_state(window, 1)

                pending_focus[wid] = now + 2.0

                s9_v2_last_dock = wid
                s9_v2_last_action = "restore"
                s9_v2_click_guard[wid] = now

                print(
                    f"S9_DOCKLIKE_RESTORE_REQUEST "
                    f"window=0x{wid:x} iconic=1",
                    flush=True
                )
                continue

            if state != 1 or s9_is_hidden(window):
                s9_v3_reject(wid, "state", source, timestamp, f"wm_state={state}")
                continue

            # ===== JANELA NORMAL: EXAMINAR CLIQUE =====

            # Os eventos source=2 com timestamp=0 sao enviados
            # pela nossa propria ponte e nao representam
            # um clique do usuario.
            if source != 1 or timestamp == 0:
                s9_v3_reject(wid, "timestamp", source, timestamp)
                continue

            on_panel, px, py = s9_v2_pointer_on_panel()

            if not on_panel:
                s9_v3_reject(wid, "not-on-panel", source, timestamp, f"pointer=({px},{py})")
                continue

            if now - s9_v2_click_guard.get(wid, 0) < 0.45:
                s9_v3_reject(wid, "guard", source, timestamp)
                continue

            snap = s9_v3_snap
            valid = (
                snap is not None and
                snap["active"] == s9_v3_last_active and
                now - snap["t"] < 300.0
            )

            if valid:
                was_min = wid in snap["min"]
                prev_app = snap["last_app"]
            else:
                was_min = False
                prev_app = 0

            if was_min:
                decision = "restored_by_mir"
            elif valid and prev_app == wid:
                decision = "minimize"
            elif valid:
                decision = "activate"
            else:
                decision = "activate_nosnap"

            s9_v2_last_dock = wid
            s9_v2_click_guard[wid] = now

            if decision == "minimize":
                s9_v2_change_state(window, 3)
                s9_v2_last_action = "minimize"
                s9_v2_last_app = 0
            elif decision == "restored_by_mir":
                s9_v2_last_action = "restore"
            else:
                s9_v2_last_action = "activate"

            # O instantaneo foi consumido por este clique.
            s9_v3_snap = None

            print(
                f"S9_DOCKLIKE_CLICK window=0x{wid:x} "
                f"decision={decision} "
                f"prev_app=0x{prev_app:x} "
                f"was_min={int(was_min)} snap={int(valid)} "
                f"pointer=({px},{py})",
                flush=True
            )

        except Exception as exc:
            print(
                f"S9_DOCKLIKE_V2_ERROR "
                f"window=0x{wid:x} error={exc}",
                flush=True
            )



# S9_CHROME_DOCKLIKE_PROXY_V1
#
# Representacao X11 da janela Chrome Wayland.
# Nao renderiza Chrome, nao modifica o cliente e nao
# interfere nas janelas Xwayland reais.
#
# O controle real utiliza o socket nativo do MirAL V28.

import socket

s9_chrome_path = "/run/s9-miral/s9-chrome-control.sock"

s9_chrome_proxy = None
s9_chrome_last_status = {}
s9_chrome_last_poll = 0.0
s9_chrome_last_focus = 0.0
s9_chrome_last_click = 0.0
s9_chrome_failures = 0

s9_chrome_atom_state = d.intern_atom("WM_STATE")
s9_chrome_atom_netstate = d.intern_atom("_NET_WM_STATE")
s9_chrome_atom_hidden = d.intern_atom("_NET_WM_STATE_HIDDEN")
s9_chrome_atom_type = d.intern_atom("_NET_WM_WINDOW_TYPE")
s9_chrome_atom_normal = d.intern_atom("_NET_WM_WINDOW_TYPE_NORMAL")
s9_chrome_atom_name = d.intern_atom("_NET_WM_NAME")
s9_chrome_atom_utf8 = d.intern_atom("UTF8_STRING")
s9_chrome_atom_close = d.intern_atom("_NET_CLOSE_WINDOW")
s9_chrome_atom_active = d.intern_atom("_NET_ACTIVE_WINDOW")
s9_chrome_atom_protocols = d.intern_atom("WM_PROTOCOLS")
s9_chrome_atom_delete = d.intern_atom("WM_DELETE_WINDOW")
s9_chrome_atom_proxy = d.intern_atom("_S9_CHROME_PROXY_V1")


def s9_chrome_rpc(command):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
        s.settimeout(0.8)
        s.connect(s9_chrome_path)
        s.sendall((command + "\n").encode())
        s.shutdown(socket.SHUT_WR)

        chunks = []
        while True:
            part = s.recv(4096)
            if not part:
                break
            chunks.append(part)

    data = b"".join(chunks).decode(errors="replace")
    result = {}

    for line in data.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            result[key] = value

    return result


def s9_chrome_dispose():
    global s9_chrome_proxy
    global s9_chrome_last_status

    # S9_CHROME_GHOST_FIX_V2
    #
    # Ao fechar Chrome, remover explicitamente o proxy
    # do rastreamento EWMH, inclusive se estava IconicState.
    # O Docklike precisa receber a atualizacao da lista
    # para transformar o grupo novamente em launcher.

    if s9_chrome_proxy is not None:

        wid = s9_chrome_proxy.id

        cache = globals().get("tracked")

        if isinstance(cache, dict):
            cache.pop(wid, None)

        focus_cache = globals().get("pending_focus")

        if isinstance(focus_cache, dict):
            focus_cache.pop(wid, None)

        removed = 0

        for property_name in (
            "_NET_CLIENT_LIST",
            "_NET_CLIENT_LIST_STACKING"
        ):
            a = d.intern_atom(property_name)

            prop = root.get_full_property(
                a, X.AnyPropertyType
            )

            if prop is None:
                continue

            before = [int(x) for x in prop.value]
            after = [x for x in before if x != wid]

            if len(after) == len(before):
                continue

            root.change_property(
                a,
                Xatom.WINDOW,
                32,
                after,
                X.PropModeReplace
            )

            removed += 1

            print(
                f"S9_CHROME_GHOST_EWMH_PRUNED "
                f"property={property_name} "
                f"window=0x{wid:x} "
                f"remaining={len(after)}",
                flush=True
            )

        # Entregar a alteracao ao Xwayland antes de
        # destruir o recurso X11 do proxy.
        d.sync()

        print(
            f"S9_CHROME_GHOST_CLEANUP "
            f"window=0x{wid:x} "
            f"ewmh_properties_updated={removed}",
            flush=True
        )

    if s9_chrome_proxy is not None:
        wid = s9_chrome_proxy.id

        try:
            s9_chrome_proxy.destroy()
            d.sync()
        except Exception:
            pass

        print(
            f"S9_CHROME_PROXY_DESTROYED window=0x{wid:x}",
            flush=True
        )

    s9_chrome_proxy = None
    s9_chrome_last_status = {}


def s9_chrome_create():
    global s9_chrome_proxy

    if s9_chrome_proxy is not None:
        return

    # Configuracao ja validada no teste PoC.
    # Override-redirect evita superficie MirAL adicional.
    w = root.create_window(
        -4096, -4096,
        1, 1, 0,
        X.CopyFromParent,
        X.InputOutput,
        X.CopyFromParent,
        override_redirect=1
    )

    w.set_wm_class("google-chrome", "Google-chrome")
    w.set_wm_name("Google Chrome")

    w.change_property(
        s9_chrome_atom_type,
        Xatom.ATOM,
        32,
        [s9_chrome_atom_normal],
        X.PropModeReplace
    )

    w.change_property(
        s9_chrome_atom_proxy,
        Xatom.CARDINAL,
        32,
        [1],
        X.PropModeReplace
    )

    w.change_property(
        s9_chrome_atom_protocols,
        Xatom.ATOM,
        32,
        [s9_chrome_atom_delete],
        X.PropModeReplace
    )

    w.map()
    d.sync()

    s9_chrome_proxy = w

    print(
        f"S9_CHROME_PROXY_CREATED window=0x{w.id:x}",
        flush=True
    )


def s9_chrome_refresh():
    global s9_chrome_last_poll
    global s9_chrome_last_status
    global s9_chrome_last_focus
    global s9_chrome_failures

    now = time.monotonic()

    if now - s9_chrome_last_poll < 0.65:
        return

    s9_chrome_last_poll = now
    # S9_CHROME_BRIDGE_SWITCH_V2: com /etc/s9-docklike/chrome-bridge.off a ponte do Chrome Wayland fica desligada
    # (depois de atualizar last_poll, senao o laco de eventos nunca dorme)
    if os.path.exists("/etc/s9-docklike/chrome-bridge.off"):
        if s9_chrome_proxy is not None:
            s9_chrome_dispose()
        return

    try:
        status = s9_chrome_rpc("STATUS")
        s9_chrome_failures = 0
    except Exception:
        s9_chrome_failures += 1

        if s9_chrome_failures >= 2:
            s9_chrome_dispose()
        return

    if status.get("PRESENT") != "1":
        s9_chrome_dispose()
        return

    if status.get("FOCUSED") == "1":
        s9_chrome_last_focus = now

    s9_chrome_create()

    minimized = status.get("MINIMIZED") == "1"
    title = status.get("TITLE") or "Google Chrome"

    if status == s9_chrome_last_status:
        return

    state = 3 if minimized else 1

    s9_chrome_proxy.change_property(
        s9_chrome_atom_state,
        s9_chrome_atom_state,
        32,
        [state, 0],
        X.PropModeReplace
    )

    s9_chrome_proxy.change_property(
        s9_chrome_atom_netstate,
        Xatom.ATOM,
        32,
        [s9_chrome_atom_hidden] if minimized else [],
        X.PropModeReplace
    )

    s9_chrome_proxy.set_wm_name(title)

    s9_chrome_proxy.change_property(
        s9_chrome_atom_name,
        s9_chrome_atom_utf8,
        8,
        title.encode("utf-8"),
        X.PropModeReplace
    )

    d.sync()
    s9_chrome_last_status = status

    print(
        f"S9_CHROME_PROXY_STATE "
        f"window=0x{s9_chrome_proxy.id:x} "
        f"minimized={int(minimized)} "
        f"focused={status.get('FOCUSED')} "
        f"title={title!r}",
        flush=True
    )


def s9_chrome_handle_event(ev):
    global s9_chrome_last_click
    global s9_chrome_last_poll

    if s9_chrome_proxy is None:
        return False

    if ev.type != X.ClientMessage:
        return False

    if ev.window.id != s9_chrome_proxy.id:
        return False

    now = time.monotonic()

    if ev.client_type == s9_chrome_atom_close:
        if now - s9_chrome_last_click < 0.35:
            return True

        command = "CLOSE"

    elif ev.client_type == s9_chrome_atom_active:
        if now - s9_chrome_last_click < 0.5:
            return True

        try:
            status = s9_chrome_rpc("STATUS")
        except Exception as exc:
            print(
                f"S9_CHROME_PROXY_IPC_ERROR error={exc}",
                flush=True
            )
            return True

        if status.get("PRESENT") != "1":
            return True

        if status.get("MINIMIZED") == "1":
            command = "RESTORE"
        elif (
            status.get("FOCUSED") == "1" or
            now - s9_chrome_last_focus < 1.0
        ):
            command = "MINIMIZE"
        else:
            command = "ACTIVATE"

    else:
        return True

    try:
        result = s9_chrome_rpc(command)

        if not any(key == "OK" for key in result):
            raise RuntimeError(str(result))

        s9_chrome_last_click = now
        s9_chrome_last_poll = 0.0

        print(
            f"S9_CHROME_PROXY_ACTION "
            f"window=0x{s9_chrome_proxy.id:x} "
            f"command={command} result={result}",
            flush=True
        )

    except Exception as exc:
        print(
            f"S9_CHROME_PROXY_ACTION_ERROR "
            f"command={command} error={exc}",
            flush=True
        )

    return True


print("S9_CHROME_PROXY_BRIDGE_READY=1", flush=True)

print("S9_DOCKLIKE_TOGGLE_CLOSE_V2_READY=1", flush=True)



def s9_process_pending_focus():
    now = time.monotonic()

    for wid, deadline in list(pending_focus.items()):

        try:
            if wid not in tracked:
                del pending_focus[wid]
                continue

            window = d.create_resource_object(
                "window", wid
            )

            state = s9_wm_state(window)
            hidden = s9_is_hidden(window)

            if state == 1 and not hidden:

                del pending_focus[wid]

                s9_send_activation(window)

                print(
                    f"S9_DOCKLIKE_RESTORE_SUCCESS "
                    f"window=0x{wid:x} state=1 hidden=0 "
                    f"activation_sent=1",
                    flush=True
                )

            elif now >= deadline:

                del pending_focus[wid]

                print(
                    f"S9_DOCKLIKE_RESTORE_TIMEOUT "
                    f"window=0x{wid:x} "
                    f"state={state} hidden={int(hidden)}",
                    flush=True
                )

        except Exception as exc:

            pending_focus.pop(wid, None)

            print(
                f"S9_DOCKLIKE_FOCUS_ERROR "
                f"window=0x{wid:x} error={exc}",
                flush=True
            )


print("S9_EWMH_CLICK_RESTORE_READY=1", flush=True)
print("S9_DOCKLIKE_TOGGLE_V1_READY=1", flush=True)

# S9_DOCKLIKE_EVENT_LOOP_V1
#
# O laço principal acordava a cada 100 ms e refazia get_windows()
# (4-5 roundtrips X por janela): ~775 acordadas/s no python e ~750/s
# no Xwayland. Agora o laço espera eventos X (select no socket) e só
# recalcula a lista quando algo mudou:
#   - eventos de estrutura da raiz (create/destroy/map/unmap/reparent/
#     configure/circulate) e PropertyNotify da raiz (exceto as
#     propriedades que nós mesmos publicamos e _NET_ACTIVE_WINDOW);
#   - recálculo de segurança a cada S9_SAFETY_SEC mesmo sem eventos;
#   - no máximo um recálculo a cada S9_MIN_FULL_SEC (como antes: 10/s).
# O foco (_NET_ACTIVE_WINDOW) continua sendo observado por evento
# (s9_process_activation_requests já trata o PropertyNotify da raiz) e
# a cada acordada; pending_focus mantém o ritmo de 100 ms enquanto houver
# restauração pendente; o poll do Chrome mantém 0,65 s.

import select

S9_SAFETY_SEC = 1.5
S9_MIN_FULL_SEC = 0.1
S9_DEBOUNCE_SEC = 0.02
S9_CHROME_POLL_SEC = 0.65

s9_el_dirty = True
s9_el_last_full = 0.0

s9_el_structure_events = {
    X.CreateNotify, X.DestroyNotify, X.MapNotify, X.UnmapNotify,
    X.ReparentNotify, X.ConfigureNotify, X.CirculateNotify,
}

s9_el_ignored_atoms = {
    int(a_list), int(a_stack), int(a_owner), int(a_restore_active),
}

_s9_el_orig_next_event = d.next_event


def s9_el_next_event(*args, **kwargs):
    global s9_el_dirty

    ev = _s9_el_orig_next_event(*args, **kwargs)

    try:
        if ev.type in s9_el_structure_events:
            s9_el_dirty = True
        elif (
            ev.type == X.PropertyNotify and
            int(ev.atom) not in s9_el_ignored_atoms
        ):
            s9_el_dirty = True
    except Exception:
        s9_el_dirty = True

    return ev


d.next_event = s9_el_next_event


def s9_el_full_due():
    now = time.monotonic()

    if s9_el_dirty and now - s9_el_last_full >= S9_MIN_FULL_SEC:
        return True

    return now - s9_el_last_full >= S9_SAFETY_SEC


def s9_el_mark_full():
    global s9_el_dirty
    global s9_el_last_full

    s9_el_dirty = False
    s9_el_last_full = time.monotonic()


def s9_el_wait():
    now = time.monotonic()

    if s9_el_dirty:
        timeout = max(
            S9_DEBOUNCE_SEC,
            s9_el_last_full + S9_MIN_FULL_SEC - now
        )
    else:
        timeout = s9_el_last_full + S9_SAFETY_SEC - now

    timeout = min(
        timeout,
        s9_chrome_last_poll + S9_CHROME_POLL_SEC - now
    )

    if pending_focus:
        timeout = min(timeout, 0.1)

    timeout = max(0.0, min(timeout, 1.0))

    try:
        if d.pending_events():
            return
    except Exception:
        pass

    try:
        select.select([d.fileno()], [], [], timeout)
    except (OSError, ValueError):
        time.sleep(min(timeout, 0.1))


print("EWMH_BRIDGE_STARTED=1", flush=True)

print(f"PID={pid}", flush=True)

try:
    while running:
        # S9_DOCKLIKE_EVENT_LOOP_V1: so recalcula quando houver motivo.
        s9_prev_proxy = s9_chrome_proxy
        s9_chrome_refresh()

        if s9_chrome_proxy is not s9_prev_proxy:
            s9_el_dirty = True

        if not s9_el_full_due():
            s9_process_activation_requests()
            s9_process_pending_focus()
            s9_el_wait()
            continue

        s9_el_mark_full()

        if owner() != pid:
            raise RuntimeError("EWMH_OWNER_CHANGED")

        s9_chrome_refresh()
        found = get_windows()
        if s9_chrome_proxy is not None:
            found.append((
                s9_chrome_proxy.id,
                "google-chrome/Google-chrome"
            ))
        stacking = [wid for wid, cls in found]

        for wid in stacking:
            if wid not in tracked:
                tracked.append(wid)

        tracked = [
            wid for wid in tracked
            if wid in stacking
        ]

        changed = (
            tracked != last_list or
            stacking != last_stack or
            get_property(a_list) != tracked or
            get_property(a_stack) != stacking
        )

        if changed:
            publish(a_list, tracked)
            publish(a_stack, stacking)
            d.sync()

            last_list = list(tracked)
            last_stack = list(stacking)

            print(f"WINDOW_COUNT={len(tracked)}", flush=True)

            for wid, cls in found:
                print(f"WINDOW=0x{wid:x} CLASS={cls}", flush=True)

        s9_process_activation_requests()
        s9_process_pending_focus()

        s9_el_wait()

finally:
    try:
        s9_chrome_dispose()
        if owner() == pid:
            if (
                last_list is not None and
                get_property(a_list) == last_list
            ):
                root.delete_property(a_list)

            if (
                last_stack is not None and
                get_property(a_stack) == last_stack
            ):
                root.delete_property(a_stack)

            root.delete_property(a_owner)
            d.sync()
            print("EWMH_CLEANUP_COMPLETE=1", flush=True)

    except Exception as e:
        print(f"CLEANUP_ERROR={e}", flush=True)

    d.close()

print("EWMH_BRIDGE_STOPPED=1", flush=True)
