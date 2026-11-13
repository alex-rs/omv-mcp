# Test VM

A disposable OpenMediaVault 8 VM runs inside Docker with QEMU/KVM. The only supported target is `127.0.0.1`, hostname `omv-test`.

## Ports

| Host | VM | Purpose |
|---|---|---|
| `127.0.0.1:2222` | 22 | SSH |
| `127.0.0.1:18080` | 80 | OMV web/RPC |

Port 18080 is used because 8080 is commonly occupied on developer machines. The integration guard accepts only loopback OMV targets on 8080, 8081 or 18080.

## Lifecycle

```sh
make testenv-build       # download Debian 13 cloud image, create disks and seed ISO
make testenv-provision   # install OMV 8, omv-extras, plugins; seed; snapshot base
make testenv-up          # boot overlays from the seeded base
make testenv-reset       # discard overlay writes and boot fresh
make testenv-down
make testenv-ssh
make testenv-capture     # refresh bundled schemas and fixtures
make testenv-destroy
```

State lives in `testenv/.state/` (gitignored): generated SSH key, OMV admin password, MFA test-user password, base disks, overlays, console log, `known_hosts`, `versions.txt`.

## Disks

The VM has a 24 GiB OS disk and seven data disks:

| Serial | Size | Role |
|---|---|---|
| `OMVTESTSSD1` | 4G | ext4 |
| `OMVTESTSSD2` | 4G | ext4 |
| `OMVTESTSSD3` | 6G | ext4 |
| `OMVTESTHDD1` | 6G | ext4 / mergerfs / SnapRAID data |
| `OMVTESTHDD2` | 6G | ext4 / mergerfs / SnapRAID data |
| `OMVTESTHDD3` | 8G | ext4 / mergerfs / SnapRAID parity |
| `OMVTESTNVME1` | 6G | ext4, emulated NVMe |

The seeded state has a `pool` mergerfs pool, a SnapRAID `main` array, nine shared folders, a compose file, users `tester` and `mfatester` (TOTP), writecache settings, SMART schedules and only the `ssh` module left dirty.

## Guards

`testenv/guard.py` refuses any SSH target other than `127.0.0.1:2222`, any HTTP target other than loopback ports 8080/8081/18080, and any OMV hostname other than `omv-test`. Integration tests abort before the first RPC if a guard fails.

## Secrets

Generated keys and passwords are in `testenv/.state/` and are never committed. Fixtures are captured through the redactor. Never add real NAS data to this repository.
