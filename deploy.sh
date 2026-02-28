#!/bin/bash
# =============================================================================
# deploy.sh — Full deployment script for the Heterogeneous HCP Demo
#
# Architecture (after swap):
#   - App Server : Flask/Python — built via OCP S2I BuildConfig
#                  Base image: registry.redhat.io/ubi9/python-311:latest
#                  Build pod pinned to Intel (amd64) node → produces amd64 image
#                  Runs on Intel (x86_64) node
#
#   - Database   : Direct PostgreSQL 16 deployment
#                  Image: registry.redhat.io/rhel9/postgresql-16:latest (multi-arch)
#                  Runs on IBM Power (ppc64le) node
#                  NO docker.io images — all from registry.redhat.io
#
# Cross-arch flow: Intel (x86_64) App Server → IBM Power (ppc64le) PostgreSQL
#
# Prerequisites:
#   - oc CLI logged in to your HCP guest cluster
#   - Nodes labeled:
#       Intel node  → workload-type=appserver
#       Power node  → workload-type=database
#     Run: bash 01-node-labels-taints.sh
#
# Usage:
#   bash deploy.sh
# =============================================================================

set -euo pipefail

NAMESPACE="hetero-demo"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ---- Colour helpers ---------------------------------------------------------
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
info()    { echo -e "${CYAN}[INFO]${NC}  $*"; }
success() { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error()   { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }

# ---- Preflight checks -------------------------------------------------------
info "Checking prerequisites..."
command -v oc >/dev/null 2>&1 || error "'oc' CLI not found. Please install and log in."
oc whoami      >/dev/null 2>&1 || error "Not logged in to OCP cluster. Run: oc login <api-url>"
success "Prerequisites OK. Logged in as: $(oc whoami)"

# ---- Step 1: Create namespace -----------------------------------------------
info "Step 1/6: Creating namespace '$NAMESPACE'..."
oc apply -f "${SCRIPT_DIR}/00-namespace.yaml"
success "Namespace ready."

# ---- Step 2: Node labels ----------------------------------------------------
info "Step 2/6: Node labeling check..."
warn "Ensure nodes are labeled before proceeding."
warn "If not done yet, run: bash 01-node-labels-taints.sh"
echo ""
info "Current nodes and architectures:"
oc get nodes -o custom-columns='NAME:.metadata.name,ARCH:.status.nodeInfo.architecture,STATUS:.status.conditions[-1].type,WORKLOAD:.metadata.labels.workload-type' 2>/dev/null || true
echo ""

# ---- Step 3: Deploy PostgreSQL on Power (ppc64le) node ----------------------
info "Step 3/6: Deploying PostgreSQL 16 on IBM Power (ppc64le) node..."
info "  Image: registry.redhat.io/rhel9/postgresql-16:latest (multi-arch, no docker.io)"
oc apply -f "${SCRIPT_DIR}/03-postgres-direct.yaml"

info "Waiting for PostgreSQL pod to be ready (up to 3 min)..."
timeout=180
elapsed=0
while true; do
  READY=$(oc get deployment hetero-postgres -n "$NAMESPACE" \
    -o jsonpath='{.status.readyReplicas}' 2>/dev/null || echo "0")
  if [[ "$READY" == "1" ]]; then
    success "PostgreSQL is ready on IBM Power node."
    break
  fi
  info "  Waiting for PostgreSQL (readyReplicas=${READY:-0}, ${elapsed}s elapsed)..."
  sleep 10
  elapsed=$((elapsed + 10))
  if [[ $elapsed -ge $timeout ]]; then
    warn "Timed out waiting for PostgreSQL. Check: oc get pods -n $NAMESPACE -l app=postgres -o wide"
    warn "Continuing deployment — app server will retry DB connection."
    break
  fi
done

# ---- Step 4: Build Flask App Server (S2I on Intel/amd64 node) ---------------
info "Step 4/6: Building Flask App Server via OCP S2I (amd64, internal registry)..."
info "  Base image: registry.redhat.io/ubi9/python-311:latest (no docker.io)"
info "  Build pod pinned to Intel (amd64) node → produces amd64 image"
oc apply -f "${SCRIPT_DIR}/04-appserver-build.yaml"

info "Starting S2I binary build from ${SCRIPT_DIR}/app/ ..."
oc start-build hetero-demo-app \
  --from-dir="${SCRIPT_DIR}/app/" \
  --follow \
  --wait \
  -n "$NAMESPACE"
success "Flask app server image built and pushed to internal ImageStream (amd64)."

# ---- Step 5: Deploy Flask App Server (Intel/amd64 node) ---------------------
info "Step 5/6: Deploying Flask App Server on Intel (x86_64) node..."
oc apply -f "${SCRIPT_DIR}/06-appserver-deployment.yaml"
oc apply -f "${SCRIPT_DIR}/07-appserver-service-route.yaml"
oc apply -f "${SCRIPT_DIR}/08-network-policy.yaml"
info "Waiting for Flask app server to be ready..."
oc rollout status deployment/flask-appserver -n "$NAMESPACE" --timeout=180s
success "Flask App Server is running on Intel (x86_64) node."

# ---- Step 6: Verify deployment ----------------------------------------------
info "Step 6/6: Running verification job..."
oc delete job hetero-verify -n "$NAMESPACE" --ignore-not-found=true
oc apply -f "${SCRIPT_DIR}/09-verify-job.yaml"
info "Waiting for verification job to complete..."
oc wait --for=condition=complete job/hetero-verify -n "$NAMESPACE" --timeout=120s
echo ""
info "Verification job logs:"
oc logs job/hetero-verify -n "$NAMESPACE"

# ---- Summary ----------------------------------------------------------------
echo ""
echo -e "${GREEN}============================================================${NC}"
echo -e "${GREEN}  Heterogeneous HCP Demo Deployed Successfully!${NC}"
echo -e "${GREEN}============================================================${NC}"
echo ""
ROUTE_HOST=$(oc get route flask-appserver-route -n "$NAMESPACE" -o jsonpath='{.spec.host}' 2>/dev/null || echo "<route-not-found>")
echo -e "  App URL         : ${CYAN}https://${ROUTE_HOST}${NC}"
echo -e "  Architecture    : App Server on ${YELLOW}Intel (x86_64 / amd64)${NC}"
echo -e "                    Database on   ${YELLOW}IBM Power (ppc64le)${NC}"
echo ""
echo -e "  Images used (NO docker.io):"
echo -e "    PostgreSQL    : registry.redhat.io/rhel9/postgresql-16:latest"
echo -e "    App Server    : image-registry.openshift-image-registry.svc:5000/hetero-demo/hetero-demo-app:latest"
echo -e "    S2I base      : registry.redhat.io/ubi9/python-311:latest"
echo -e "    Init container: image-registry.openshift-image-registry.svc:5000/openshift/cli:latest"
echo ""
echo -e "  Test endpoints:"
echo -e "    Browser UI   : https://${ROUTE_HOST}/"
echo -e "    GET  https://${ROUTE_HOST}/arch    — show cross-arch info (Intel app → Power DB)"
echo -e "    GET  https://${ROUTE_HOST}/items   — list DB items"
echo -e "    POST https://${ROUTE_HOST}/items   — create DB item"
echo ""
info "Check pod placement (Intel app + Power DB):"
echo "    oc get pods -n $NAMESPACE -o wide"
echo ""
info "Check PostgreSQL on Power node:"
echo "    oc get pods -n $NAMESPACE -l app=postgres -o wide"
echo "    oc logs -f deploy/hetero-postgres -n $NAMESPACE"
echo ""
info "Tail app server logs:"
echo "    oc logs -f deploy/flask-appserver -n $NAMESPACE"
echo ""
info "Rebuild app after code changes:"
echo "    oc start-build hetero-demo-app --from-dir=./app/ --follow --wait -n $NAMESPACE"
echo "    oc rollout restart deployment/flask-appserver -n $NAMESPACE"
echo ""