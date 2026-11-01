#!/usr/bin/env python3
"""build-ramdisk.py - build the S9 initramfs (gzip-compressed "newc" cpio) from an arm64 root.

The ramdisk is tiny: a static busybox, `dmsetup` with the shared libraries it needs, the
mount-point directories and kernel/ramdisk/init. Everything binary is taken from an
Ubuntu 24.04 arm64 root file system you already have (e.g. the debootstrap tree), so nothing
proprietary is involved. Needs only Python 3 and `readelf` (binutils); no root, no cpio.

  Packages in the arm64 root: busybox-static, dmsetup (pulls libdevmapper, libselinux, libudev,
  libcap, libpcre2-8 and libc6).

  kernel/ramdisk/build-ramdisk.py --rootfs /path/to/arm64/root --out ramdisk.cpio.gz

Output is reproducible (fixed timestamps, root:root, sorted entries).
"""
import argparse, gzip, os, re, subprocess, sys

APPLETS = "cat chmod date dmesg echo grep ls mkdir mknod mount sh sleep switch_root sync umount uname".split()
DIRS = ["bin", "sbin", "lib", "dev", "proc", "sys", "run", "newroot"]


def resolve(root, path):
    """Follow symlinks of `path` (absolute inside the root) without leaving the root."""
    cur = path
    for _ in range(40):
        real = os.path.join(root, cur.lstrip("/"))
        parts = cur.strip("/").split("/")
        # resolve each component (handles usr-merge symlinks like /sbin -> usr/sbin)
        acc = ""
        for i, p in enumerate(parts):
            acc = acc + "/" + p
            full = os.path.join(root, acc.lstrip("/"))
            if os.path.islink(full):
                tgt = os.readlink(full)
                tgt = tgt if tgt.startswith("/") else os.path.normpath(os.path.join(os.path.dirname(acc), tgt))
                cur = os.path.normpath(os.path.join(tgt, *parts[i + 1:]))
                break
        else:
            return real
    sys.exit("too many symlinks: " + path)


def readelf(args, f):
    return subprocess.run(["readelf"] + args + [f], check=True, capture_output=True, text=True).stdout


def needed(f):
    return re.findall(r"\(NEEDED\)\s+Shared library: \[(.+?)\]", readelf(["-d", "-W"], f))


def interp(f):
    m = re.search(r"Requesting program interpreter: (\S+?)\]", readelf(["-l", "-W"], f))
    return m.group(1) if m else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rootfs", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--init", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "init"))
    ap.add_argument("--triplet", default="aarch64-linux-gnu", help="multiarch directory name")
    ap.add_argument("--busybox", default="/bin/busybox")
    ap.add_argument("--dmsetup", default="/sbin/dmsetup")
    a = ap.parse_args()
    root = os.path.realpath(a.rootfs)
    libdirs = ["/lib/" + a.triplet, "/usr/lib/" + a.triplet, "/lib", "/usr/lib"]

    files = {}      # archive path -> (mode, bytes or link target)
    def add_file(arc, src, mode=0o755):
        with open(src, "rb") as fh:
            files[arc] = (mode, fh.read())

    bb = resolve(root, a.busybox)
    dm = resolve(root, a.dmsetup)
    for p in (bb, dm, a.init):
        if not os.path.isfile(p):
            sys.exit("missing: " + p)
    if needed(bb):
        sys.exit("busybox must be statically linked (install busybox-static)")
    add_file("bin/busybox", bb)
    for ap_ in APPLETS:
        files["bin/" + ap_] = (0o120777, b"busybox")
    add_file("sbin/dmsetup", dm)
    add_file("init", a.init)

    # shared libraries of dmsetup, recursively
    todo, seen = [dm], set()
    ip = interp(dm)
    if ip:
        add_file(ip.lstrip("/"), resolve(root, ip))
    while todo:
        f = todo.pop()
        for lib in needed(f):
            if lib in seen or (ip and lib == os.path.basename(ip)):
                continue            # the loader is added separately below
            seen.add(lib)
            for d in libdirs:
                cand = resolve(root, d + "/" + lib)
                if os.path.exists(cand):
                    add_file("lib/%s/%s" % (a.triplet, lib), cand, 0o644 if not lib.startswith(("libc.", "ld-", "libm.")) else 0o755)
                    todo.append(cand)
                    break
            else:
                sys.exit("library not found in the root: " + lib)
    if ip:  # the loader also lives next to the libraries (LD_LIBRARY_PATH in init)
        add_file("lib/%s/%s" % (a.triplet, os.path.basename(ip)), resolve(root, ip))

    # ---- write newc cpio -------------------------------------------------------------
    out = bytearray()
    ino = [0]
    def entry(name, mode, data=b"", nlink=1):
        ino[0] += 1
        nm = name.encode() + b"\0"
        hdr = "070701" + "".join("%08x" % v for v in (
            ino[0], mode, 0, 0, nlink, 0, len(data), 0, 0, 0, 0, len(nm), 0))
        out.extend(hdr.encode() + nm)
        out.extend(b"\0" * (-len(out) % 4))
        out.extend(data)
        out.extend(b"\0" * (-len(out) % 4))

    entries = {d: (0o40755, b"") for d in DIRS}
    for arc in files:                       # parent directories
        parent = os.path.dirname(arc)
        while parent:
            entries.setdefault(parent, (0o40755, b""))
            parent = os.path.dirname(parent)
    for arc, (mode, data) in files.items():
        entries[arc] = (mode if mode & 0o170000 else 0o100000 | mode, data)
    for name in sorted(entries):
        mode, data = entries[name]
        entry(name, mode, data)
    entry("TRAILER!!!", 0)
    with open(a.out, "wb") as fh:
        with gzip.GzipFile(filename="", mode="wb", fileobj=fh, compresslevel=9, mtime=0) as gz:
            gz.write(bytes(out))
    print("wrote %s: %d entries, %d bytes uncompressed" % (a.out, len(entries), len(out)))


if __name__ == "__main__":
    main()
