# Local Kubernetes Deployment Script Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a repository-local one-command Kubernetes deployment entry point that builds/imports the checked-in ARM64 images and invokes the existing cluster deployment workflow without performing remote Git operations.

**Architecture:** Keep `deploy/k8s/build-images.sh` and `deploy/k8s/deploy.sh` unchanged as the server-side build/import and deployment implementation. Add a separate local `deploy/k8s/one-click-deploy.sh` that uploads the project through SSH to a generated temporary server directory and executes those existing scripts there.

**Tech Stack:** Bash, local SSH/tar, remote Docker, containerd `ctr`, kubectl, Kubernetes/Kustomize, pytest.

## Global Constraints

- Default `./deploy/k8s/one-click-deploy.sh` must upload the project, then run the existing server-side build/import script followed by the existing server-side deployment script.
- `--skip-build` must deploy existing imported images without rebuilding them.
- The script must resolve paths relative to itself and work from another current working directory.
- The script must not run `git push`, `git commit`, or destructive volume deletion commands.
- The local workstation must require only SSH and tar; Docker, ctr, kubectl, sudo, openssl, and base64 are server-side requirements.
- The current manifests target the documented local ARM64 Kubernetes cluster; do not claim multi-architecture or HA support.

---

### Task 1: Lock down the Kubernetes entry-point contract

**Files:**
- Modify: `tests/test_local_deployment_script.py`
- Test: `deploy/k8s/one-click-deploy.sh` (expected to fail until the new file exists)

**Interfaces:**
- Consumes: repository root and the new local uploader source text.
- Produces: tests for SSH upload, server-side command delegation, command modes, path resolution, and local-only behavior.

- [ ] **Step 1: Write the failing tests**

```python
def test_deploy_script_builds_images_then_deploys_to_kubernetes():
    script = (ROOT / "deploy/k8s/one-click-deploy.sh").read_text(encoding="utf-8")
    assert "ssh" in script
    assert "tar" in script
    assert "bash deploy/k8s/build-images.sh" in script
    assert "bash deploy/k8s/deploy.sh" in script
    assert "--skip-build" in script
```

- [ ] **Step 2: Run the focused test to verify RED**

Run: `.venv/bin/pytest -q tests/test_local_deployment_script.py`

Expected: FAIL because the new local uploader does not exist yet.

---

### Task 2: Implement the local uploader and server-side delegator

**Files:**
- Create: `deploy/k8s/one-click-deploy.sh`

**Interfaces:**
- Consumes: local SSH/tar and the unchanged server-side scripts under `deploy/k8s/`.
- Produces: `up` (default), `build`, `deploy`, and `status` commands; `--skip-build` is valid for `up` and selects deploy-only behavior.

- [ ] **Step 1: Implement the orchestration flow**

The default command must create a generated temporary directory on the server, upload the project without `.git`, `.venv`, `.env`, or frontend dependencies, then execute:

```bash
tar ... | ssh ... "tar -xzf - ..."
ssh ... "bash deploy/k8s/build-images.sh && bash deploy/k8s/deploy.sh"
```

`build` runs only the server-side build/import command, `deploy` runs only the server-side deployment command, and `status` runs:

```bash
kubectl -n ai-studio get pods,services,persistentvolumeclaims
```

Unknown arguments must print usage and exit non-zero.

- [ ] **Step 2: Validate shell syntax**

Run: `chmod +x deploy/k8s/one-click-deploy.sh && bash -n deploy/k8s/one-click-deploy.sh`

Expected: exit code 0.

---

### Task 3: Align Kubernetes documentation and verify

**Files:**
- Modify: `README.md`
- Modify: `AGENTS.md`
- Modify: `deploy/k8s/README.md`
- Test: `tests/test_local_deployment_script.py`

**Interfaces:**
- Consumes: root script command modes and existing K8s deployment limitations.
- Produces: one copy-paste local K8s deployment command and explicit ARM64/local-containerd scope.

- [ ] **Step 1: Document the root entry point**

Document:

```bash
./deploy/k8s/one-click-deploy.sh
```

Also document `./deploy/k8s/one-click-deploy.sh build`, `./deploy/k8s/one-click-deploy.sh deploy`, `./deploy/k8s/one-click-deploy.sh status`, and `./deploy/k8s/one-click-deploy.sh --skip-build`.

- [ ] **Step 2: Run focused deployment checks**

Run: `.venv/bin/pytest -q tests/test_local_deployment_script.py tests/test_rabbitmq_deployment_config.py tests/test_k8s_deployment_hardening.py`

Expected: all tests pass.

Run: `bash -n deploy/k8s/one-click-deploy.sh deploy/k8s/build-images.sh deploy/k8s/deploy.sh && git diff --check`

Expected: exit code 0.

- [ ] **Step 3: Confirm local-only scope**

Run: `git status --short`

Expected: only local script, tests, plan, and documentation changes are present; no commit or remote push is performed.
