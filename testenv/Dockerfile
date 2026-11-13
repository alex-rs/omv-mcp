FROM debian:trixie-slim

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        qemu-system-x86 qemu-utils cloud-image-utils openssh-client openssl \
        curl ca-certificates jq python3 procps \
    && rm -rf /var/lib/apt/lists/*

COPY . /testenv/
COPY run-vm.sh build.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/run-vm.sh /usr/local/bin/build.sh

WORKDIR /state
VOLUME ["/state"]
ENTRYPOINT ["/usr/local/bin/run-vm.sh"]
