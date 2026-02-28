# IBM Power and IBM Fusion HCI Demo — Heterogeneous OCP Hosted Control Plane

This solution demonstrates a **true heterogeneous workload deployment** on an OpenShift Hosted Control Plane (HCP) cluster with mixed-architecture worker nodes — IBM Power (ppc64le) and Intel (x86_64) — running on **IBM Fusion HCI**.

**No docker.io images are used.** All images come from:
- Red Hat Certified Operators catalog (`registry.connect.redhat.com`)
- Internal OCP image registry (`image-registry.openshift-image-registry.svc:5000`)
- Red Hat registry (`registry.access.redhat.com`, `registry.redhat.io`)

| Component | Architecture | Node Type | Workload | Image Source |
|-----------|-------------|-----------|----------|--------------|
| **PostgreSQL (Crunchy PGO)** | `x86_64` | Intel | Data persistence — managed by operator | `registry.connect.redhat.com` (Certified) |
| **Flask App Server** | `ppc64le` | IBM Power | Application logic + REST API + Web UI | OCP internal registry (S2I build) |

The Flask app server (running on Power) connects **cross-architecture** to PostgreSQL (running on Intel) via Kubernetes ClusterIP DNS — proving seamless heterogeneous workload communication on IBM Fusion HCI.

---

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│               OpenShift Hosted Control Plane (HCP)                   │
│                     Namespace: hetero-demo                            │
│                                                                       │
│  ┌──────────────────────────┐   ┌──────────────────────────────┐    │
│  │   IBM Power Worker Node  │   │   Intel Worker Node          │    │
│  │   (ppc64le)              │   │   (x86_64 / amd64)           │    │
│  │                          │   │                              │    │
│  │  ┌────────────────────┐  │   │  ┌──────────────────────┐   │    │
│  │  │  Flask App Server  │  │   │  │  Crunchy PGO         │   │    │
│  │  │  Python/Gunicorn   │  │   │  │  PostgresCluster      │   │    │
│  │  │  Port: 8080        │──┼───┼─▶│  Port: 5432          │   │    │
│  │  │  (S2I / UBI9)      │  │   │  │  (Certified Operator) │   │    │
│  │  └────────────────────┘  │   │  └──────────────────────┘   │    │
│  │         │                │   │                              │    │
│  │  flask-appserver-service  │   │  hetero-pgcluster-primary    │    │
│  └──────────────────────────┘   └──────────────────────────────┘    │
│         │                                                             │
│  OCP Route (TLS edge)                                                │
└─────────┼─────────────────────────────────────────────────────────── ┘
          │
    External Users
    https://flask-appserver-hetero-demo.<apps-domain>
```

---

## Image Sources (No docker.io)

| Component | Image | Source |
|-----------|-------|--------|
| Crunchy PGO Operator | `registry.connect.redhat.com/crunchydata/postgres-operator` | Red Hat Certified Operators |
| Crunchy PGO PostgreSQL | `registry.connect.redhat.com/crunchydata/crunchy-postgres` | Red Hat Certified Operators |
| Flask App Server | `image-registry.openshift-image-registry.svc:5000/hetero-demo/hetero-demo-app:latest` | OCP internal registry (S2I build) |
| S2I base image | `registry.redhat.io/ubi9/python-311:latest` | Red Hat registry (multi-arch) |
| Init container | `image-registry.openshift-image-registry.svc:5000/openshift/cli:latest` | OCP internal registry |
| Verify job | `image-registry.openshift-image-registry.svc:5000/openshift/cli:latest` | OCP internal registry |

---

## File Structure

```
hetero-hcp-demo/
├── README.md                        # This file
├── deploy.sh                        # One-shot deployment script
├── 00-namespace.yaml                # Namespace: hetero-demo
├── 01-node-labels-taints.sh         # Label/taint Intel and Power nodes
├── 02-postgres-operator.yaml        # Crunchy PGO OperatorGroup + Subscription
├── 03-postgres-cluster.yaml         # PostgresCluster CR → Intel (x86_64) node
├── 04-appserver-build.yaml          # OCP S2I BuildConfig + ImageStream
├── 06-appserver-deployment.yaml     # Flask App Server → Power (ppc64le) node
├── 07-appserver-service-route.yaml  # Service + OCP Route for Flask app
├── 08-network-policy.yaml           # NetworkPolicy for cross-arch traffic
├── 09-verify-job.yaml               # Verification job (OCP cli image)
└── app/
    ├── app.py                       # Flask application source
    ├── wsgi.py                      # WSGI entry point for gunicorn
    ├── requirements.txt             # Python dependencies (pinned)
    ├── Dockerfile                   # Dockerfile using registry.access.redhat.com/ubi9/python-311
    └── .gitignore                   # Python artifact exclusions
```

> **Note:** Files `02-postgres-secret.yaml`, `03-postgres-pvc.yaml`, `04-postgres-deployment.yaml`,
> and `05-postgres-service.yaml` are superseded by the Crunchy PGO operator approach.
> The operator manages secrets, PVCs, deployments, and services automatically.

---

## Prerequisites

- OpenShift HCP guest cluster (on IBM Fusion HCI or any OCP cluster) with:
  - At least **1 Intel (x86_64)** worker node
  - At least **1 IBM Power (ppc64le)** worker node
- `oc` CLI logged in to the HCP guest cluster
- Access to the Red Hat Certified Operators catalog (`certified-operators` CatalogSource)
- Internal OCP image registry accessible (default in OCP clusters)
- `git` CLI (for cloning this repo)

---

## Quick Start — One-Shot Deployment

```bash
# Clone the repo
git clone https://github.com/ganshug/heterogeneous-ocp-demo.git
cd heterogeneous-ocp-demo

# Log in to your OCP HCP cluster
oc login <api-url> --token=<token>

# Label your nodes (edit the script first — set INTEL_NODE and POWER_NODE)
vi 01-node-labels-taints.sh
bash 01-node-labels-taints.sh

# Deploy everything
bash deploy.sh
```

---

## Step-by-Step Deployment

### Step 1 — Label the nodes

Find your node names:
```bash
oc get nodes -o wide
```

Edit `01-node-labels-taints.sh` and set:
```bash
INTEL_NODE="<your-intel-node-hostname>"
POWER_NODE="<your-power-node-hostname>"
```

Run the labeling script:
```bash
bash 01-node-labels-taints.sh
```

Verify labels:
```bash
oc get nodes --show-labels | grep workload-type
```

---

### Step 2 — Create namespace and install Crunchy Postgres Operator

```bash
# Create namespace
oc apply -f 00-namespace.yaml

# Install the operator (OperatorGroup + Subscription from Red Hat Certified catalog)
oc apply -f 02-postgres-operator.yaml

# Wait for the operator to be ready (STATUS = Succeeded)
oc get csv -n hetero-demo -w
```

---

### Step 3 — Deploy PostgresCluster on Intel node

```bash
oc apply -f 03-postgres-cluster.yaml

# Watch the cluster come up
oc get postgrescluster -n hetero-demo -w

# Check pods (should land on Intel node)
oc get pods -n hetero-demo -l postgres-operator.crunchydata.com/cluster=hetero-pgcluster -o wide
```

The operator automatically creates:
- **Secret** `hetero-pgcluster-pguser-appuser` — DB credentials (user, password, host, port, dbname, uri)
- **Service** `hetero-pgcluster-primary` — ClusterIP on port 5432
- **PVC** — 10Gi data volume on Intel node
- **PVC** — 10Gi pgBackRest backup volume on Intel node

---

### Step 4 — Build the Flask App Server (S2I on Power node)

The build runs **on the Power node** using the Red Hat UBI9 Python 3.11 image from `registry.redhat.io`.
No docker.io credentials needed.

```bash
# Create the BuildConfig and ImageStream
oc apply -f 04-appserver-build.yaml

# Start the S2I build (uploads app/ directory to the cluster)
# The build pod is pinned to the ppc64le node via nodeSelector
oc start-build hetero-demo-app --from-dir=./app/ --follow -n hetero-demo
```

The built image is stored in the internal OCP registry:
`image-registry.openshift-image-registry.svc:5000/hetero-demo/hetero-demo-app:latest`

To rebuild after code changes:
```bash
oc start-build hetero-demo-app --from-dir=./app/ --follow --wait -n hetero-demo
oc rollout restart deployment/flask-appserver -n hetero-demo
oc rollout status deployment/flask-appserver -n hetero-demo
```

---

### Step 5 — Deploy Flask App Server on Power node

```bash
oc apply -f 06-appserver-deployment.yaml
oc apply -f 07-appserver-service-route.yaml
oc apply -f 08-network-policy.yaml

# Wait for rollout
oc rollout status deployment/flask-appserver -n hetero-demo
```

---

### Step 6 — Verify deployment

```bash
# Check pod placement
oc get pods -n hetero-demo -o wide
```

Expected output:
```
NAME                                    READY  STATUS   NODE                                        ...
hetero-pgcluster-pginstance-xxxx-0      4/4    Running  <your-intel-node-hostname>   ...
hetero-pgcluster-pgbouncer-xxxx         2/2    Running  <your-intel-node-hostname>   ...
flask-appserver-xxxx                    1/1    Running  <your-power-node-hostname>   ...
```

Confirm architectures:
```bash
# PostgreSQL pod — should show x86_64
oc exec -n hetero-demo \
  $(oc get pod -n hetero-demo -l postgres-operator.crunchydata.com/cluster=hetero-pgcluster -o name | head -1) \
  -- uname -m
# Expected: x86_64

# Flask app server pod — should show ppc64le
oc exec -n hetero-demo deploy/flask-appserver -- uname -m
# Expected: ppc64le
```

---

### Step 7 — Test the application

Get the Route URL:
```bash
ROUTE=$(oc get route flask-appserver-route -n hetero-demo -o jsonpath='{.spec.host}')
echo "App URL: https://$ROUTE"
```

Open the browser UI:
```
https://<ROUTE>/
```

Test the REST API:
```bash
# Health check
curl -sk https://$ROUTE/health

# Readiness check (includes DB connectivity)
curl -sk https://$ROUTE/ready

# Show architecture info (Power app → Intel DB via Crunchy PGO)
curl -sk https://$ROUTE/arch | python3 -m json.tool

# Create an inventory item (written from Power node to Intel PostgreSQL)
curl -sk -X POST https://$ROUTE/items \
  -H 'Content-Type: application/json' \
  -d '{"name":"fusion-hci-item","description":"Cross-arch write: IBM Power → Intel PostgreSQL (Crunchy PGO)"}'

# List all inventory items
curl -sk https://$ROUTE/items | python3 -m json.tool

# Get a single item
curl -sk https://$ROUTE/items/1 | python3 -m json.tool

# Update an item
curl -sk -X PUT https://$ROUTE/items/1 \
  -H 'Content-Type: application/json' \
  -d '{"name":"updated-item","description":"Updated via PUT"}'

# Delete an item
curl -sk -X DELETE https://$ROUTE/items/1
```

Expected `/arch` response:
```json
{
  "heterogeneous_demo": {
    "app_server": {
      "role": "Application Server + Web UI",
      "architecture": "ppc64le",
      "arch_label": "ppc64le (IBM Power)",
      "node": "<your-power-node-hostname>"
    },
    "database": {
      "role": "Database Server (Crunchy PGO)",
      "architecture": "x86_64 (Intel)",
      "host": "hetero-pgcluster-primary.hetero-demo.svc.cluster.local",
      "connected": true,
      "postgres_version": "PostgreSQL 16.x ..."
    }
  }
}
```

---

## Local Development (without OCP)

You can run the Flask app locally against a local PostgreSQL instance:

```bash
cd app/

# Create a virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Set environment variables
export DATABASE_URL="postgresql://appuser:changeme@localhost:5432/appdb"

# Run with gunicorn
gunicorn --bind 0.0.0.0:8080 --workers 2 --timeout 60 wsgi:application

# Or run with Flask dev server
python app.py
```

---

## Build the Container Image Locally (podman/docker)

```bash
cd app/

# Build for ppc64le (IBM Power)
podman build \
  --platform linux/ppc64le \
  -t hetero-demo-app:latest \
  .

# Build for x86_64 (Intel) — for local testing
podman build \
  --platform linux/amd64 \
  -t hetero-demo-app:latest \
  .

# Push to OCP internal registry (when logged in)
REGISTRY=$(oc registry info)
podman build \
  --platform linux/ppc64le \
  -t ${REGISTRY}/hetero-demo/hetero-demo-app:latest \
  --push .
```

---

## How Workload Placement Works

### Node Affinity (Hard Placement)

**PostgresCluster instances → Intel node:**
```yaml
affinity:
  nodeAffinity:
    requiredDuringSchedulingIgnoredDuringExecution:
      nodeSelectorTerms:
        - matchExpressions:
            - key: kubernetes.io/arch
              operator: In
              values: [amd64]
            - key: workload-type
              operator: In
              values: [database]
```

**Flask App Server → Power node:**
```yaml
affinity:
  nodeAffinity:
    requiredDuringSchedulingIgnoredDuringExecution:
      nodeSelectorTerms:
        - matchExpressions:
            - key: kubernetes.io/arch
              operator: In
              values: [ppc64le]
            - key: workload-type
              operator: In
              values: [appserver]
```

**S2I Build → Power node:**
```yaml
nodeSelector:
  kubernetes.io/arch: ppc64le
```

**pgBackRest backup jobs → Intel node:**
```yaml
backups:
  pgbackrest:
    jobs:
      affinity:
        nodeAffinity:
          requiredDuringSchedulingIgnoredDuringExecution:
            nodeSelectorTerms:
              - matchExpressions:
                  - key: kubernetes.io/arch
                    operator: In
                    values: [amd64]
```

---

## API Reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | Browser UI — inventory management |
| GET | `/health` | Liveness probe |
| GET | `/ready` | Readiness probe (checks DB) |
| GET | `/arch` | **Cross-arch info** — shows Power app + Intel DB details |
| GET | `/items` | List all inventory items from PostgreSQL |
| POST | `/items` | Create item `{"name":"...", "description":"..."}` |
| GET | `/items/<id>` | Get a single item by ID |
| PUT | `/items/<id>` | Update item `{"name":"...", "description":"..."}` |
| DELETE | `/items/<id>` | Delete item by ID |

---

## Cleanup

```bash
oc delete namespace hetero-demo
```

---

## Key Takeaways

1. **No docker.io credentials needed** — all images from Red Hat registries or internal OCP registry
2. **Crunchy Postgres Operator** (Red Hat Certified) manages the full PostgreSQL lifecycle — HA, backups, users, TLS
3. **OCP S2I BuildConfig** builds the ppc64le Flask image natively on the Power node using the internal Python UBI9 image
4. **`kubernetes.io/arch`** label is auto-applied by OCP — use it for architecture-based scheduling
5. **Node affinity** with `requiredDuringScheduling` enforces hard placement — pods will not start if no matching node exists
6. **ClusterIP DNS** works transparently across architectures — `hetero-pgcluster-primary.hetero-demo.svc.cluster.local` resolves correctly from the Power node
7. **Custom labels** (`workload-type`) give fine-grained control beyond just architecture
8. **pgBackRest backup jobs** must also be pinned to the correct architecture node — use `backups.pgbackrest.jobs.affinity` in the PostgresCluster CR
9. **wsgi.py** is the gunicorn entry point — the OCP S2I Python builder auto-detects it