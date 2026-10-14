# RabbitMQ Enterprise Production Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate Celery from the shared Redis instance to RabbitMQ quorum queues, remove the unused Celery result backend, and deploy a production-safe task delivery configuration without disturbing Redis-backed application features.

**Architecture:** FastAPI publishes small task messages to RabbitMQ while Redis remains dedicated to cache, rate limiting, and token revocation. Celery persists business status in MySQL instead of a result backend, uses explicit quorum queues and publisher confirms, and acknowledges idempotent tasks only after execution. Docker Compose runs a single-node RabbitMQ for local and compact deployments; Kubernetes supports the current single-node cluster while documenting that true broker HA requires an external or three-node RabbitMQ cluster.

**Tech Stack:** Python 3.11, Celery 5.6, Kombu, RabbitMQ 4.x, Redis 7, Docker Compose, Kubernetes, pytest.

## Global Constraints

- Preserve all pre-existing uncommitted changes in the shared working tree.
- Do not commit because target files already contain unrelated user changes that must not be bundled into an agent commit.
- Keep Redis DB 0 for application cache, rate limiting, and token revocation only.
- Do not store RabbitMQ passwords in ConfigMaps or source-controlled manifests.
- Celery task messages contain identifiers and paths only; file contents remain outside the broker.
- The current Kubernetes target is single-node ARM64, so an in-cluster RabbitMQ replica improves separation but not infrastructure-level high availability.

---

### Task 1: Lock the production Celery contract with failing tests

**Files:**
- Modify: `backend/tests/test_celery_config.py`
- Modify: `backend/tests/test_celery_task_registration.py`
- Create: `backend/tests/test_knowledge_processor_failure.py`

**Interfaces:**
- Consumes: `Config.get_celery_broker_url()`, `Config.get_celery_result_backend()`, `celery_app.conf`, `process_document_task.run()`.
- Produces: Executable requirements for encoded AMQP URLs, disabled result storage, quorum queue routing, late acknowledgement, and propagated task failures.

- [ ] **Step 1: Write the failing configuration tests**

```python
def test_celery_broker_url_is_built_from_rabbitmq_settings():
    config = Config(
        celery_broker_url="",
        rabbitmq_host="rabbitmq",
        rabbitmq_port=5672,
        rabbitmq_username="worker@example.com",
        rabbitmq_password="p@ss/word",
        rabbitmq_vhost="ai-studio",
    )
    assert config.get_celery_broker_url() == (
        "amqp://worker%40example.com:p%40ss%2Fword@rabbitmq:5672/ai-studio"
    )


def test_celery_result_backend_is_disabled_by_default():
    assert Config(celery_result_backend="").get_celery_result_backend() is None
```

- [ ] **Step 2: Write failing Celery application contract tests**

```python
def test_enterprise_delivery_settings_are_enabled():
    assert celery_app.conf.task_ignore_result is True
    assert celery_app.conf.task_acks_late is True
    assert celery_app.conf.task_reject_on_worker_lost is True
    assert celery_app.conf.worker_prefetch_multiplier == 1
    assert celery_app.conf.broker_transport_options["confirm_publish"] is True


def test_tasks_use_declared_quorum_queues():
    routes = celery_app.conf.task_routes
    assert routes["process_document_task"]["queue"] == "document.ingest"
    assert routes["tenant_cleanup.cascade_delete"]["queue"] == "tenant.cleanup"
    queues = {queue.name: queue for queue in celery_app.conf.task_queues}
    assert queues["document.ingest"].queue_arguments["x-queue-type"] == "quorum"
    assert queues["tenant.cleanup"].queue_arguments["x-queue-type"] == "quorum"
```

- [ ] **Step 3: Write a failing task failure-semantics test**

```python
def test_document_processing_records_failure_and_reraises(monkeypatch):
    document = SimpleNamespace(status=DocumentStatus.PROCESSING, error_message=None)
    session = MagicMock()
    first_query = MagicMock()
    first_query.filter.return_value.first.side_effect = RuntimeError("database unavailable")
    failure_query = MagicMock()
    failure_query.filter.return_value.first.return_value = document
    session.query.side_effect = [first_query, failure_query]
    monkeypatch.setattr(knowledge_processor, "sessionLocal", lambda: session)

    with pytest.raises(RuntimeError, match="database unavailable"):
        knowledge_processor.process_document_task.run("doc-1", "/tmp/doc.txt", "tenant-1")

    assert document.status == DocumentStatus.FAILED
    session.close.assert_called_once()
```

- [ ] **Step 4: Run tests and confirm RED**

Run: `cd backend && .venv/bin/pytest tests/test_celery_config.py tests/test_celery_task_registration.py tests/test_knowledge_processor_failure.py -q`

Expected: failures for missing RabbitMQ fields, missing quorum/routing settings, enabled result backend, and swallowed task exception.

- [ ] **Step 5: Review checkpoint without commit**

Run: `git diff -- backend/tests/test_celery_config.py backend/tests/test_celery_task_registration.py backend/tests/test_knowledge_processor_failure.py`

Expected: only the new production contract tests.

---

### Task 2: Implement RabbitMQ configuration and reliable task semantics

**Files:**
- Modify: `backend/app/core/config.py`
- Modify: `backend/app/core/celery_app.py`
- Modify: `backend/app/services/knowledge_processor.py`
- Modify: `backend/requirements.txt`

**Interfaces:**
- Consumes: RabbitMQ settings from environment variables and the tests from Task 1.
- Produces: `get_celery_broker_url() -> str`, `get_celery_result_backend() -> Optional[str]`, two declared quorum queues, and failures visible to Celery.

- [ ] **Step 1: Implement secure AMQP URL construction**

Add `rabbitmq_host`, `rabbitmq_port`, `rabbitmq_username`, `rabbitmq_password`, and `rabbitmq_vhost` settings. Build an AMQP URL with `urllib.parse.quote`, while allowing an explicitly configured `CELERY_BROKER_URL` to override the generated URL. Return `None` for an empty result-backend setting.

- [ ] **Step 2: Configure declared quorum queues and delivery guarantees**

Declare `document.ingest` and `tenant.cleanup` with `x-queue-type=quorum`; route the two existing tasks explicitly; enable publisher confirms, late acknowledgement, worker-lost rejection, persistent delivery, startup retries, and `worker_prefetch_multiplier=1`; disable result storage and import both task modules.

- [ ] **Step 3: Propagate document task failures**

Keep the MySQL `FAILED` status update, include `tenant_id` in the recovery query, and re-raise the original exception after the status transaction so Celery records task failure.

- [ ] **Step 4: Upgrade Celery**

Change `celery==5.4.0` to `celery==5.6.3`, the stable line that supports quorum queue configuration.

- [ ] **Step 5: Run tests and confirm GREEN**

Run: `cd backend && .venv/bin/pytest tests/test_celery_config.py tests/test_celery_task_registration.py tests/test_knowledge_processor_failure.py tests/test_knowledge_processor_vector_layout.py -q`

Expected: all selected tests pass.

- [ ] **Step 6: Review checkpoint without commit**

Run: `git diff -- backend/app/core/config.py backend/app/core/celery_app.py backend/app/services/knowledge_processor.py backend/requirements.txt`

Expected: only RabbitMQ configuration, Celery reliability settings, failure propagation, and the dependency upgrade alongside preserved prior edits.

---

### Task 3: Migrate Docker Compose and environment templates

**Files:**
- Modify: `.env.example`
- Modify: `backend/.env.example`
- Modify: `docker-compose.yml`

**Interfaces:**
- Consumes: `RABBITMQ_HOST`, `RABBITMQ_PORT`, `RABBITMQ_USERNAME`, `RABBITMQ_PASSWORD`, and `RABBITMQ_VHOST`.
- Produces: A healthy RabbitMQ service, persistent broker volume, and backend/worker environment wiring with no Redis broker/result URLs.

- [ ] **Step 1: Add deployment configuration validation tests**

Extend the existing deployment configuration test module, or create `backend/tests/test_rabbitmq_deployment_config.py`, to parse Compose YAML and assert that RabbitMQ exists, the worker depends on it, backend environment uses RabbitMQ settings, Redis is not configured as Celery Broker, and no result backend is set.

- [ ] **Step 2: Run the deployment tests and confirm RED**

Run: `cd backend && .venv/bin/pytest tests/test_rabbitmq_deployment_config.py -q`

Expected: failure because RabbitMQ is absent and Redis URLs remain.

- [ ] **Step 3: Add RabbitMQ to Compose**

Use a RabbitMQ management image, persistent volume, non-default credentials from `.env`, an AMQP health check, and service dependencies. Keep Redis for application features and update its comments to remove the Broker responsibility.

- [ ] **Step 4: Update environment templates**

Document strong RabbitMQ credentials and local defaults. Remove Redis Broker and Result Backend defaults from both templates while preserving an optional explicit `CELERY_BROKER_URL` override for managed RabbitMQ.

- [ ] **Step 5: Validate Compose and confirm GREEN**

Run: `docker compose config --quiet`

Run: `cd backend && .venv/bin/pytest tests/test_rabbitmq_deployment_config.py -q`

Expected: Compose renders successfully and tests pass.

- [ ] **Step 6: Review checkpoint without commit**

Run: `git diff -- .env.example backend/.env.example docker-compose.yml backend/tests/test_rabbitmq_deployment_config.py`

Expected: RabbitMQ service, volume, environment, health checks, and preserved administrator-bootstrap changes.

---

### Task 4: Add RabbitMQ to the Kubernetes deployment

**Files:**
- Modify: `deploy/k8s/configmap.yaml`
- Modify: `deploy/k8s/datastores.yaml`
- Modify: `deploy/k8s/storage.yaml`
- Modify: `deploy/k8s/applications.yaml`
- Modify: `deploy/k8s/deploy.sh`
- Modify: `backend/tests/test_rabbitmq_deployment_config.py`

**Interfaces:**
- Consumes: RabbitMQ credentials in `ai-studio-secrets` and non-secret network settings in `ai-studio-config`.
- Produces: RabbitMQ Service/StatefulSet/PVC, generated migration credentials for existing Secrets, datastore readiness checks, and a worker consuming the two declared queues.

- [ ] **Step 1: Extend tests for Kubernetes manifests and Secret handling**

Assert that the ConfigMap contains no password or Redis Broker URL, RabbitMQ reads credentials from Secret keys, a persistent volume exists, the worker waits for port 5672 and consumes both queues, and `deploy.sh` creates missing RabbitMQ Secret keys without replacing existing database keys.

- [ ] **Step 2: Run the Kubernetes deployment tests and confirm RED**

Run: `cd backend && .venv/bin/pytest tests/test_rabbitmq_deployment_config.py -q`

Expected: failure because Kubernetes RabbitMQ resources and credential migration are absent.

- [ ] **Step 3: Add RabbitMQ storage and workload resources**

Add a local persistent volume/PVC for the current deployment model, a RabbitMQ Service and StatefulSet using Secret-backed credentials, health probes, persistent storage, and bounded resources.

- [ ] **Step 4: Wire backend and worker readiness**

Add RabbitMQ to datastore socket checks, add an explicit worker-side Broker readiness check, and launch the worker with `--queues=document.ingest,tenant.cleanup`.

- [ ] **Step 5: Make Secret migration idempotent**

Generate RabbitMQ credentials when creating `ai-studio-secrets`; when reusing an older Secret, patch only missing RabbitMQ keys. Create `/var/lib/ai-studio/rabbitmq`, wait for the RabbitMQ StatefulSet, and preserve the existing platform-admin bootstrap workflow.

- [ ] **Step 6: Validate manifests and confirm GREEN**

Run: `kubectl kustomize deploy/k8s >/tmp/ai-studio-rabbitmq-rendered.yaml`

Run: `bash -n deploy/k8s/deploy.sh`

Run: `cd backend && .venv/bin/pytest tests/test_rabbitmq_deployment_config.py -q`

Expected: manifests render, the script parses, and tests pass.

- [ ] **Step 7: Review checkpoint without commit**

Run: `git diff -- deploy/k8s/configmap.yaml deploy/k8s/datastores.yaml deploy/k8s/storage.yaml deploy/k8s/applications.yaml deploy/k8s/deploy.sh`

Expected: isolated RabbitMQ resources and wiring alongside preserved offline-embedding and administrator-bootstrap changes.

---

### Task 5: Document, verify, and deploy the migration

**Files:**
- Modify: `README.md`
- Modify: `deploy/k8s/README.md`
- Modify: `AGENTS.md`
- Modify: `docs/architecture.md`
- Modify: `docs/core-mechanisms.md`

**Interfaces:**
- Consumes: the production configuration from Tasks 2–4.
- Produces: operator instructions, verification commands, and a deployed RabbitMQ-backed Celery worker.

- [ ] **Step 1: Update operator documentation**

Document RabbitMQ credentials, Broker/Redis responsibility boundaries, queue names, health checks, rollback considerations, and the limitation that a one-node Kubernetes cluster cannot provide RabbitMQ HA. Preserve current platform-admin instructions.

- [ ] **Step 2: Run focused and regression tests**

Run: `cd backend && .venv/bin/pytest tests/test_celery_config.py tests/test_celery_task_registration.py tests/test_knowledge_processor_failure.py tests/test_knowledge_processor_vector_layout.py tests/test_rabbitmq_deployment_config.py -q`

Run: `cd backend && .venv/bin/pytest -q`

Expected: all focused tests and the backend suite pass.

- [ ] **Step 3: Validate deployment definitions**

Run: `docker compose config --quiet`

Run: `kubectl kustomize deploy/k8s >/tmp/ai-studio-rabbitmq-rendered.yaml`

Run: `bash -n deploy/k8s/deploy.sh`

Expected: all commands exit successfully.

- [ ] **Step 4: Deploy through the repository's Kubernetes workflow**

Run the documented image build/import and `deploy/k8s/deploy.sh` workflow on the configured cluster. Do not delete the Redis volume or existing application data.

- [ ] **Step 5: Smoke test the deployed topology**

Verify the RabbitMQ StatefulSet, backend and Celery worker rollouts; confirm the worker is connected to an AMQP Broker and subscribed to `document.ingest` and `tenant.cleanup`; call `/api/health`; inspect recent backend/worker/RabbitMQ logs for authentication, queue declaration, or connectivity errors.

- [ ] **Step 6: Final diff review without commit**

Run: `git diff --check`

Run: `git status --short`

Expected: no whitespace errors; all unrelated pre-existing changes remain intact and uncommitted.
