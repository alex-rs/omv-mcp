#!/usr/bin/env bash
set -euxo pipefail

export DEBIAN_FRONTEND=noninteractive
export LANG=C.UTF-8

systemctl enable --now systemd-resolved || true
if ! apt-get update; then
  iface=$(ip route show default | awk '{print $5; exit}')
  resolvectl dns "$iface" 10.0.2.3 || true
  systemctl restart systemd-resolved || true
  apt-get update
fi

install -d -m 0755 /etc/apt/keyrings
wget -qO /etc/apt/keyrings/openmediavault.asc https://packages.openmediavault.io/archive.key
cat > /etc/apt/sources.list.d/openmediavault.list <<'EOF'
deb [signed-by=/etc/apt/keyrings/openmediavault.asc] https://packages.openmediavault.org/public synchrony main
deb [signed-by=/etc/apt/keyrings/openmediavault.asc] https://packages.openmediavault.org/public synchrony partner
EOF
apt-get update

apt-get install -y --allow-downgrades --allow-change-held-packages --no-install-recommends \
  openmediavault

if ! omv-rpc -u admin System noop '{}' >/dev/null 2>&1; then
  omv-confdbadm populate || true
fi

wget -qO- https://github.com/OpenMediaVault-Plugin-Developers/packages/raw/master/install | bash

for _ in $(seq 1 30); do
  if omv-rpc -u admin omvextras set '{"docker":true}' >/dev/null 2>&1; then
    break
  fi
  sleep 2
done
omv-rpc -u admin omvextras set '{"docker":true}' || true
apt-get update

apt-get install -y --no-install-recommends \
  openmediavault-compose \
  openmediavault-cterm \
  openmediavault-mergerfs \
  openmediavault-snapraid \
  openmediavault-wireguard \
  openmediavault-writecache \
  openmediavault-sharerootfs \
  openmediavault-2fa-totp \
  docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

for _ in $(seq 1 60); do
  if omv-rpc -u admin System noop '{}' >/dev/null 2>&1; then
    break
  fi
  sleep 2
done
omv-rpc -u admin System noop '{}' >/dev/null

systemctl enable --now docker
for _ in $(seq 1 30); do
  docker info >/dev/null 2>&1 && break
  sleep 2
done

if ! id admin >/dev/null 2>&1; then
  useradd -r -m -s /bin/bash admin
fi
echo "admin:$(cat /root/omv-admin.pass)" | chpasswd
rm -f /root/omv-admin.pass

dpkg-query -W -f='${Package} ${Version}\n' 'openmediavault*' > /root/versions.txt
