#!/usr/bin/env python3
"""Anchor panel popup windows under X11/Xwayland; follow ConfigureNotify.

Catches same-window relocations/reflows that occur *after* opening GTK menus.
No polling of cursor, no global repositioning of unrelated application menus.
"""
import heapq
import os
import re
import select
import subprocess
import time
from Xlib import X, Xatom, display
from Xlib.error import XError

D = display.Display()
ROOT = D.screen().root

def atom(name):
    return D.intern_atom(name)

TYPES = {name: atom('_NET_WM_WINDOW_TYPE_' + name)
         for name in ('DOCK', 'MENU', 'POPUP_MENU', 'DROPDOWN_MENU',
                      'COMBO', 'UTILITY', 'TOOLTIP', 'NOTIFICATION', 'NORMAL')}
A_TYPE = atom('_NET_WM_WINDOW_TYPE')
MENU_TYPES = {TYPES[name] for name in ('MENU', 'POPUP_MENU', 'DROPDOWN_MENU', 'COMBO', 'UTILITY')}
EXCLUDED_TYPES = {TYPES[name] for name in ('DOCK', 'TOOLTIP', 'NOTIFICATION', 'NORMAL')}

# wid -> dict(kind, ref, px, py, x_offset, initial_x, last_move)
ANCHORS = {}
TASKS = []
PENDING = set()
SEQ = 0
MONITORS = []
MONITORS_AT = 0.0

def log(msg):
    print(time.strftime('%H:%M:%S'), msg, flush=True)

def rect(w):
    g = w.get_geometry()
    xy = w.translate_coords(ROOT, 0, 0)
    return (xy.x, xy.y, g.width, g.height)

def visible_rect(wid):
    w = D.create_resource_object('window', wid)
    a = w.get_attributes()
    if a.map_state != X.IsViewable or a.win_class != X.InputOutput:
        return None
    return rect(w)

def contains(r, x, y, margin=0):
    rx, ry, rw, rh = r
    return rx-margin <= x < rx+rw+margin and ry-margin <= y < ry+rh+margin

def clamp(v, lo, hi):
    return max(lo, min(v, max(lo, hi)))

def get_types(w):
    p = w.get_full_property(A_TYPE, Xatom.ATOM)
    return set(map(int, p.value)) if p is not None else set()

def get_class(w):
    return ' '.join(w.get_wm_class() or ()).lower()

def monitors():
    global MONITORS, MONITORS_AT
    now = time.monotonic()
    if MONITORS and now-MONITORS_AT < 1.5:
        return MONITORS
    found = []
    try:
        result = subprocess.check_output(['xrandr', '--listmonitors'],
                                         text=True, timeout=.5,
                                         stderr=subprocess.DEVNULL)
        rx = re.compile(r'(\d+)/\d+x(\d+)/\d+([+-]\d+)([+-]\d+)')
        for m in rx.finditer(result):
            w,h,x,y = map(int, m.groups())
            if w > 0 and h > 0:
                found.append((x,y,w,h))
    except (OSError, subprocess.SubprocessError):
        pass
    if not found:
        g = ROOT.get_geometry()
        found = [(0,0,g.width,g.height)]
    MONITORS, MONITORS_AT = found, now
    return found

def monitor_for(r):
    x,y,w,h = r
    cx,cy=x+w/2,y+h/2
    ms=monitors()
    for m in ms:
        if contains(m,cx,cy):
            return m
    return min(ms, key=lambda m:(cx-m[0]-m[2]/2)**2+(cy-m[1]-m[3]/2)**2)

def panel_rects():
    found=[]
    for w in ROOT.query_tree().children:
        try:
            if w.get_attributes().map_state != X.IsViewable:
                continue
            if 'xfce4-panel' not in get_class(w) or TYPES['DOCK'] not in get_types(w):
                continue
            r=rect(w)
            if r[2] >= 80 and r[3] >= 14:
                found.append((w.id,r))
        except XError:
            pass
    return found

def panel_under_pointer(px, py):
    candidates=[(wid,r) for wid,r in panel_rects() if contains(r,px,py,6)]
    if not candidates:
        return None
    return min(candidates,key=lambda z:abs(z[1][0]+z[1][2]/2-px)+
               abs(z[1][1]+z[1][3]/2-py))

def is_menu(w):
    a=w.get_attributes()
    if a.map_state != X.IsViewable or a.win_class != X.InputOutput:
        return False
    r=rect(w)
    if r[2] < 65 or r[3] < 24:
        return False
    ts=get_types(w)
    if ts & EXCLUDED_TYPES:
        return False
    # GTK often uses override_redirect for popup windows.
    return bool(ts & MENU_TYPES or a.override_redirect or
                ('xfce4-panel' in get_class(w) and not ts))

def schedule(wid, delay):
    global SEQ
    if wid in PENDING:
        return
    PENDING.add(wid)
    SEQ += 1
    heapq.heappush(TASKS,(time.monotonic()+delay,SEQ,wid))

def make_anchor(wid,px,py,kind,ref):
    if wid in ANCHORS:
        return
    try:
        w=D.create_resource_object('window',wid)
        if not is_menu(w):
            return
        x,y,width,height=rect(w)
        if kind=='panel':
            panel=dict(panel_rects()).get(ref)
            if panel is None or not contains(panel,px,py,12):
                return
            bx,by,bw,bh=panel
            # Preserve correct horizontal placement when already near icon.
            initial_x=x if x-2 <= px <= x+width+2 else round(px-width/2)
            x_offset=initial_x-bx
        else:
            parent=visible_rect(ref)
            if parent is None or not contains(parent,px,py,10):
                return
            x_offset=0
            initial_x=x
        ANCHORS[wid]=dict(kind=kind,ref=ref,px=px,py=py,
                          x_offset=x_offset,initial_x=initial_x,
                          last_move=0.,moves=[])
        # V4: primeira tentativa sincronamente no MapNotify.
        # A segunda tentativa corrige eventuais reflows do GTK.
        anchor(wid)
        schedule(wid,.012)
        log(f'watch id=0x{wid:x} kind={kind} parent=0x{ref:x}')
    except XError:
        pass

def anchor(wid):
    state=ANCHORS.get(wid)
    if state is None:
        return
    try:
        w=D.create_resource_object('window',wid)
        if not is_menu(w):
            ANCHORS.pop(wid,None)
            return
        x,y,width,height=rect(w)
        if state['kind']=='panel':
            panel=dict(panel_rects()).get(state['ref'])
            if panel is None:
                ANCHORS.pop(wid,None)
                return
            bx,by,bw,bh=panel
            mx,my,mw,mh=monitor_for(panel)
            if bw >= bh:
                top = by+bh/2 < my+mh/2
                target_y=by+bh if top else by-height
                target_x=bx+state['x_offset']
            else:
                left=bx+bw/2 < mx+mw/2
                target_x=bx+bw if left else bx-width
                target_y=state['py']-height/2
        else:
            parent=visible_rect(state['ref'])
            if parent is None:
                ANCHORS.pop(wid,None)
                return
            bx,by,bw,bh=parent
            mx,my,mw,mh=monitor_for(parent)
            target_x=bx+bw if bx+bw+width<=mx+mw else bx-width
            target_y=clamp(state['py']-12,by-4,by+bh)
        target_x=round(clamp(target_x,mx,mx+mw-width))
        target_y=round(clamp(target_y,my,my+mh-height))
        if abs(x-target_x)>1 or abs(y-target_y)>1:
            now=time.monotonic()
            moves=[t for t in state['moves'] if now-t<1.0]
            # Avoid feedback loops if GTK immediately undoes every X11 move.
            if len(moves)>=12:
                state['moves']=moves
                return
            moves.append(now)
            state['moves']=moves
            w.configure(x=target_x,y=target_y)
            D.flush()
            state['last_move']=now
            log(f'fix 0x{wid:x} {state["kind"]} ({x},{y}) -> '
                f'({target_x},{target_y}) {width}x{height}')
    except XError:
        ANCHORS.pop(wid,None)
    except Exception as ex:
        log(f'warn 0x{wid:x}: {ex}')

def on_map(e):
    wid=e.window.id
    if wid==ROOT.id:
        return
    try:
        pointer=ROOT.query_pointer()
        px,py=pointer.root_x,pointer.root_y
        p=panel_under_pointer(px,py)
        if p is not None:
            make_anchor(wid,px,py,'panel',p[0])
            return
        # Only anchor submenu windows while cursor is over an already watched menu.
        for ref in reversed(list(ANCHORS)):
            try:
                r=visible_rect(ref)
                if r and contains(r,px,py,4):
                    make_anchor(wid,px,py,'submenu',ref)
                    return
            except XError:
                ANCHORS.pop(ref,None)
    except XError:
        pass

def main():
    ROOT.change_attributes(event_mask=X.SubstructureNotifyMask)
    D.flush()
    log(f'anchor-v3 ativo DISPLAY={os.getenv("DISPLAY")} panels={len(panel_rects())}')
    while True:
        while D.pending_events():
            e=D.next_event()
            if e.type == X.MapNotify:
                on_map(e)
            elif e.type == X.ConfigureNotify:
                # Main difference vs v2: react to GTK relocating/resizing an OPEN menu.
                wid=e.window.id
                if wid in ANCHORS:
                    schedule(wid,.022)
            elif e.type in (X.UnmapNotify,X.DestroyNotify):
                wid=e.window.id
                ANCHORS.pop(wid,None)
                PENDING.discard(wid)
        now=time.monotonic()
        while TASKS and TASKS[0][0] <= now:
            _,_,wid=heapq.heappop(TASKS)
            if wid in PENDING:
                PENDING.discard(wid)
                anchor(wid)
        # For missed ConfigureNotify on rootless windows, resample active popups.
        # At most every ~0.15s, without injecting mouse movement or altering focus.
        for wid,s in list(ANCHORS.items()):
            if wid not in PENDING and now-s['last_move'] >= .35:
                schedule(wid,.035)
                s['last_move']=now
        timeout=max(0.,min(.15,TASKS[0][0]-time.monotonic() if TASKS else .15))
        select.select([D.fileno()],[],[],timeout)

if __name__=='__main__':
    main()
