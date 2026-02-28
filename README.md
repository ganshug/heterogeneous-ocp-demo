# IBM Power and IBM Fusion HCI Demo — Heterogeneous OCP Hosted Control Plane

This repository demonstrates **true heterogeneous workload deployments** on an OpenShift Hosted Control Plane (HCP) cluster with mixed-architecture worker nodes — Intel (x86_64) and IBM Power (ppc64le) — running on **IBM Fusion HCI**.

Two demos are available:

| Demo | Database | App | Repo |
|------|----------|-----|------|
| **[hetero-hcp-demo](#demo-1-postgresql-16-on-ibm-power--flask-on-intel)** | PostgreSQL 16 on IBM Power (ppc64le) | Flask inventory app on Intel (x86_64) | This repo |
| **[hetero-db2-demo](https://github.com/ganshug/heterogeneous-ecommerce-demo)** | IBM Db2 CE on IBM Power (ppc64le) | Flask e-commerce shopping cart on Intel (x86_64) | [heterogeneous-ecommerce-demo](https://github.com/ganshug/heterogeneous-ecommerce-demo) |

---

## Demo 1: PostgreSQL 16 on IBM Power + Flask on Intel

**No docker.io images are used.** All images come from:
- Red Hat registry (`registry.redhat.io`)
- Internal OCP image registry (`image-registry.openshift-image-registry.svc:5000`)

| Component | Architecture | Node Type | Workload | Image Source |
|-----------|-------------|-----------|----------|--------------|
| **Flask App Server** | `x86_64` | Intel | Application logic + REST API + Web UI | OCP internal registry (S2I build on amd64) |
| **PostgreSQL 16** | `ppc64le` | IBM Power | Data persistence | `registry.redhat.io/rhel9/postgresql-16` |

The Flask app server (running on Intel) connects **cross-architecture** to PostgreSQL (running on IBM Power) via Kubernetes ClusterIP DNS — proving seamless heterogeneous workload communication on IBM Fusion HCI.

---

### Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│               OpenShift Hosted Control Plane (HCP)                   │
│                     Namespace: hetero-demo                            │
│                                                                       │
│  ┌──────────────────────────────┐   ┌──────────────────────────┐    │
│  │   Intel Worker Node          │   │   IBM Power Worker Node  │    │
│  │   (x86_64 / amd64)           │   │   (ppc64le)              │    │
│  │                              │   │                          │    │
│  │  ┌──────────────────────┐   │   │  ┌────────────────────┐  │    │
│  │  │  Flask App Server    │   │   │  │  PostgreSQL 16     │  │    │
│  │  │  Python/Gunicorn     │───┼───┼─▶│  rhel9/postgresql  │  │    │
│  │  │  Port: 8080          │   │   │  │  Port: 5432        │  │    │
│  │  │  (S2I / UBI9 amd64)  │   │   │  │  (multi-arch)      │  │    │
│  │  └──────────────────────┘   │   │  └────────────────────┘  │    │
│  │         │                   │   │                          │    │
│  │  flask-appserver-service     │   │  hetero-postgres-service  │    │
│  └──────────────────────────────┘   └──────────────────────────┘    │
│         │                                                             │
│  OCP Route (TLS edge)                                                │
└─────────┼─────────────────────────────────────────────────────────── ┘
          │
    External Users
    https://flask-appserver-route-hetero-demo.<apps-domain>
```

---

### Image Sources (No docker.io)

| Component | Image | Source |
|-----------|-------|--------|
| PostgreSQL 16 | `registry.redhat.io/rhel9/postgresql-16:latest` | Red Hat registry (multi-arch: amd64 + ppc64le) |
| Flask App Server | `image-registry.openshift-image-registry.svc:5000/hetero-demo/hetero-demo-app:latest` | OCP internal registry (S2I build) |
| S2I base image | `registry.redhat.io/ubi9/python-311:latest` | Red Hat registry (multi-arch) |
| Init container | `image-registry.openshift-image-registry.svc:5000/openshift/cli:latest` | OCP internal registry |
| Verify job | `image-registry.openshift-image-registry.svc:5000/openshift/cli:latest` | OCP internal registry |

---

### File Structure

```
heterogeneous-ocp-demo/          ← repo root
├── README.md                        # This file
├── deploy.sh                        # One-shot deployment script
├── .gitignore
├── 00-namespace.yaml                # Namespace: hetero-demo
├── 01-node-labels-taints.sh         # Label Intel (appserver) and Power (database) nodes
├── 02-postgres-operator.yaml        # PostgreSQL operator (optional operator-based install)
├── 03-postgres-cluster.yaml         # PostgreSQL cluster CR (operator-based)
├── 03-postgres-direct.yaml          # PostgreSQL 16 Deployment → IBM Power (ppc64le) node
├── 04-appserver-build.yaml          # OCP S2I BuildConfig + ImageStream (amd64 build)
├── 06-appserver-deployment.yaml     # Flask App Server → Intel (x86_64) node
├── 07-appserver-service-route.yaml  # Service + OCP Route for Flask app
├── 08-network-policy.yaml           # NetworkPolicy for cross-arch traffic
├── 09-verify-job.yaml               # Verification job (OCP cli image)
└── app/
    ├── app.py                       # Flask application source + browser UI
    ├── requirements.txt             # Python dependencies (pinned)
    └── Dockerfile                   # Dockerfile using registry.redhat.io/ubi9/python-311
```

---

### Prerequisites

- OpenShift HCP guest cluster (on IBM Fusion HCI or any OCP cluster) with:
  - At least **1 Intel (x86_64)** worker node
  - At least **1 IBM Power (ppc64le)** worker node
- `oc` CLI logged in to the HCP guest cluster
- Access to `registry.redhat.io` from cluster nodes (standard OCP pull secret)
- Internal OCP image registry accessible (default in OCP clusters)

---

### Quick Start — One-Shot Deployment

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

### Step-by-Step Deployment

#### Step 1 — Label the nodes

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

This applies:
- Intel node → `workload-type=appserver`
- Power node → `workload-type=database`

Verify labels:
```bash
oc get nodes --show-labels | grep workload-type
```

---

#### Step 2 — Create namespace

```bash
oc apply -f 00-namespace.yaml
```

---

#### Step 3 — Deploy PostgreSQL 16 on IBM Power node

```bash
oc apply -f 03-postgres-direct.yaml

# Watch the pod come up on the Power node
oc get pods -n hetero-demo -l app=postgres -o wide -w
```

This creates:
- **Secret** `hetero-postgres-secret` — DB credentials (user, password, dbname, uri)
- **PVC** `hetero-postgres-pvc` — 10Gi data volume on Power node
- **Deployment** `hetero-postgres` — pinned to ppc64le via nodeAffinity
- **Service** `hetero-postgres-service` — ClusterIP on port 5432

---

#### Step 4 — Build the Flask App Server (S2I on Intel node)

The build runs **on the Intel (amd64) node** using the Red Hat UBI9 Python 3.11 image.
The resulting image is **amd64** and stored in the internal OCP registry.
No docker.io credentials needed.

```bash
# Create the BuildConfig and ImageStream
oc apply -f 04-appserver-build.yaml

# Start the S2I build (uploads app/ directory to the cluster)
# The build pod is pinned to the amd64 (Intel) node via nodeSelector
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

#### Step 5 — Deploy Flask App Server on Intel node

```bash
oc apply -f 06-appserver-deployment.yaml
oc apply -f 07-appserver-service-route.yaml
oc apply -f 08-network-policy.yaml

# Wait for rollout
oc rollout status deployment/flask-appserver -n hetero-demo
```

---

#### Step 6 — Verify deployment

```bash
# Check pod placement
oc get pods -n hetero-demo -o wide
```

Expected output:
```
NAME                              READY  STATUS   NODE                                        ...
hetero-postgres-xxxx              1/1    Running  <your-power-node-hostname>   ...
flask-appserver-xxxx              1/1    Running  <your-intel-node-hostname>   ...
```

Confirm architectures:
```bash
# PostgreSQL pod — should show ppc64le
oc exec -n hetero-demo deploy/hetero-postgres -- uname -m
# Expected: ppc64le

# Flask app server pod — should show x86_64
oc exec -n hetero-demo deploy/flask-appserver -- uname -m
# Expected: x86_64
```

---

#### Step 7 — Test the application

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

# Show architecture info (Intel app → Power DB)
curl -sk https://$ROUTE/arch | python3 -m json.tool

# Create an inventory item (written from Intel node to IBM Power PostgreSQL)
curl -sk -X POST https://$ROUTE/items \
  -H 'Content-Type: application/json' \
  -d '{"name":"fusion-hci-item","description":"Cross-arch write: Intel (x86_64) → IBM Power (ppc64le) PostgreSQL"}'

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
      "architecture": "x86_64",
      "arch_label": "x86_64 (Intel)",
      "node": "<your-intel-node-hostname>"
    },
    "database": {
      "role": "Database Server (rhel9/postgresql-16)",
      "architecture": "ppc64le (IBM Power)",
      "host": "hetero-postgres-service.hetero-demo.svc.cluster.local",
      "connected": true,
      "postgres_version": "PostgreSQL 16.x on powerpc64le-redhat-linux-gnu ..."
    }
  }
}
```

---

### Local Development (without OCP)

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

# Run with Flask dev server
python app.py
```

---

### How Workload Placement Works

#### Node Labels (set by `01-node-labels-taints.sh`)

| Node | Architecture | `workload-type` label | Workload |
|------|-------------|----------------------|----------|
| Intel worker | `x86_64` / `amd64` | `appserver` | Flask App Server |
| Power worker | `ppc64le` | `database` | PostgreSQL 16 |

#### Node Affinity (Hard Placement)

**PostgreSQL → IBM Power node:**
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
              values: [database]
```

**Flask App Server → Intel node:**
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
              values: [appserver]
```

**S2I Build → Intel node (produces amd64 image):**
```yaml
nodeSelector:
  kubernetes.io/arch: amd64
```

---

### API Reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | Browser UI — inventory management |
| GET | `/health` | Liveness probe |
| GET | `/ready` | Readiness probe (checks DB) |
| GET | `/arch` | **Cross-arch info** — shows Intel app + Power DB details |
| GET | `/items` | List all inventory items from PostgreSQL |
| POST | `/items` | Create item `{"name":"...", "description":"..."}` |
| GET | `/items/<id>` | Get a single item by ID |
| PUT | `/items/<id>` | Update item `{"name":"...", "description":"..."}` |
| DELETE | `/items/<id>` | Delete item by ID |

---

### Cleanup

```bash
oc delete namespace hetero-demo
```

---

## Demo 2: IBM Db2 on IBM Power + Flask E-Cart on Intel

> **Repo:** [ganshug/heterogeneous-ecommerce-demo](https://github.com/ganshug/heterogeneous-ecommerce-demo)

This demo showcases an IBM Power E-Cart application — a full e-commerce shopping cart — where the Flask app server runs on Intel (x86_64) and IBM Db2 Community Edition runs on IBM Power (ppc64le).

| Component | Architecture | Node Type | Workload | Image Source |
|-----------|-------------|-----------|----------|--------------|
| **E-Cart App Server** | `x86_64` | Intel | Flask e-commerce shopping cart | OCP internal registry (S2I build on amd64) |
| **IBM Db2 CE** | `ppc64le` | IBM Power | Data persistence (products, cart, orders) | `cp.icr.io/cp/db2/db2u:latest` |

### Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│               OpenShift Hosted Control Plane (HCP)                   │
│                     Namespace: db2-shop-demo                          │
│                                                                       │
│  ┌──────────────────────────────┐   ┌──────────────────────────┐    │
│  │   Intel Worker Node          │   │   IBM Power Worker Node  │    │
│  │   (x86_64 / amd64)           │   │   (ppc64le)              │    │
│  │                              │   │                          │    │
│  │  ┌──────────────────────┐   │   │  ┌────────────────────┐  │    │
│  │  │  IBM Power E-Cart    │   │   │  │  IBM Db2 CE        │  │    │
│  │  │  Flask / Python      │───┼───┼─▶│  cp.icr.io/db2u   │  │    │
│  │  │  Port: 8080          │   │   │  │  Port: 50000       │  │    │
│  │  │  (S2I / UBI9 amd64)  │   │   │  │  (ppc64le native)  │  │    │
│  │  └──────────────────────┘   │   │  └────────────────────┘  │    │
│  │         │                   │   │                          │    │
│  │  shop-cart-service           │   │  db2-service              │    │
│  └──────────────────────────────┘   └──────────────────────────┘    │
│         │                                                             │
│  OCP Route (TLS edge)                                                │
└─────────┼─────────────────────────────────────────────────────────── ┘
          │
    External Users
    https://shop-cart-route-db2-shop-demo.<apps-domain>
```

### Quick Start

```bash
# Clone the e-commerce demo repo
git clone https://github.com/ganshug/heterogeneous-ecommerce-demo.git
cd heterogeneous-ecommerce-demo

# Log in to your OCP HCP cluster
oc login <api-url> --token=<token>

# Label your nodes
vi 01-node-labels-taints.sh
bash 01-node-labels-taints.sh

# Deploy (requires IBM Entitlement Key for cp.icr.io)
bash deploy.sh
```

> **Prerequisites:** IBM Entitlement Key must be configured in the OCP global pull secret to pull IBM Db2 from `cp.icr.io`.

See the full README at: [heterogeneous-ecommerce-demo/README.md](https://github.com/ganshug/heterogeneous-ecommerce-demo/blob/main/README.md)

---

## Key Takeaways (Both Demos)

1. **`kubernetes.io/arch`** label is auto-applied by OCP — use it for architecture-based scheduling
2. **Node affinity** with `requiredDuringScheduling` enforces hard placement — pods will not start if no matching node exists
3. **ClusterIP DNS** works transparently across architectures — cross-arch pod-to-pod communication is seamless
4. **Custom labels** (`workload-type`) give fine-grained control beyond just architecture
5. **OCP S2I BuildConfig** with `nodeSelector: kubernetes.io/arch: amd64` builds app images natively on Intel nodes
6. **IBM Fusion HCI** enables mixed-architecture OCP HCP clusters — run IBM Power workloads alongside x86_64 workloads in the same cluster
7. **No docker.io** required for the PostgreSQL demo — all images from Red Hat or internal OCP registry
8. **IBM Db2 on ppc64le** runs natively on IBM Power via `cp.icr.io/cp/db2/db2u` — requires IBM Entitlement Key