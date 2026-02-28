# =============================================================================
# Multi-arch Dockerfile for the Flask App Server
#
# Base image: Red Hat UBI9 Python 3.11 from the internal OCP registry
# (No docker.io pull required)
#
# For OCP S2I builds, use 04-appserver-build.yaml (BuildConfig) instead.
# This Dockerfile is provided for local/podman builds using the Red Hat
# registry or the internal OCP registry.
#
# Build using internal OCP registry (when logged in via podman/docker):
#   REGISTRY=$(oc registry info)
#   podman build \
#     --platform linux/ppc64le \
#     -t ${REGISTRY}/hetero-demo/hetero-demo-app:latest \
#     --push .
# =============================================================================

# Red Hat UBI9 Python 3.11 — available for ppc64le (IBM Power) natively
# Pull from internal OCP registry (no docker.io needed):
#   image-registry.openshift-image-registry.svc:5000/openshift/python:3.11-ubi9
# Or from Red Hat registry directly:
#   registry.access.redhat.com/ubi9/python-311
FROM registry.access.redhat.com/ubi9/python-311

LABEL maintainer="hetero-hcp-demo"
LABEL description="Flask app server for heterogeneous HCP demo — runs on IBM Power (ppc64le)"
LABEL arch="ppc64le"

# Switch to root to install system packages, then drop back to 1001
USER root

WORKDIR /app

# Install libpq for psycopg2 (available in UBI9 repos — no docker.io needed)
RUN dnf install -y libpq-devel gcc python3-devel && \
    dnf clean all

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY app.py .
COPY wsgi.py .

# OpenShift: allow arbitrary UID to write to /app
RUN chown -R 1001:0 /app && chmod -R g=u /app

USER 1001

EXPOSE 8080

# Use gunicorn for production — wsgi.py is the entry point
# --workers 2  : two worker processes (tune to available CPU)
# --timeout 60 : kill workers that take > 60s (prevents hung DB connections)
# --access-logfile - : log requests to stdout (visible via `oc logs`)
CMD ["gunicorn", \
     "--bind", "0.0.0.0:8080", \
     "--workers", "2", \
     "--timeout", "60", \
     "--access-logfile", "-", \
     "wsgi:application"]