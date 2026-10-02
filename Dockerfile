# ============================================================
# IBM Cloud Terraform DriftGuard AI — Dockerfile
#
# Build: docker build -t driftguard-ai .
# Run:   docker run --env-file .env -p 8080:8080 driftguard-ai
#
# Security:
# - Non-root user (uid 1001)
# - Red Hat UBI minimal base image (as required by IBM security policy)
# - Terraform CLI installed from HashiCorp package
# - No IBM Cloud CLI (not required for drift detection)
# ============================================================

# ── Stage 1: Terraform downloader ──────────────────────────────────────
FROM registry.redhat.io/ubi9/ubi-minimal:latest AS terraform-download

# Install unzip for Terraform binary extraction
RUN microdnf install -y unzip curl && microdnf clean all

# Download and verify Terraform
ARG TERRAFORM_VERSION=1.9.8
ARG TARGETARCH=amd64

RUN curl -fsSL \
    "https://releases.hashicorp.com/terraform/${TERRAFORM_VERSION}/terraform_${TERRAFORM_VERSION}_linux_${TARGETARCH}.zip" \
    -o /tmp/terraform.zip && \
    unzip /tmp/terraform.zip -d /tmp/terraform-bin && \
    chmod +x /tmp/terraform-bin/terraform && \
    /tmp/terraform-bin/terraform version

# ── Stage 2: Python application ─────────────────────────────────────────
FROM registry.redhat.io/ubi9/python-312-minimal:latest

# Metadata
LABEL maintainer="IBM Cloud DriftGuard AI" \
      description="IBM Cloud Terraform DriftGuard AI — Drift detection and AI analysis" \
      version="0.1.0"

# Security: disable pip version check and upgrade prompts
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    CHECKPOINT_DISABLE=1 \
    TF_IN_AUTOMATION=1

# Create non-root user
RUN useradd -m -u 1001 -s /bin/bash driftguard

# Install Terraform from stage 1
COPY --from=terraform-download /tmp/terraform-bin/terraform /usr/local/bin/terraform

# Set up application directory
WORKDIR /app

# Install Python dependencies first (layer cache optimization)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY --chown=driftguard:driftguard app/ ./app/
COPY --chown=driftguard:driftguard terraform/ ./terraform/
COPY --chown=driftguard:driftguard scripts/ ./scripts/

# Create state directory
RUN mkdir -p /app/.driftguard/state && \
    chown -R driftguard:driftguard /app/.driftguard

# Switch to non-root user
USER 1001

# Verify terraform is accessible
RUN terraform version

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health')" || exit 1

EXPOSE 8080

# Run with uvicorn on localhost only
CMD ["python3", "-m", "uvicorn", "app.main:app", \
     "--host", "127.0.0.1", \
     "--port", "8080", \
     "--log-config", "/dev/null"]
