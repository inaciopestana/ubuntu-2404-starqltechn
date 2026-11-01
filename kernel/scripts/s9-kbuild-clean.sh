#!/usr/bin/env bash
# s9-kbuild-clean.sh - full kernel rebuild from a NEUTRAL source path, then rebuild the boot image
# by replacing ONLY the kernel of an existing, known-good boot image.
#
# Why: the Android GCC 4.9 toolchain cannot remap __FILE__ (-ffile-prefix-map needs GCC 8), so
# building from /home/<you>/... embeds that path in the kernel. Here the source and the object
# directory are bind-mounted at /build/kernel-source and /build/kernel-obj inside the Jammy
# chroot, so no personal path ends up in a boot image you want to publish.
#
# Run (needs root for systemd-nspawn):
#   sudo S9_WORK=$HOME/s9-ubuntu2404-kernel bash s9-kbuild-clean.sh <base-boot.img> <sha256-of-base-boot.img> [prebuilt-Image.gz-dtb]
# With the third argument the build is skipped and that kernel (from an earlier run) is used.
# It writes nothing to the phone. Output: $S9_WORK/out/clean-<timestamp>/boot-clean.img
set -euo pipefail
BASE=${1:?usage: sudo bash s9-kbuild-clean.sh <base-boot.img> <sha256>}
BASE_SHA=${2:?usage: sudo bash s9-kbuild-clean.sh <base-boot.img> <sha256>}
PREBUILT=${3:-}
U=${SUDO_USER:?run with sudo}
R=${S9_WORK:-/home/$U/s9-ubuntu2404-kernel}
D=$R/workdir/downloads
KS=$D/kernel-source
OLDOBJ=$D/KERNEL_OBJ                  # only used to copy .config from
TC=$D/aarch64-linux-android-4.9
TC32=$D/arm-linux-androideabi-4.9
C=/opt/ubuntu2204
UB=$D/android_system_tools_mkbootimg/unpack_bootimg.py
MK=$D/android_system_tools_mkbootimg/mkbootimg.py
OUTD=$R/out/clean-$(date +%Y%m%d-%H%M%S)
NEWOBJ=$OUTD/kernel-obj
mkdir -p "$NEWOBJ"

echo "== checks"
echo "$BASE_SHA  $BASE" | sha256sum -c - || { echo "ERROR: base boot image hash mismatch"; exit 1; }
for p in "$UB" "$MK"; do [ -e "$p" ] || { echo "ERROR: missing $p"; exit 1; }; done
[ -d "$TC32" ] || TC32=""
grep -qE '^#define SECDP_HDCP_DISABLE' "$KS/drivers/gpu/drm/msm/dp/secdp.h" || echo "WARNING: SECDP_HDCP_DISABLE is not active in this tree"

BINDS=(--bind="$KS":/build/kernel-source --bind="$NEWOBJ":/build/kernel-obj --bind-ro="$TC":/build/tc64)
[ -n "$TC32" ] && BINDS+=(--bind-ro="$TC32":/build/tc32)
NS=(systemd-nspawn -q --register=no "${BINDS[@]}" -D "$C")

if [ -z "$PREBUILT" ]; then
for p in "$KS" "$OLDOBJ/.config" "$TC/bin" "$C"; do [ -e "$p" ] || { echo "ERROR: missing $p"; exit 1; }; done
[ -d "$TC32" ] || TC32=""
cp "$OLDOBJ/.config" "$NEWOBJ/.config"
echo "== full build in the chroot (this takes a while; log: $OUTD/build.log)"
"${NS[@]}" /bin/bash -c "
set -e
export ARCH=arm64 CROSS_COMPILE=aarch64-linux-android- CROSS_COMPILE_ARM32=arm-linux-androideabi-
export PATH=/build/tc64/bin:/build/tc32/bin:\$PATH
export KBUILD_BUILD_USER=build KBUILD_BUILD_HOST=s9
cd /build/kernel-source
make O=/build/kernel-obj olddefconfig </dev/null
make O=/build/kernel-obj -j$(nproc) </dev/null
" 2>&1 | tee "$OUTD/build.log" || { echo "BUILD FAILED, see $OUTD/build.log"; exit 1; }
fi
NEWK=${PREBUILT:-$NEWOBJ/arch/arm64/boot/Image.gz-dtb}
[ -s "$NEWK" ] || { echo "ERROR: no Image.gz-dtb produced"; exit 1; }
ls -l "$NEWK"

echo "== assembling the boot image (only the kernel is replaced)"
python3 -I "$UB" --boot_img "$BASE" --out "$OUTD/base-unpack" --format=mkbootimg > "$OUTD/mkbootimg-args.txt"
python3 -I - "$OUTD" "$NEWK" "$MK" "$BASE" <<'PY'
import shlex, subprocess, sys, pathlib, struct
outd = pathlib.Path(sys.argv[1]); newk = pathlib.Path(sys.argv[2]); mk = sys.argv[3]; base = pathlib.Path(sys.argv[4])
args = shlex.split((outd/'mkbootimg-args.txt').read_text())
i = args.index('--kernel'); args[i + 1] = str(newk)
raw = outd/'boot-raw.img'
subprocess.run(['python3', mk] + args + ['-o', str(raw)], check=True)
PAGE = 4096
al = lambda n: (n + PAGE - 1) // PAGE * PAGE
oldk = outd/'base-unpack'/'kernel'
bd = base.read_bytes(); nd = raw.read_bytes()
marker = b'SEANDROIDENFORCE'
lo = bd.rfind(marker); assert lo >= 0, 'marker not found in the base image'
assert len(nd) == lo + al(newk.stat().st_size) - al(oldk.stat().st_size), 'layout differs from the base image'
nd += marker
assert len(nd) <= 64 * 1024 * 1024
nd = nd.ljust(64 * 1024 * 1024, b'\0')
hdr = bytearray(bd[:1632])                       # keep the base header (second_addr etc.), change kernel_size and id
struct.pack_into('<I', hdr, 8, struct.unpack_from('<I', nd, 8)[0])
hdr[576:608] = nd[576:608]
assert nd[1632:4096] == bd[1632:4096]
out = bytes(hdr) + nd[1632:]
assert len(out) == 64 * 1024 * 1024
(outd/'boot-clean.img').write_bytes(out); raw.unlink()
print('image:', outd/'boot-clean.img')
PY

echo "== verification"
python3 -I - "$BASE" "$OUTD/boot-clean.img" "$NEWK" <<'PY'
import struct, sys, zlib, re, hashlib, pathlib
base, new, newk = (pathlib.Path(p).read_bytes() for p in sys.argv[1:4])
fail = []
def ok(c, m):
    print(('OK    ' if c else 'FAIL  ') + m)
    if not c: fail.append(m)
H = struct.Struct('<8s10I16s512s32s1024s')
N = ['magic','kernel_size','kernel_addr','ramdisk_size','ramdisk_addr','second_size','second_addr','tags_addr','page_size','header_version','os_version','name','cmdline','id','extra_cmdline']
hb, hn = dict(zip(N, H.unpack_from(base, 0))), dict(zip(N, H.unpack_from(new, 0)))
diff = [k for k in N if hb[k] != hn[k]]
ok(set(diff) <= {'kernel_size', 'id'}, 'header identical except kernel_size and id (differs: %s)' % diff)
P = hb['page_size']; al = lambda n: (n + P - 1) // P * P
def parts(img, h):
    ks, rs = h['kernel_size'], h['ramdisk_size']; ro = P + al(ks)
    return img[P:P+ks], img[ro:ro+rs], ro + al(rs)
bk, br, be = parts(base, hb); nk, nr, ne = parts(new, hn)
ok(nr == br, 'ramdisk byte-identical to the base image')
ok(nk == newk, 'kernel in the image == freshly built Image.gz-dtb')
ok(new[ne:ne+16] == b'SEANDROIDENFORCE' and new[ne+16:].count(0) == len(new) - ne - 16, 'SEANDROIDENFORCE then zeros only')
o = zlib.decompressobj(31); img = o.decompress(nk); dtb = o.unused_data
ob = zlib.decompressobj(31); bimg = ob.decompress(bk); bdtb = ob.unused_data
ok(len(dtb) == len(bdtb) and dtb[:4] == b'\xd0\x0d\xfe\xed', 'appended DTBs: same size as the base, valid magic')
ok(abs(len(img) - len(bimg)) < 262144, 'kernel size close to the base kernel (%d vs %d bytes)' % (len(img), len(bimg)))
for what, blob in (('kernel', img), ('dtb', dtb), ('ramdisk', new[P+al(hn['kernel_size']):P+al(hn['kernel_size'])+hn['ramdisk_size']])):
    ok(b'/home/' not in blob, 'no "/home/" path in the %s' % what)
for s in (b's9_uw_hz', b'skip hdcp'):
    ok(s in img, 'kernel contains %r' % s.decode())
m = re.search(rb'Linux version [^\n\0]+', img); print('--', m.group(0)[:120].decode() if m else 'no version string')
print('sha256 of the new image:', hashlib.sha256(new).hexdigest())
print('RESULT:', 'REJECTED' if fail else 'APPROVED'); sys.exit(1 if fail else 0)
PY
chown -R "$U":"$U" "$OUTD"
sha256sum "$OUTD/boot-clean.img"
echo "DONE: $OUTD/boot-clean.img  (NOT written to the phone; flash only after you test it)"
