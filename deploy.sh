#!/bin/bash
# =============================================================================
# deploy.sh — Full deployment script for the Heterogeneous HCP Demo
#
# Architecture:
#   - Database : Crunchy Postgres Operator (PGO v5) — Red Hat Certified catalog
#                PostgresCluster CR on Intel (x86_64) node
#                NO docker.io images — all from registry.connect.redhat.com
#   - App Server: Flask/Python — built via OCP S2I BuildConfig
#                 Base image: openshift/python:3.11-ubi9 (internal OCP registry)
#                 Runs on IBM Power (ppc64le) node
#
# Prerequisites:
#   - oc CLI logged in to your HCP guest cluster
#   - Nodes labeled with workload-type=database (Intel) and workload-type=appserver (Power)
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
info "Step 1/7: Creating namespace '$NAMESPACE'..."
oc apply -f "${SCRIPT_DIR}/00-namespace.yaml"
success "Namespace ready."

# ---- Step 2: Node labels ----------------------------------------------------
info "Step 2/7: Node labeling check..."
warn "Ensure nodes are labeled before proceeding."
warn "If not done yet, run: bash 01-node-labels-taints.sh"
echo ""
info "Current nodes and architectures:"
oc get nodes -o custom-columns='NAME:.metadata.name,ARCH:.status.nodeInfo.architecture,STATUS:.status.conditions[-1].type,WORKLOAD:.metadata.labels.workload-type' 2>/dev/null || true
echo ""

# ---- Step 3: Install Crunchy Postgres Operator ------------------------------
info "Step 3/7: Installing Crunchy Postgres Operator (PGO v5) from Red Hat Certified catalog..."
info "  No docker.io images — operator images from registry.connect.redhat.com"
oc apply -f "${SCRIPT_DIR}/02-postgres-operator.yaml"

info "Waiting for Crunchy Postgres Operator CSV to succeed (up to 5 min)..."
timeout=300
elapsed=0
while true; do
  CSV=$(oc get csv -n "$NAMESPACE" --no-headers 2>/dev/null | grep -i "postgresoperator" | awk '{print $1}' || true)
  if [[ -n "$CSV" ]]; then
    PHASE=$(oc get csv "$CSV" -n "$NAMESPACE" -o jsonpath='{.status.phase}' 2>/dev/null || echo "")
    if [[ "$PHASE" == "Succeeded" ]]; then
      success "Crunchy Postgres Operator installed: $CSV"
      break
    fi
    info "  CSV phase: ${PHASE:-Pending} (${elapsed}s elapsed)..."
  else
    info "  Waiting for CSV to appear (${elapsed}s elapsed)..."
  fi
  sleep 10
  elapsed=$((elapsed + 10))
  if [[ $elapsed -ge $timeout ]]; then
    error "Timed out waiting for Crunchy Postgres Operator CSV to succeed."
  fi
done

# ---- Step 4: Deploy PostgresCluster (Intel node) ----------------------------
info "Step 4/7: Deploying PostgresCluster on Intel (x86_64) node..."
oc apply -f "${SCRIPT_DIR}/03-postgres-cluster.yaml"

info "Waiting for PostgresCluster to be ready (up to 5 min)..."
timeout=300
elapsed=0
while true; do
  READY=$(oc get postgrescluster hetero-pgcluster -n "$NAMESPACE" \
    -o jsonpath='{.status.conditions[?(@.type=="ProxyAvailable")].status}' 2>/dev/null || echo "")
  INST_READY=$(oc get postgrescluster hetero-pgcluster -n "$NAMESPACE" \
    -o jsonpath='{.status.instances[0].readyReplicas}' 2>/dev/null || echo "0")
  if [[ "$INST_READY" == "1" ]]; then
    success "PostgresCluster hetero-pgcluster is ready (1 instance running)."
    break
  fi
  info "  Waiting for PostgresCluster instance (readyReplicas=${INST_READY:-0}, ${elapsed}s elapsed)..."
  sleep 10
  elapsed=$((elapsed + 10))
  if [[ $elapsed -ge $timeout ]]; then
    warn "Timed out waiting for PostgresCluster. Check: oc get postgrescluster -n $NAMESPACE"
    warn "Continuing deployment — app server will retry DB connection."
    break
  fi
done

# ---- Step 5: Build Flask App Server (S2I on Power node) ---------------------
info "Step 5/7: Building Flask App Server via OCP S2I (ppc64le, internal registry)..."
info "  Base image: openshift/python:3.11-ubi9 (internal OCP registry — no docker.io)"
oc apply -f "${SCRIPT_DIR}/04-appserver-build.yaml"

info "Starting S2I binary build from ${SCRIPT_DIR}/app/ ..."
oc start-build hetero-demo-app \
  --from-dir="${SCRIPT_DIR}/app/" \
  --follow \
  --wait \
  -n "$NAMESPACE"
success "Flask app server image built and pushed to internal ImageStream."

# ---- Step 6: Deploy Flask App Server (Power node) ---------------------------
info "Step 6/7: Deploying Flask App Server on Power (ppc64le) node..."
oc apply -f "${SCRIPT_DIR}/06-appserver-deployment.yaml"
oc apply -f "${SCRIPT_DIR}/07-appserver-service-route.yaml"
oc apply -f "${SCRIPT_DIR}/08-network-policy.yaml"
info "Waiting for Flask app server to be ready..."
oc rollout status deployment/flask-appserver -n "$NAMESPACE" --timeout=180s
success "Flask App Server is running on Power node."

# ---- Step 7: Verify deployment ----------------------------------------------
info "Step 7/7: Running verification job..."
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
echo -e "  App Server URL  : ${CYAN}https://${ROUTE_HOST}${NC}"
echo -e "  Architecture    : App Server on ${YELLOW}IBM Power (ppc64le)${NC}"
echo -e "                    Database on   ${YELLOW}Intel (x86_64) — Crunchy PGO${NC}"
echo ""
echo -e "  Images used (NO docker.io):"
echo -e "    DB Operator   : registry.connect.redhat.com/crunchydata/postgres-operator"
echo -e "    App Server    : image-registry.openshift-image-registry.svc:5000/hetero-demo/hetero-demo-app:latest"
echo -e "    Init container: image-registry.openshift-image-registry.svc:5000/openshift/cli:latest"
echo -e "    Verify job    : image-registry.openshift-image-registry.svc:5000/openshift/cli:latest"
echo ""
echo -e "  Test endpoints:"
echo -e "    GET  https://${ROUTE_HOST}/arch    — show cross-arch info"
echo -e "    GET  https://${ROUTE_HOST}/items   — list DB items"
echo -e "    POST https://${ROUTE_HOST}/items   — create DB item"
echo ""
info "Check pod placement:"
echo "    oc get pods -n $NAMESPACE -o wide"
echo ""
info "Check PostgresCluster status:"
echo "    oc get postgrescluster -n $NAMESPACE"
echo "    oc get pods -n $NAMESPACE -l postgres-operator.crunchydata.com/cluster=hetero-pgcluster -o wide"
echo ""
info "Tail app server logs:"
echo "    oc logs -f deploy/flask-appserver -n $NAMESPACE"
echo ""