#!/usr/bin/env bash
set -euo pipefail

BASE=/state/base
mkdir -p "$BASE"

if [ ! -f "$BASE/debian-13-genericcloud-amd64.qcow2" ]; then
  curl -fL --retry 5 -o "$BASE/debian-13-genericcloud-amd64.qcow2.part" \
    https://cloud.debian.org/images/cloud/trixie/latest/debian-13-genericcloud-amd64.qcow2
  mv "$BASE/debian-13-genericcloud-amd64.qcow2.part" "$BASE/debian-13-genericcloud-amd64.qcow2"
fi
if [ ! -f "$BASE/SHA512SUMS" ]; then
  curl -fL --retry 5 -o "$BASE/SHA512SUMS" \
    https://cloud.debian.org/images/cloud/trixie/latest/SHA512SUMS
fi
grep 'debian-13-genericcloud-amd64.qcow2' "$BASE/SHA512SUMS" | (cd "$BASE" && sha512sum -c -)

if [ ! -f "$BASE/os.qcow2" ]; then
  (cd "$BASE" && qemu-img create -f qcow2 -F qcow2 -b debian-13-genericcloud-amd64.qcow2 os.qcow2 24G)
fi
for pair in ssd1:4G ssd2:4G ssd3:6G hdd1:6G hdd2:6G hdd3:8G nvme1:6G; do
  name=${pair%%:*}
  size=${pair##*:}
  [ -f "$BASE/$name.qcow2" ] || qemu-img create -f qcow2 "$BASE/$name.qcow2" "$size"
done

[ -f /state/id_ed25519 ] || ssh-keygen -q -t ed25519 -N '' -f /state/id_ed25519
[ -f /state/omv-admin.pass ] || openssl rand -base64 24 > /state/omv-admin.pass
[ -f /state/mfa-user.pass ] || openssl rand -base64 24 > /state/mfa-user.pass
chmod 0600 /state/id_ed25519 /state/omv-admin.pass /state/mfa-user.pass

python3 - "$BASE" <<'PY'
import pathlib
import sys

base = pathlib.Path(sys.argv[1])
pubkey = pathlib.Path('/state/id_ed25519.pub').read_text().strip()
password = pathlib.Path('/state/omv-admin.pass').read_text().strip()
script = pathlib.Path('/testenv/provision.sh').read_text()
indented = '\n'.join('      ' + line for line in script.splitlines())
template = pathlib.Path('/testenv/cloud-init.yaml.tmpl').read_text()
template = template.replace('__SSH_PUBKEY__', pubkey)
template = template.replace('__ADMIN_PASSWORD__', password)
template = template.replace('__PROVISION_SCRIPT__', indented)
pathlib.Path('/state/user-data').write_text(template)
pathlib.Path('/state/meta-data').write_text(
    'instance-id: omv-test-001\nlocal-hostname: omv-test\n'
)
PY

cloud-localds /state/seed.iso /state/user-data /state/meta-data
