from pathlib import Path

import yaml


ROOT = next(
    parent
    for parent in Path(__file__).resolve().parents
    if (parent / "docker-compose.yml").exists()
)


def _load_yaml(path: str):
    return yaml.safe_load((ROOT / path).read_text())


def _load_yaml_documents(path: str):
    return [
        document
        for document in yaml.safe_load_all((ROOT / path).read_text())
        if document
    ]


def _resource(documents, kind: str, name: str):
    return next(
        document
        for document in documents
        if document.get("kind") == kind
        and document.get("metadata", {}).get("name") == name
    )


def test_compose_uses_rabbitmq_as_the_only_celery_broker():
    compose = _load_yaml("docker-compose.yml")
    services = compose["services"]
    rabbitmq = services["rabbitmq"]

    assert rabbitmq["image"].startswith("rabbitmq:4.")
    assert rabbitmq["healthcheck"]["test"] == [
        "CMD",
        "rabbitmq-diagnostics",
        "-q",
        "ping",
    ]
    assert "rabbitmq-data" in compose["volumes"]

    backend_env = services["backend"]["environment"]
    assert backend_env["RABBITMQ_HOST"] == "rabbitmq"
    assert "RABBITMQ_PASSWORD" in backend_env
    assert "CELERY_BROKER_URL" not in backend_env
    assert "CELERY_RESULT_BACKEND" not in backend_env
    assert services["backend"]["depends_on"]["rabbitmq"]["condition"] == "service_healthy"
    assert services["celery-worker"]["depends_on"]["rabbitmq"]["condition"] == "service_healthy"


def test_kubernetes_uses_secret_backed_rabbitmq_and_no_redis_broker_url():
    config = _load_yaml("deploy/k8s/configmap.yaml")["data"]
    assert config["RABBITMQ_HOST"] == "rabbitmq"
    assert config["RABBITMQ_PORT"] == "5672"
    assert "RABBITMQ_PASSWORD" not in config
    assert "CELERY_BROKER_URL" not in config
    assert "CELERY_RESULT_BACKEND" not in config

    datastores = _load_yaml_documents("deploy/k8s/datastores.yaml")
    _resource(datastores, "Service", "rabbitmq")
    rabbitmq = _resource(datastores, "StatefulSet", "rabbitmq")
    container = rabbitmq["spec"]["template"]["spec"]["containers"][0]
    env_by_name = {item["name"]: item for item in container["env"]}
    assert env_by_name["RABBITMQ_DEFAULT_USER"]["valueFrom"]["secretKeyRef"]["key"] == "RABBITMQ_USERNAME"
    assert env_by_name["RABBITMQ_DEFAULT_PASS"]["valueFrom"]["secretKeyRef"]["key"] == "RABBITMQ_PASSWORD"
    assert env_by_name["RABBITMQ_DEFAULT_VHOST"]["valueFrom"]["secretKeyRef"]["key"] == "RABBITMQ_VHOST"
    assert container["readinessProbe"]["exec"]["command"] == [
        "rabbitmq-diagnostics",
        "-q",
        "ping",
    ]

    storage = _load_yaml_documents("deploy/k8s/storage.yaml")
    _resource(storage, "PersistentVolume", "ai-studio-rabbitmq")
    _resource(storage, "PersistentVolumeClaim", "rabbitmq-data")


def test_kubernetes_workers_wait_for_and_consume_rabbitmq_queues():
    applications = _load_yaml_documents("deploy/k8s/applications.yaml")
    backend = _resource(applications, "Deployment", "backend")
    backend_wait = backend["spec"]["template"]["spec"]["initContainers"][0]["args"][0]
    assert "('rabbitmq', 5672)" in backend_wait

    worker = _resource(applications, "Deployment", "celery-worker")
    pod_spec = worker["spec"]["template"]["spec"]
    worker_wait = pod_spec["initContainers"][0]["args"][0]
    assert "('rabbitmq', 5672)" in worker_wait
    args = pod_spec["containers"][0]["args"]
    assert any("--queues=default,document.ingest,tenant.cleanup" in arg for arg in args)


def test_deploy_script_migrates_existing_secrets_without_replacing_them():
    script = (ROOT / "deploy/k8s/deploy.sh").read_text()

    assert "/var/lib/ai-studio/rabbitmq" in script
    assert '"RABBITMQ_USERNAME=ai_studio"' in script
    assert '"RABBITMQ_PASSWORD=${rabbitmq_password}"' in script
    assert '"RABBITMQ_VHOST=ai-studio"' in script
    assert "patch secret" in script
    assert "statefulset in mysql redis rabbitmq qdrant" in script
