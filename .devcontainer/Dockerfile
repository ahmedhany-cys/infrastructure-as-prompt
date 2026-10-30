FROM mcr.microsoft.com/devcontainers/python:1-3.12-bookworm

# The base image's Yarn apt source currently fails signature verification, which
# breaks every `apt-get update`. Yarn is not used here, so drop the source.
RUN rm -f /etc/apt/sources.list.d/yarn.list \
 && apt-get update \
 && apt-get install -y --no-install-recommends unzip \
 && rm -rf /var/lib/apt/lists/*

# Terraform from releases.hashicorp.com, verified against the published SHA-256 sums.
ARG TERRAFORM_VERSION=1.17.0
ARG TARGETARCH
RUN set -eux; \
    arch="${TARGETARCH:-amd64}"; \
    cd /tmp; \
    curl -fsSLO "https://releases.hashicorp.com/terraform/${TERRAFORM_VERSION}/terraform_${TERRAFORM_VERSION}_linux_${arch}.zip"; \
    curl -fsSLO "https://releases.hashicorp.com/terraform/${TERRAFORM_VERSION}/terraform_${TERRAFORM_VERSION}_SHA256SUMS"; \
    grep " terraform_${TERRAFORM_VERSION}_linux_${arch}.zip\$" "terraform_${TERRAFORM_VERSION}_SHA256SUMS" | sha256sum -c -; \
    unzip -o "terraform_${TERRAFORM_VERSION}_linux_${arch}.zip" terraform -d /usr/local/bin; \
    rm -f terraform_*; \
    terraform version
