#!/usr/bin/env bash
# s9-kpatch5.sh: kernel v5 = v4 + `#define SECDP_HDCP_DISABLE` em secdp.h (nos DOIS trees, como o kpatch4). Sem sudo. Faz backup antes.
# Efeito: dp_display.c:2237 passa a compilar `pr_info("skip hdcp")` em vez de agendar hdcp_start_work (único ponto que inicia o HDCP),
# acabando com o laço de ~2,7 falhas/s (hdcp_tz_lib ~24% de um núcleo). Reversível: restaurar o backup e recompilar.
# NÃO compila nada e NÃO grava nada no celular.
set -euo pipefail
B=${S9_PROJ:-$HOME/s9-ubuntu2404-kernel}
TS=$(date +%Y%m%d-%H%M%S)
for pair in build:$B/workdir/downloads/kernel-source repo:$B/kernel-source; do
  L=${pair%%:*}; T=${pair#*:}
  F=$T/drivers/gpu/drm/msm/dp/secdp.h
  [ -f "$F" ] || { echo "ERRO: $F não existe"; exit 1; }
  mkdir -p "$B/workdir/backups-kernel-src/$TS/$L"
  cp -a "$F" "$B/workdir/backups-kernel-src/$TS/$L/secdp.h"
  python3 - "$F" <<'PY'
import sys
p = sys.argv[1]
s = open(p).read()
if 'S9-HDCP-V5' in s:
    print('ja aplicado (V5); nada alterado'); sys.exit(0)
old = '/*#define SECDP_HDCP_DISABLE*/\n'
new = ('#define SECDP_HDCP_DISABLE\t\t\t/* S9-HDCP-V5: sem HDCP no DP; o TrustZone nunca autentica e o laco de '
       'reautenticacao (~2,7 falhas/s) custava ~24%% de um nucleo */\n') % ()
if s.count(old) != 1:
    sys.exit('ERRO: linha %r aparece %d vezes; nada alterado' % (old.strip(), s.count(old)))
for need in ('#define SECDP_WIDE_32_9_SUPPORT', '#define SECDP_HIGH_REFRESH_SUPPORT'):
    if need not in s:
        sys.exit('ERRO: %s ausente (secdp.h nao esta no estado v4); nada alterado' % need)
s = s.replace(old, new)
if s.count('S9-HDCP-V5') != 1:
    sys.exit('ERRO: marcador inesperado; nada gravado')
open(p, 'w').write(s)
print('ok: aplicado em', p)
PY
  echo "== $L: diff"
  diff -u "$B/workdir/backups-kernel-src/$TS/$L/secdp.h" "$F" || true
done
echo "backups em $B/workdir/backups-kernel-src/$TS"
