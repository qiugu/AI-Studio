# Kubernetes deployment

Kubernetes is an additional deployment option for AI-Studio. It does not
replace local development or the existing Docker Compose workflow.

This deployment targets the single ARM64 node `k8s-master` at `192.168.99.131`.
It uses retained local persistent volumes below `/var/lib/ai-studio` and exposes
only the frontend through NodePort `30080`.

Redis is dedicated to cache, rate limiting, and token revocation. RabbitMQ is
the Celery Broker and stores the durable `default`, `document.ingest`, and
`tenant.cleanup` quorum queues. Task business status remains in MySQL; no
Celery result backend is enabled.

## Deploy

Run on the target VM from the project root:

```bash
chmod +x deploy/k8s/build-images.sh deploy/k8s/deploy.sh
./deploy/k8s/build-images.sh
./deploy/k8s/deploy.sh
```

If Docker Hub is unavailable on the target VM, build the two ARM64 images on
another ARM64 Docker host, transfer their `docker save` archives, and import
them with `sudo ctr --namespace k8s.io images import <archive>` before running
`deploy.sh`.

The first run creates `ai-studio-secrets` with generated database, RabbitMQ,
JWT, and Fernet keys. Later runs reuse that Secret so existing database
credentials, Broker credentials, and encrypted provider keys remain valid.
When upgrading an older installation, `deploy.sh` patches only missing
RabbitMQ keys and does not rotate existing database, JWT, or Fernet values.

To create the initial platform administrator, export both values before the
first deployment:

```bash
export PLATFORM_ADMIN_EMAIL='platform-admin@example.com'
read -rsp 'Initial platform admin password: ' PLATFORM_ADMIN_PASSWORD; echo
export PLATFORM_ADMIN_PASSWORD
./deploy/k8s/deploy.sh
```

The deploy script stores them in the Kubernetes Secret. After the backend
deployment is healthy and its migration init container has completed, the
script creates `job/bootstrap-platform-admin` and waits for it to finish. The
Job runs `scripts/bootstrap_platform_admin.py` once to create a dedicated
system tenant and the administrator account. This step is idempotent: it does
not reset an existing platform administrator's password.
If both values are omitted, account creation is skipped; if only one is set,
deployment stops. The script reuses an existing Secret, so changing exported
values later does not change the stored credentials or account password.
Use a unique password and restrict Secret read access; for production, inject
credentials through an external Secret manager rather than shell history.

`deploy.sh` runs this Job automatically. To run it manually after the backend
is up and migrations have completed:

```bash
kubectl -n ai-studio apply -f deploy/k8s/bootstrap-platform-admin-job.yaml
kubectl -n ai-studio wait --for=condition=complete job/bootstrap-platform-admin --timeout=300s
```

The completed Job is retained, so later deploys do not run it again. To retry
after fixing credentials or a failed run, delete it and run `deploy.sh` again:

```bash
kubectl -n ai-studio delete job bootstrap-platform-admin --ignore-not-found
./deploy/k8s/deploy.sh
```

## Verify

```bash
kubectl -n ai-studio get pods,svc,pvc
kubectl -n ai-studio exec statefulset/rabbitmq -- rabbitmq-diagnostics -q ping
kubectl -n ai-studio exec statefulset/rabbitmq -- rabbitmqctl list_queues name type messages consumers
curl -fsS http://192.168.99.131:30080/
curl -fsS http://192.168.99.131:30080/api/health
```

- Console: `http://192.168.99.131:30080`
- Swagger: `http://192.168.99.131:30080/docs`
- Health: `http://192.168.99.131:30080/api/health`

## Logs

```bash
kubectl -n ai-studio logs deployment/backend --tail=100
kubectl -n ai-studio logs deployment/celery-worker --tail=100
kubectl -n ai-studio logs statefulset/rabbitmq --tail=100
kubectl -n ai-studio logs statefulset/mysql --tail=100
```

The checked-in StatefulSet has one RabbitMQ replica because this repository's
Kubernetes target has one node. It separates Broker and cache failure domains,
but it is not highly available. Enterprise HA requires a managed RabbitMQ
service or at least three RabbitMQ nodes placed across failure domains; point
`RABBITMQ_HOST` and the Secret-backed credentials at that cluster before
removing the in-cluster StatefulSet.

Before rolling back to a Redis Broker, stop task publishers and drain RabbitMQ.
Broker queues are not migrated automatically between transports.

## Roll back application workloads

```bash
kubectl -n ai-studio rollout undo deployment/backend
kubectl -n ai-studio rollout undo deployment/celery-worker
kubectl -n ai-studio rollout undo deployment/frontend
```

Deleting workloads does not delete the host data. Persistent volumes use the
`Retain` policy; do not remove `/var/lib/ai-studio` unless permanent data loss
is intended.
