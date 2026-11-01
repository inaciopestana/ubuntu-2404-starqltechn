#!/bin/bash
set -e

PROJ=$S9_WORK
ROOTFS=$PROJ/workdir/ubuntu2404-rootfs

mkdir -p "$ROOTFS"

echo "=== Ubuntu Noble ARM64: primeiro estágio ==="

debootstrap \
  --arch=arm64 \
  --foreign \
  --variant=minbase \
  noble \
  "$ROOTFS" \
  http://ports.ubuntu.com/ubuntu-ports

echo "=== Copiando QEMU ARM64 ==="

cp /usr/bin/qemu-aarch64-static \
   "$ROOTFS/usr/bin/"

echo "=== Segundo estágio ==="

chroot "$ROOTFS" \
  /usr/bin/qemu-aarch64-static \
  /debootstrap/debootstrap --second-stage

echo
echo "=== ROOTFS BASE CRIADO ==="
cat "$ROOTFS/etc/os-release"
