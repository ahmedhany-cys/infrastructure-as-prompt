# Backend: FastAPI + the Terraform CLI. Runs in simulation mode; no AWS
# credentials are present in the image.
FROM python:3.12-slim-bookworm

ARG TERRAFORM_VERSION=1.17.0
ARG TARGETARCH

RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl unzip \
 && rm -rf /var/lib/apt/lists/*

# Terraform from releases.hashicorp.com, verified against the published SHA-256 sums.
RUN set -eux; \
    arch="${TARGETARCH:-amd64}"; \
    cd /tmp; \
    curl -fsSLO "https://releases.hashicorp.com/terraform/${TERRAFORM_VERSION}/terraform_${TERRAFORM_VERSION}_linux_${arch}.zip"; \
    curl -fsSLO "https://releases.hashicorp.com/terraform/${TERRAFORM_VERSION}/terraform_${TERRAFORM_VERSION}_SHA256SUMS"; \
    grep " terraform_${TERRAFORM_VERSION}_linux_${arch}.zip\$" "terraform_${TERRAFORM_VERSION}_SHA256SUMS" | sha256sum -c -; \
    unzip -o "terraform_${TERRAFORM_VERSION}_linux_${arch}.zip" terraform -d /usr/local/bin; \
    rm -f terraform_*; \
    terraform version

WORKDIR /app/backend
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN useradd --create-home --uid 10001 iap \
 && mkdir -p var \
 && chown -R iap:iap var \
 && chmod +x docker/entrypoint.sh

USER iap
ENV PYTHONUNBUFFERED=1 \
    IAP_ENVIRONMENT=development \
    IAP_ALLOW_REAL_DEPLOY=false
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --start-period=20s --retries=6 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=2)"
ENTRYPOINT ["docker/entrypoint.sh"]
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
