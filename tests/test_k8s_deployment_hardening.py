from pathlib import Path

import yaml


ROOT = next(
    parent
    for parent in Path(__file__).resolve().parents
    if (parent / "docker-compose.yml").exists()
)


def _load_documents(path: str):
    return [
        document
        for document in yaml.safe_load_all((ROOT / path).read_text(encoding="utf-8"))
        if document
    ]


def _resource(documents, kind: str, name: str):
    return next(
        document
        for document in documents
        if document.get("kind") == kind
        and document.get("metadata", {}).get("name") == name
    )


def test_all_workloads_are_pinned_to_the_supported_local_image_architecture():
    documents = _load_documents("deploy/k8s/applications.yaml") + _load_documents(
        "deploy/k8s/datastores.yaml"
    )

    for document in documents:
        if document.get("kind") not in {"Deployment", "StatefulSet"}:
            continue
        pod_spec = document["spec"]["template"]["spec"]
        assert pod_spec["nodeSelector"] == {"kubernetes.io/arch": "arm64"}


def test_backend_has_startup_probe_before_liveness_can_restart_slow_boots():
    backend = _resource(
        _load_documents("deploy/k8s/applications.yaml"), "Deployment", "backend"
    )
    container = backend["spec"]["template"]["spec"]["containers"][0]

    assert container["startupProbe"]["httpGet"] == {
        "path": "/health",
        "port": "http",
    }
    assert backend["spec"]["revisionHistoryLimit"] == 3


def test_bootstrap_job_is_pinned_to_the_supported_local_image_architecture():
    job = _resource(
        _load_documents("deploy/k8s/bootstrap-platform-admin-job.yaml"),
        "Job",
        "bootstrap-platform-admin",
    )
    assert job["spec"]["template"]["spec"]["nodeSelector"] == {
        "kubernetes.io/arch": "arm64"
    }


def test_network_policy_resource_is_in_kustomization():
    kustomization = yaml.safe_load(
        (ROOT / "deploy/k8s/kustomization.yaml").read_text(encoding="utf-8")
    )
    assert "networkpolicy.yaml" in kustomization["resources"]


def test_network_policy_has_default_ingress_deny_and_required_allow_rules():
    documents = _load_documents("deploy/k8s/networkpolicy.yaml")
    names = {document["metadata"]["name"] for document in documents}

    assert "default-deny-ingress" in names
    assert {"allow-frontend", "frontend-to-backend", "app-to-datastores"} <= names


def test_backend_policy_allows_health_probes_from_both_node_networks():
    policy = _resource(
        _load_documents("deploy/k8s/networkpolicy.yaml"),
        "NetworkPolicy",
        "frontend-to-backend",
    )
    sources = policy["spec"]["ingress"][0]["from"]
    cidrs = {source["ipBlock"]["cidr"] for source in sources if "ipBlock" in source}

    assert {"192.168.1.0/24", "192.168.99.0/24"} <= cidrs


def test_deploy_script_runs_cluster_preflight_before_apply():
    script = (ROOT / "deploy/k8s/deploy.sh").read_text(encoding="utf-8")

    assert "preflight_cluster()" in script
    assert "kubectl get nodes" in script
    assert "k8s-app=calico-node" in script
    assert "preflight_cluster" in script.split("kubectl apply -f", 1)[0]


def test_build_script_uses_repository_root_for_backend_image():
    script = (ROOT / "deploy/k8s/build-images.sh").read_text(encoding="utf-8")

    assert '"${PROJECT_ROOT}"' in script
    assert '"${PROJECT_ROOT}/backend"' not in script


def test_readme_documents_mixed_architecture_and_calico_interface_requirements():
    readme = (ROOT / "deploy/k8s/README.md").read_text(encoding="utf-8")

    assert "ARM64" in readme and "AMD64" in readme
    assert "IP_AUTODETECTION_METHOD" in readme
    assert "NetworkPolicy" in readme
