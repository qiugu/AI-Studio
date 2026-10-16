# Two-Node Kubernetes Deployment Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the AI-Studio Kubernetes deployment safe and explicit for the current two-node, mixed-architecture cluster, while adding network isolation and preflight checks without claiming unsupported high availability.

**Architecture:** Keep all current application and stateful workloads on the ARM64 `k8s-master`, because the checked-in build/import flow produces local ARM64 images and all persistent volumes are local RWO volumes bound to that node. Add a namespace NetworkPolicy ingress baseline that permits only the documented application-to-service flows while leaving egress unrestricted for configured providers, and make deployment fail early when node readiness or Calico readiness is not healthy. Fix the image build context and update documentation with the real dual-node and mixed-architecture constraints.

**Tech Stack:** Kubernetes manifests, Kustomize, Bash, Docker/BuildKit, PyYAML, pytest.

## Global Constraints

- Do not move workloads to the AMD64 worker until a multi-architecture image distribution path is configured.
- Preserve local PV `Retain` behavior and do not delete or recreate existing PVCs.
- Do not apply changes to the live cluster in this implementation; validate manifests locally and provide the controlled deployment command.
- Preserve RabbitMQ as the only Celery broker and keep the existing queue names.
- Keep the current `/var/lib/ai-studio` host paths and `k8s-master` PV affinity unless a future storage migration is explicitly approved.
- NetworkPolicy changes must not add default-deny egress, because outbound LLM, embedding, Ollama, and other configured provider calls are part of the application contract.

## Files and Responsibilities

- Modify `deploy/k8s/applications.yaml`: add explicit ARM64 scheduling, startup-safe probes, and rollout metadata for API, worker, and frontend workloads.
- Modify `deploy/k8s/bootstrap-platform-admin-job.yaml`: pin the one-shot backend image to ARM64 as well.
- Modify `deploy/k8s/datastores.yaml`: add explicit ARM64 scheduling and graceful termination settings to stateful services.
- Create `deploy/k8s/networkpolicy.yaml`: deny unsolicited namespace ingress and allow the documented NodePort/frontend, API/worker, and datastore paths while leaving egress unrestricted.
- Modify `deploy/k8s/kustomization.yaml`: include the NetworkPolicy resource.
- Modify `deploy/k8s/deploy.sh`: add node/Calico preflight checks before changing application state.
- Modify `deploy/k8s/build-images.sh`: use the actual repository root as the backend build context and expose the architecture limitation clearly.
- Modify `deploy/k8s/README.md`: document the live two-node audit result, mixed-architecture scheduling rule, Calico interface requirement, NetworkPolicy behavior, and the non-HA storage/broker boundary.
- Create `tests/test_k8s_deployment_hardening.py`: lock the scheduling, policy, build-context, and preflight invariants into static tests.

### Task 1: Add explicit architecture scheduling and safe pod lifecycle settings

**Files:**
- Modify: `deploy/k8s/applications.yaml`
- Modify: `deploy/k8s/bootstrap-platform-admin-job.yaml`
- Modify: `deploy/k8s/datastores.yaml`
- Test: `tests/test_k8s_deployment_hardening.py`

**Interfaces:**
- Consumes: existing `ai-studio` labels, local PVCs, and `kubernetes.io/arch` node labels.
- Produces: every checked-in workload explicitly targets `kubernetes.io/arch: arm64`; application pods gain startup protection and bounded rollout history.

- [x] **Step 1: Write failing static tests**

```python
def test_all_workloads_are_pinned_to_the_supported_local_image_architecture():
    for document in _load_documents("deploy/k8s/applications.yaml") + _load_documents("deploy/k8s/datastores.yaml"):
        if document.get("kind") not in {"Deployment", "StatefulSet"}:
            continue
        pod_spec = document["spec"]["template"]["spec"]
        assert pod_spec["nodeSelector"] == {"kubernetes.io/arch": "arm64"}


def test_backend_has_startup_probe_before_liveness_can_restart_slow_boots():
    backend = _resource(_load_documents("deploy/k8s/applications.yaml"), "Deployment", "backend")
    container = backend["spec"]["template"]["spec"]["containers"][0]
    assert container["startupProbe"]["httpGet"] == {"path": "/health", "port": "http"}
    assert backend["spec"]["revisionHistoryLimit"] == 3
```

- [x] **Step 2: Run the focused test and verify it fails**

Run: `pytest -q tests/test_k8s_deployment_hardening.py`

Expected: FAIL because the current manifests have no explicit architecture selector or backend startup probe.

- [x] **Step 3: Add the minimal manifest changes**

Add `nodeSelector: {kubernetes.io/arch: arm64}` under each Deployment/StatefulSet/Job pod spec. Add `revisionHistoryLimit: 3` and `progressDeadlineSeconds: 600` to Deployments. Add a backend `startupProbe` using `/health`, with `failureThreshold: 60`, `periodSeconds: 5`, and `timeoutSeconds: 3`; keep existing readiness/liveness probes. Add `terminationGracePeriodSeconds: 30` to frontend and datastore pods, preserving the worker’s existing 90-second grace period.

- [x] **Step 4: Run the focused test and manifest parse**

Run: `pytest -q tests/test_k8s_deployment_hardening.py && python -c 'import yaml; [list(yaml.safe_load_all(open(p))) for p in ["deploy/k8s/applications.yaml", "deploy/k8s/datastores.yaml"]]'`

Expected: PASS and both YAML files parse successfully.

### Task 2: Add namespace network isolation for service-to-service traffic

**Files:**
- Create: `deploy/k8s/networkpolicy.yaml`
- Modify: `deploy/k8s/kustomization.yaml`
- Test: `tests/test_k8s_deployment_hardening.py`

**Interfaces:**
- Consumes: existing component labels and service ports.
- Produces: ingress-deny baseline with explicit NodePort/frontend, frontend/worker-to-backend, and app-to-datastore allowances; egress remains unrestricted.

- [x] **Step 1: Write failing static tests**

```python
def test_network_policy_resource_is_in_kustomization():
    kustomization = yaml.safe_load((ROOT / "deploy/k8s/kustomization.yaml").read_text())
    assert "networkpolicy.yaml" in kustomization["resources"]


def test_network_policy_has_default_ingress_deny_and_required_allow_rules():
    documents = _load_documents("deploy/k8s/networkpolicy.yaml")
    names = {doc["metadata"]["name"] for doc in documents}
    assert "default-deny-ingress" in names
    assert {"allow-frontend", "frontend-to-backend", "app-to-datastores"} <= names
```

- [x] **Step 2: Run the focused test and verify it fails**

Run: `pytest -q tests/test_k8s_deployment_hardening.py`

Expected: FAIL because the NetworkPolicy file and Kustomize entry do not exist.

- [x] **Step 3: Add the NetworkPolicy resources**

Create seven policies in namespace `ai-studio`:

1. `default-deny-ingress` selects all pods and sets `policyTypes: [Ingress]` with no ingress rules.
2. `frontend-to-backend` selects the backend component, allows ingress TCP 8000 only from the frontend/worker components and node CIDRs `192.168.1.0/24` and `192.168.99.0/24` for kubelet health probes.
3. `app-to-datastores` selects MySQL and allows port 3306 from backend, celery-worker, and the bootstrap Job label `job-name: bootstrap-platform-admin`.
4. `app-to-redis`, `app-to-rabbitmq`, and `app-to-qdrant` select their respective datastore and allow only the backend/worker ports used by the application.
5. `allow-frontend` selects the frontend component and allows its NodePort HTTP ingress from all sources.

Do not add egress policy types; DNS and configured outbound providers must remain reachable. Add `networkpolicy.yaml` to `kustomization.yaml` after `configmap.yaml`.

- [x] **Step 4: Validate policy structure**

Run: `pytest -q tests/test_k8s_deployment_hardening.py && kubectl kustomize deploy/k8s >/tmp/ai-studio-k8s-rendered.yaml`

Expected: PASS and Kustomize renders without errors. If local `kubectl` lacks Kustomize support, run the PyYAML test and report the missing local validator without applying anything.

### Task 3: Add deployment preflight checks for node and Calico health

**Files:**
- Modify: `deploy/k8s/deploy.sh`
- Test: `tests/test_k8s_deployment_hardening.py`

**Interfaces:**
- Consumes: `kubectl`, namespace `ai-studio`, the current Calico DaemonSet label `k8s-app=calico-node`, and the ARM64 node label.
- Produces: a `preflight_cluster()` shell function called before local directory creation or resource apply.

- [x] **Step 1: Write failing script-content tests**

```python
def test_deploy_script_runs_cluster_preflight_before_apply():
    script = (ROOT / "deploy/k8s/deploy.sh").read_text()
    assert "preflight_cluster()" in script
    assert "kubectl get nodes" in script
    assert "k8s-app=calico-node" in script
    assert "preflight_cluster" in script.split("kubectl apply -f", 1)[0]
```

- [x] **Step 2: Run the focused test and verify it fails**

Run: `pytest -q tests/test_k8s_deployment_hardening.py`

Expected: FAIL because the current script has no cluster preflight.

- [x] **Step 3: Implement the preflight function**

Add a function that:

1. Requires at least one Ready node with `kubernetes.io/arch=arm64`.
2. Waits up to 180 seconds for all Calico pods selected by `k8s-app=calico-node` to be Ready.
3. Verifies at least two Ready nodes are present when the cluster has two or more nodes, and prints a warning—not a failure—if a future deployment intentionally runs single-node.
4. Calls `preflight_cluster` immediately after command checks and before `sudo install -d` or any `kubectl apply`.

Use `kubectl wait --for=condition=Ready pod -l k8s-app=calico-node -n kube-system --timeout=180s` for Calico readiness. Keep the function read-only.

- [x] **Step 4: Run shell syntax and focused tests**

Run: `bash -n deploy/k8s/deploy.sh && pytest -q tests/test_k8s_deployment_hardening.py`

Expected: shell syntax passes and the focused tests pass.

### Task 4: Fix the image build context and align deployment documentation

**Files:**
- Modify: `deploy/k8s/build-images.sh`
- Modify: `deploy/k8s/README.md`
- Test: `tests/test_k8s_deployment_hardening.py`

**Interfaces:**
- Consumes: repository-root `Dockerfile`, frontend K8s Dockerfile, and current local containerd import workflow.
- Produces: a working ARM64 local build path and operator documentation for mixed-architecture worker usage.

- [x] **Step 1: Write failing tests for the stale build context and docs**

```python
def test_build_script_uses_repository_root_for_backend_image():
    script = (ROOT / "deploy/k8s/build-images.sh").read_text()
    assert '"${PROJECT_ROOT}"' in script
    assert '"${PROJECT_ROOT}/backend"' not in script


def test_readme_documents_mixed_architecture_and_calico_interface_requirements():
    readme = (ROOT / "deploy/k8s/README.md").read_text()
    assert "ARM64" in readme and "AMD64" in readme
    assert "IP_AUTODETECTION_METHOD" in readme
    assert "NetworkPolicy" in readme
```

- [x] **Step 2: Run the focused test and verify it fails**

Run: `pytest -q tests/test_k8s_deployment_hardening.py`

Expected: FAIL because the build script points at `backend/` and the README describes a single-node cluster.

- [x] **Step 3: Fix the build script**

Change the backend build command to use the repository root (`"${PROJECT_ROOT}"`). Keep the local tag/import behavior and `--platform linux/arm64`; add a message that all checked-in workloads are pinned to ARM64 and that an AMD64 worker requires a separate multi-architecture registry workflow before it can run application pods.

- [x] **Step 4: Rewrite the deployment limitations and operations section**

Document:

- observed cluster topology: ARM64 master `192.168.99.131`, AMD64 worker `192.168.1.10`;
- current safe scheduling: application/stateful pods remain ARM64 and local PVs remain on `k8s-master`;
- Calico must use the `192.168.1.x` interface for node-to-node BGP in this dual-NIC setup, with an explicit `IP_AUTODETECTION_METHOD` such as `can-reach=192.168.1.10` or an interface-specific equivalent validated for the environment;
- TCP 179, the Calico IP-in-IP path, and Kubernetes API/DNS traffic must be permitted between nodes;
- the checked-in NetworkPolicy only restricts ingress and leaves outbound provider calls available;
- this is not HA: MySQL, RabbitMQ, Qdrant, Redis, and local uploads have one replica and local RWO storage;
- the controlled upgrade flow: build/import, run `kubectl kustomize deploy/k8s`, then execute `deploy.sh` after reviewing the rendered output.

- [x] **Step 5: Run all deployment-focused checks**

Run: `bash -n deploy/k8s/build-images.sh deploy/k8s/deploy.sh && pytest -q tests/test_rabbitmq_deployment_config.py tests/test_k8s_embedding_config.py tests/test_k8s_deployment_hardening.py`

Expected: all selected tests pass.

## Self-Review Checklist

- The plan explicitly addresses the observed BGP event history without treating a currently Established session as proof of HA.
- The plan prevents ARM64-only local images from being scheduled on the AMD64 worker.
- The plan fixes the repository-root migration bug in the image build script.
- The NetworkPolicy does not block external LLM/embedding/Ollama traffic because no default-deny egress policy is added.
- No task deletes PVCs, changes reclaim policies, or applies live cluster resources.
