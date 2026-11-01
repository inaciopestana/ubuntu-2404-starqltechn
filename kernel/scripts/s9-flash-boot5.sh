#!/usr/bin/env bash
# s9-flash-boot5.sh: grava o boot na sda20 SOMENTE no TWRP (adb em recovery), com sha256 aprovado e confirmação digitada GRAVAR.
# Uso: bash s9-flash-boot5.sh <imagem.img> [sha256-do-v5-aprovado-por-voce]
set -euo pipefail
IMG=${1:?uso: bash s9-flash-boot5.sh <imagem.img> [sha256-v5-aprovado]}
APPROVED=${2:-}
PART=/dev/block/platform/soc/1d84000.ufshc/by-name/boot
V4_SHA=6b84d1bd4d23ea3fa9c08143900a3d660bea1e2b48f171d3359172f9e2108c80
V3_SHA=3122a2f4dac41ac85cc0fa057b116d00ebe45d42354388fc51aa307972e7ff1b
LIVE_SHA=a27701c0b70944aecbb9e9ccf609705421a5fd016d7628b10e69ae5ec0ceb641
EMPTY=e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
[ -n "$APPROVED" ] && ! [[ "$APPROVED" =~ ^[0-9a-f]{64}$ ]] && { echo "ERRO: sha256 aprovado inválido"; exit 1; }
[ -f "$IMG" ] || { echo "ERRO: imagem não encontrada"; exit 1; }
SIZE=$(stat -c %s "$IMG"); [ "$SIZE" = 67108864 ] || { echo "ERRO: a imagem precisa ter 64 MiB (tem $SIZE)"; exit 1; }
SHA=$(sha256sum "$IMG" | cut -d' ' -f1)
case "$SHA" in
  "$V4_SHA")   WHAT="ROLLBACK para o BOOT v4 (ultrawide 60 Hz, com HDCP)";;
  "$V3_SHA")   WHAT="BOOT v3 (ultrawide, padrão 120 Hz)";;
  "$LIVE_SHA") WHAT="ROLLBACK (boot funcional original de 20/10)";;
  *) if [ -n "$APPROVED" ] && [ "$SHA" = "$APPROVED" ]; then WHAT="BOOT v5 (v4 + HDCP desligado), sha256 aprovado por você"
     else echo "ERRO: sha256 $SHA não está na lista de imagens aprovadas"; exit 1; fi;;
esac
echo "imagem: $IMG"; echo "tipo:   $WHAT"; echo "sha256: $SHA"

rsha() {  # $1 = comando remoto que escreve bytes no stdout
  local h
  h=$(adb exec-out "$1" 2>/dev/null | sha256sum | cut -d' ' -f1)
  if [ "$h" = "$EMPTY" ]; then h=$(adb shell "$1 | sha256sum" | tr -d '\r' | cut -d' ' -f1); fi
  echo "$h"
}

echo "== adb"
adb devices
STATE=$(adb get-state 2>/dev/null || true)
case "$STATE" in recovery) ;; *) echo "ERRO: aparelho não está no TWRP via adb (estado: '$STATE')"; exit 1;; esac
echo "estado: $STATE | dispositivo: $(adb shell getprop ro.product.device | tr -d '\r')"

echo "== partição de boot"
adb shell "ls -l '$PART'"
REAL=$(adb shell "readlink -f '$PART'" | tr -d '\r')
echo "resolve para: $REAL"
[ "$REAL" = /dev/block/sda20 ] || { echo "ERRO: a partição boot não é a sda20"; exit 1; }
SECT=$(adb shell "cat /sys/class/block/sda20/size" | tr -d '\r')
[ "$SECT" = 131072 ] || { echo "ERRO: tamanho da sda20 inesperado ($SECT setores)"; exit 1; }

echo "== enviando"
adb push "$IMG" /tmp/s9-boot.img
[ "$(rsha 'cat /tmp/s9-boot.img')" = "$SHA" ] || { echo "ERRO: arquivo corrompido no envio, nada foi gravado"; exit 1; }
echo "envio verificado"

read -r -p "Digite GRAVAR para escrever '$WHAT' na partição boot (sda20): " ANS
[ "$ANS" = GRAVAR ] || { echo "cancelado, nada foi gravado"; exit 1; }

echo "== gravando"
adb shell "dd if=/tmp/s9-boot.img of='$PART' bs=4M && sync"
echo "== conferindo a partição"
PSHA=$(rsha "dd if='$PART' bs=4M count=16 2>/dev/null")
echo "partição: $PSHA"
[ "$PSHA" = "$SHA" ] || { echo "FALHA: a partição NÃO bate com a imagem! Rode o rollback agora (v4 ou original)."; exit 1; }
echo "OK: gravado e verificado. Para reiniciar: adb reboot"
