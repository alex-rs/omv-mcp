SHELL := /usr/bin/env bash
.DEFAULT_GOAL := check

.PHONY: install lint format typecheck test check docs \
	testenv-build testenv-provision testenv-up testenv-reset testenv-down \
	testenv-snapshot testenv-ssh testenv-destroy testenv-capture testenv-wait

install:
	uv sync --extra dev

lint:
	uv run ruff check .
	uv run ruff format --check .

format:
	uv run ruff format .

typecheck:
	uv run mypy src tests

test:
	uv run pytest

check: lint typecheck test

docs:
	uv run python scripts/gen_tools_doc.py

testenv-build:
	cd testenv && docker compose build && docker compose run --rm --entrypoint /usr/local/bin/build.sh omv-test
	cd testenv && docker compose run --rm --entrypoint /bin/chown omv-test -R "$$(id -u):$$(id -g)" /state

testenv-provision:
	cd testenv && test ! -e .state/base/PROVISIONED || { echo "already provisioned; use make testenv-destroy" >&2; exit 1; }
	$(MAKE) testenv-build
	cd testenv && PROVISION=1 docker compose up -d
	$(MAKE) testenv-wait
	uv run python -m testenv.seed
	cd testenv && ssh -p 2222 -i .state/id_ed25519 -o UserKnownHostsFile=.state/known_hosts -o StrictHostKeyChecking=yes root@127.0.0.1 'cat /root/versions.txt' > .state/versions.txt
	cd testenv && docker compose down
	cd testenv && touch .state/base/PROVISIONED

testenv-wait:
	cd testenv && for i in $$(seq 1 90); do ssh-keyscan -p 2222 127.0.0.1 > .state/known_hosts 2>/dev/null && test -s .state/known_hosts && break; sleep 2; done
	cd testenv && test -s .state/known_hosts
	cd testenv && for i in $$(seq 1 180); do ssh -p 2222 -i .state/id_ed25519 -o UserKnownHostsFile=.state/known_hosts -o StrictHostKeyChecking=yes -o ConnectTimeout=3 root@127.0.0.1 'test -f /var/lib/omv-test-provisioned && omv-rpc -u admin System noop "{}"' >/dev/null 2>&1 && exit 0; sleep 5; done; echo "test VM did not become ready" >&2; exit 1

testenv-up:
	cd testenv && test -f .state/base/PROVISIONED || { echo "run make testenv-provision first" >&2; exit 1; }
	cd testenv && mkdir -p .state/run && rm -f .state/run/*.qcow2
	cd testenv/.state/run && for d in os ssd1 ssd2 ssd3 hdd1 hdd2 hdd3 nvme1; do qemu-img create -f qcow2 -F qcow2 -b ../base/$$d.qcow2 $$d.qcow2; done
	cd testenv && docker compose up -d
	$(MAKE) testenv-wait

testenv-reset:
	$(MAKE) testenv-down
	rm -rf testenv/.state/run
	$(MAKE) testenv-up

testenv-down:
	cd testenv && docker compose down

testenv-snapshot:
	@echo "snapshot support: stop the VM, copy .state/base disks aside, then recreate overlays with testenv-up"

testenv-ssh:
	cd testenv && ssh -p 2222 -i .state/id_ed25519 -o UserKnownHostsFile=.state/known_hosts -o StrictHostKeyChecking=yes root@127.0.0.1

testenv-destroy:
	cd testenv && docker compose down || true
	rm -rf testenv/.state

testenv-capture:
	PYTHONPATH=. uv run python scripts/capture_omv_metadata.py
	PYTHONPATH=. uv run python scripts/capture_fixtures.py
