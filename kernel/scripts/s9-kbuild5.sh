#!/usr/bin/env bash
# s9-kbuild5.sh: kernel v5 (= v4 + SECDP_HDCP_DISABLE). Rode com: sudo bash ~/s9-kbuild5.sh   (precisa antes do s9-kpatch5.sh)
# Compila incremental no chroot Jammy, monta o boot trocando SOMENTE o kernel do boot ao vivo (backup de 20/10) e verifica.
# NAO grava nada no celular. Log: $OUTD/build.log
set -euo pipefail
U=${SUDO_USER:?rode com: sudo bash s9-kbuild5.sh}
R=/home/$U/s9-ubuntu2404-kernel
D=$R/workdir/downloads
KS=$D/kernel-source
O=$D/KERNEL_OBJ
DP=$KS/drivers/gpu/drm/msm/dp
C=/opt/ubuntu2204
LIVE=$R/workdir/backups-boot/boot-live-20261020-114720.img
LIVE_SHA=a27701c0b70944aecbb9e9ccf609705421a5fd016d7628b10e69ae5ec0ceb641
REF=$R/workdir/s9root-expand/boot-s9root-expanded-v2.img
KORIG=$R/out/ultrawide-20261020-120209/Image.gz-dtb.orig
V4IMG=$(ls -1d "$R"/out/ultrawide-v4-*/boot-ultrawide-v4.img 2>/dev/null | tail -1)
OUTD=$R/out/ultrawide-v5-$(date +%Y%m%d-%H%M%S)
UB=$D/android_system_tools_mkbootimg/unpack_bootimg.py
MK=$D/android_system_tools_mkbootimg/mkbootimg.py
NM=$D/aarch64-linux-android-4.9/bin/aarch64-linux-android-nm
DPO=$O/drivers/gpu/drm/msm/dp/dp_drm.o
DDO=$O/drivers/gpu/drm/msm/dp/dp_display.o
mkdir -p "$OUTD"
NS="systemd-nspawn -q --register=no --bind=$R -D $C"

echo "== pré-requisitos"
echo "$LIVE_SHA  $LIVE" | sha256sum -c - || { echo "ERRO: backup ao vivo não bate com o hash"; exit 1; }
[ "$(grep -c 'S9-UW-V3' "$DP/dp_drm.c")" = 4 ] && [ "$(grep -c 'S9-UW-V4' "$DP/dp_drm.c")" = 1 ] || { echo "ERRO: dp_drm.c não está no estado v4"; exit 1; }
grep -qE '^#define SECDP_WIDE_32_9_SUPPORT' "$DP/secdp.h" && grep -qE '^#define SECDP_HIGH_REFRESH_SUPPORT' "$DP/secdp.h" || { echo "ERRO: macros v4 do secdp.h"; exit 1; }
[ "$(grep -c 'S9-HDCP-V5' "$DP/secdp.h")" = 1 ] && grep -qE '^#define SECDP_HDCP_DISABLE' "$DP/secdp.h" || { echo "ERRO: rode antes o s9-kpatch5.sh (SECDP_HDCP_DISABLE não está ativo)"; exit 1; }
[ -f "$KORIG" ] || KORIG=""
cp -a "$O/arch/arm64/boot/Image.gz-dtb" "$OUTD/Image.gz-dtb.prev"
[ -f "$DDO" ] && cp -a "$DDO" "$OUTD/dp_display.o.prev" || true

echo "== chroot Jammy"
$NS /bin/bash -c 'head -2 /etc/os-release; make --version | head -1; gcc --version | head -1'

echo "== compilando no chroot Jammy (incremental: secdp.h recompila os dp/*.o, uns 3 a 6 min; log em $OUTD/build.log)"
$NS /bin/bash -c "
set -e
export ARCH=arm64 CROSS_COMPILE=aarch64-linux-android- CROSS_COMPILE_ARM32=arm-linux-androideabi-
export PATH=$D/aarch64-linux-android-4.9/bin:\$PATH
cd $KS
make O=$O -j$(nproc) </dev/null
" > "$OUTD/build.log" 2>&1 || { tail -40 "$OUTD/build.log"; echo "ERRO NA COMPILAÇÃO"; exit 1; }
grep -E "dp/dp_display|dp/dp_drm|error|Error" "$OUTD/build.log" | tail -10 || true
grep -q 'msm/dp/dp_display' "$OUTD/build.log" || { echo "ERRO: dp_display.c não foi recompilado (secdp.h não disparou o rebuild)"; exit 1; }
NEWK=$O/arch/arm64/boot/Image.gz-dtb
ls -l "$NEWK"
cmp -s "$NEWK" "$OUTD/Image.gz-dtb.prev" && { echo "ERRO: o kernel não mudou em relação ao v4"; exit 1; }
$NM "$DPO" | grep -E "s9_uw|drm_cvt_mode" || { echo "ERRO: símbolos S9 ausentes no dp_drm.o"; exit 1; }
strings -a "$DDO" | grep -q 'skip hdcp' || { echo "ERRO: dp_display.o não contém 'skip hdcp' (SECDP_HDCP_DISABLE não entrou)"; exit 1; }

echo "== montando o boot (só troca o kernel)"
python3 "$UB" --boot_img "$LIVE" --out "$OUTD/live-unpack" --format=mkbootimg > "$OUTD/mkbootimg-args.txt"
python3 - "$OUTD" "$NEWK" "$MK" "$LIVE" <<'PY'
import shlex, subprocess, sys, pathlib, struct
outd = pathlib.Path(sys.argv[1]); newk = pathlib.Path(sys.argv[2]); mk = sys.argv[3]; live = pathlib.Path(sys.argv[4])
args = shlex.split((outd/'mkbootimg-args.txt').read_text())
i = args.index('--kernel'); args[i + 1] = str(newk)
raw = outd/'boot-raw.img'
subprocess.run(['python3', mk] + args + ['-o', str(raw)], check=True)
PAGE = 4096
al = lambda n: (n + PAGE - 1) // PAGE * PAGE
oldk = outd/'live-unpack'/'kernel'
ld = live.read_bytes(); nd = raw.read_bytes()
marker = b'SEANDROIDENFORCE'
lo = ld.rfind(marker)
assert lo >= 0, 'marcador nao encontrado no boot ao vivo'
exp = lo + al(newk.stat().st_size) - al(oldk.stat().st_size)
assert len(nd) == exp, ('layout difere do original', len(nd), exp)
nd += marker
assert len(nd) <= 64 * 1024 * 1024
nd = nd.ljust(64 * 1024 * 1024, b'\0')
# cabecalho do boot ao vivo (preserva second_addr etc.), trocando so kernel_size e id
H = 1632
hdr = bytearray(ld[:H])
struct.pack_into('<I', hdr, 8, struct.unpack_from('<I', nd, 8)[0])
hdr[576:608] = nd[576:608]
assert nd[H:4096] == ld[H:4096], 'bytes apos o cabecalho na pagina 0 diferem'
out = bytes(hdr) + nd[H:]
assert len(out) == len(nd) == 64 * 1024 * 1024
(outd/'boot-ultrawide-v5.img').write_bytes(out)
raw.unlink()
print('imagem:', outd/'boot-ultrawide-v5.img', len(out), 'bytes')
PY

echo "== verificação completa"
cat > "$OUTD/verify.py" <<'PY3'
import struct, sys, hashlib, pathlib, shlex, subprocess, tempfile, zlib
LIVE, NEW, NEWK, KORIG, REF, UB, NM, DPO, PREVK, V4IMG = sys.argv[1:11]
EXPECT = 'a27701c0b70944aecbb9e9ccf609705421a5fd016d7628b10e69ae5ec0ceb641'
fail = []
def ok(c, msg):
    print(('OK    ' if c else 'FALHA ') + msg)
    if not c: fail.append(msg)
rd = lambda p: pathlib.Path(p).read_bytes()
live, new, nkern, korig, ref, prevk = map(rd, (LIVE, NEW, NEWK, KORIG, REF, PREVK))
ok(hashlib.sha256(live).hexdigest() == EXPECT, 'sha256 do backup ao vivo = a27701c0...ceb641')
ok(live == ref, 'backup ao vivo == boot-s9root-expanded-v2.img (byte a byte)')
ok(len(live) == len(new) == 64 * 1024 * 1024, 'ambos com 64 MiB')
print('sha256 do boot novo:', hashlib.sha256(new).hexdigest())
H = struct.Struct('<8s10I16s512s32s1024s')
N = ['magic','kernel_size','kernel_addr','ramdisk_size','ramdisk_addr','second_size','second_addr','tags_addr','page_size','header_version','os_version','name','cmdline','id','extra_cmdline']
hl = dict(zip(N, H.unpack_from(live, 0))); hn = dict(zip(N, H.unpack_from(new, 0)))
print('-- cabecalho: campos que diferem (ao vivo | novo)')
bad = []
for k in N:
    a, b = hl[k], hn[k]
    if a == b: continue
    if isinstance(a, bytes): print('   %s: DIFERE' % k)
    else: print('   %s: %#x | %#x' % (k, a, b))
    if k not in ('kernel_size', 'id'): bad.append(k)
ok(not bad, 'cabecalho identico exceto kernel_size e id' + ((' (diferem: %s)' % bad) if bad else ''))
ok(hn['second_addr'] == hl['second_addr'] == 0xf00000, 'second_addr preservado (0xf00000)')
P = hl['page_size']
al = lambda n: (n + P - 1) // P * P
def sect(img, h):
    ks, rs = h['kernel_size'], h['ramdisk_size']
    ro = P + al(ks)
    return img[P:P + ks], img[ro:ro + rs], ro + al(rs)
lk, lr, lend = sect(live, hl); nk, nr, nend = sect(new, hn)
ok(lk == korig, 'kernel do boot ao vivo == kernel original de referencia')
ok(nk == nkern, 'kernel do boot novo == Image.gz-dtb recem-compilado')
ok(nk != lk, 'kernel novo difere do original')
ok(nkern != prevk, 'kernel novo difere do v4 (Image.gz-dtb.prev)')
ok(nr == lr, 'ramdisk novo == ramdisk ao vivo (byte a byte)')
M = b'SEANDROIDENFORCE'
ok(live[lend:lend + 16] == M, 'ao vivo: SEANDROIDENFORCE logo apos a imagem')
ok(new[nend:nend + 16] == M, 'novo: SEANDROIDENFORCE logo apos a imagem')
tl, tn = live[lend + 16:], new[nend + 16:]
print('-- info: residuo nao-zero apos o marcador ao vivo: %d bytes; AVBf: %s' % (len(tl) - tl.count(0), live[-64:-60] == b'AVBf'))
ok(tn.count(0) == len(tn), 'novo: so zeros depois do marcador')
def targs(p):
    d = tempfile.mkdtemp(prefix='bootv-')
    out = subprocess.run(['python3', '-I', UB, '--boot_img', p, '--out', d, '--format=mkbootimg'], capture_output=True, text=True, check=True).stdout
    t = shlex.split(out)
    for i, x in enumerate(t):
        if x in ('--kernel', '--ramdisk'): t[i + 1] = 'X'
    return t
ok(targs(LIVE) == targs(NEW), 'parametros do mkbootimg identicos')
def gz(b):
    o = zlib.decompressobj(31); img = o.decompress(b); return len(img), o.unused_data
li, lu = gz(korig); ni, nu = gz(nkern); pi, pu = gz(prevk)
print('-- Image descompactada: original %d, v4 %d, v5 %d (v5 vs v4: %+d); DTBs anexados: %d | %d | %d bytes' % (li, pi, ni, ni - pi, len(lu), len(pu), len(nu)))
ok(lu[:4] == b'\xd0\x0d\xfe\xed' and nu[:4] == b'\xd0\x0d\xfe\xed', 'DTBs anexados comecam com d00dfeed')
ok(len(lu) == len(nu), 'tamanho dos DTBs anexados igual ao original')
ok(abs(ni - pi) < 65536, 'v5 vs v4: diferenca de tamanho pequena (<64 KiB), como esperado de uma chave de compilacao')
nm = subprocess.run([NM, DPO], capture_output=True, text=True).stdout
ok(' drm_cvt_mode' in nm, 'dp_drm.o referencia drm_cvt_mode')
ok('s9_uw_hz' in nm, 'dp_drm.o contem o parametro s9_uw_hz')
if V4IMG != '-' and pathlib.Path(V4IMG).exists():
    v4 = rd(V4IMG)
    hv = dict(zip(N, H.unpack_from(v4, 0)))
    ok(v4[P + al(hv['kernel_size']):][:hv['ramdisk_size']] == nr, 'ramdisk do v5 == ramdisk do v4 (byte a byte)')
    print('-- info: sha256 do v4 gravado hoje:', hashlib.sha256(v4).hexdigest())
print()
if fail:
    print('RESULTADO: REPROVADO (%d falha(s))' % len(fail)); sys.exit(1)
print('RESULTADO: APROVADO')
PY3
python3 -I "$OUTD/verify.py" "$LIVE" "$OUTD/boot-ultrawide-v5.img" "$NEWK" "${KORIG:-$OUTD/live-unpack/kernel}" "$REF" "$UB" "$NM" "$DPO" "$OUTD/Image.gz-dtb.prev" "${V4IMG:--}"
chown -R "$U":"$U" "$OUTD"
echo
sha256sum "$OUTD/boot-ultrawide-v5.img"
echo "PRONTO: $OUTD/boot-ultrawide-v5.img (NÃO gravado no celular)"
echo "Cole este log de volta; o sha256 acima só entra na lista de gravação depois que você aprovar."
