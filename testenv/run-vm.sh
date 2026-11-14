#!/usr/bin/env bash
set -euo pipefail

if [ ! -e /dev/kvm ]; then
  echo "refusing: /dev/kvm is required; TCG fallback is disabled" >&2
  exit 1
fi

if [ "${PROVISION:-0}" = "1" ]; then
  DISKS=/state/base
else
  DISKS=/state/run
fi

mkdir -p "$DISKS"
if [ ! -f "$DISKS/os.qcow2" ]; then
  echo "missing $DISKS/os.qcow2" >&2
  exit 1
fi
if [ ! -f /state/seed.iso ]; then
  echo "missing /state/seed.iso" >&2
  exit 1
fi

touch /state/console.log
tail -n +1 -F /state/console.log &
exec qemu-system-x86_64 \
  -machine q35,accel=kvm \
  -cpu host \
  -m 4096 \
  -smp 2 \
  -drive if=none,id=os,file="$DISKS/os.qcow2",format=qcow2 \
  -device virtio-blk-pci,drive=os,bootindex=0 \
  -device ahci,id=ahci \
  -drive if=none,id=ssd1,file="$DISKS/ssd1.qcow2",format=qcow2 \
  -device ide-hd,drive=ssd1,bus=ahci.0,serial=OMVTESTSSD1,model=OMVSSD \
  -drive if=none,id=ssd2,file="$DISKS/ssd2.qcow2",format=qcow2 \
  -device ide-hd,drive=ssd2,bus=ahci.1,serial=OMVTESTSSD2,model=OMVSSD \
  -drive if=none,id=ssd3,file="$DISKS/ssd3.qcow2",format=qcow2 \
  -device ide-hd,drive=ssd3,bus=ahci.2,serial=OMVTESTSSD3,model=OMVSSD \
  -drive if=none,id=hdd1,file="$DISKS/hdd1.qcow2",format=qcow2 \
  -device ide-hd,drive=hdd1,bus=ahci.3,serial=OMVTESTHDD1,model=OMVHDD,rotation_rate=7200 \
  -drive if=none,id=hdd2,file="$DISKS/hdd2.qcow2",format=qcow2 \
  -device ide-hd,drive=hdd2,bus=ahci.4,serial=OMVTESTHDD2,model=OMVHDD,rotation_rate=7200 \
  -drive if=none,id=hdd3,file="$DISKS/hdd3.qcow2",format=qcow2 \
  -device ide-hd,drive=hdd3,bus=ahci.5,serial=OMVTESTHDD3,model=OMVHDD,rotation_rate=7200 \
  -drive if=none,id=nvme1,file="$DISKS/nvme1.qcow2",format=qcow2 \
  -device nvme,drive=nvme1,serial=OMVTESTNVME1 \
  -netdev user,id=net0,hostfwd=tcp:0.0.0.0:2222-:22,hostfwd=tcp:0.0.0.0:8080-:80 \
  -device virtio-net-pci,netdev=net0 \
  -drive file=/state/seed.iso,media=cdrom,readonly=on \
  -display none -monitor none -serial file:/state/console.log
