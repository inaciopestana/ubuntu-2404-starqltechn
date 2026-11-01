#!/usr/bin/env python3
from __future__ import annotations
import argparse, csv, re
from pathlib import Path

FORBID = re.compile(r'(G965|star2qltechn|star2qlte)', re.I)
SKIP_SUBSYSTEM = re.compile(r'(camera|gps|nfc|ril|ofono|audio|pulse|pipewire)', re.I)

CANDIDATE_PREFIXES = (
 'usr/lib/aarch64-linux-gnu/libhybris', 'usr/lib/aarch64-linux-gnu/libmir', 'usr/lib/mir',
 'usr/bin/miral-shell','usr/bin/miriway','usr/bin/Xwayland','usr/share/halium-overlay',
 'usr/lib/lxc-android-config','var/lib/lxc/android','etc/lxc','etc/ubuntu-touch-session.d'
)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--reference-root', required=True)
    ap.add_argument('--output', required=True)
    ap.add_argument('--allow-xwayland', action='store_true')
    ns=ap.parse_args()
    root=Path(ns.reference_root).resolve(); out=Path(ns.output)
    if not root.is_dir(): ap.error('reference-root inválida')
    rows=[]
    for p in root.rglob('*'):
        rel=p.relative_to(root).as_posix()
        if FORBID.search(rel) or SKIP_SUBSYSTEM.search(rel): continue
        if not any(rel.startswith(x) for x in CANDIDATE_PREFIXES): continue
        if rel.endswith('Xwayland') and not ns.allow_xwayland: continue
        kind='dir' if p.is_dir() else ('symlink' if p.is_symlink() else 'file')
        rows.append((kind, str(p), '/'+rel, 'yes', 'Halium/Mir runtime reference', 'reference-runtime'))
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open('w', newline='') as f:
        w=csv.writer(f, delimiter='\t'); w.writerow(['kind','source','target','required','reason','owner']); w.writerows(rows)
    print(f'{len(rows)} linhas em {out}')
if __name__=='__main__': main()
