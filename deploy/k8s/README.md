# Kubernetes deployment

Kubernetes is an additional deployment option for AI-Studio. It does not
replace local development or the existing Docker Compose workflow.

This deployment targets the current two-node cluster:

- `k8s-master` — ARM64, `192.168.99.131` on the management network and
  `192.168.1.11` on the Calico/node network;
- `k8s-worker-01` — AMD64, `192.168.1.10`.

The checked-in local image workflow builds ARM64 images and all workloads are
therefore explicitly scheduled to ARM64 nodes. The worker remains available for
system services and future multi-architecture application images. Do not remove
the architecture selectors until images are published as a verified AMD64/ARM64
multi-architecture manifest.

Stateful workloads and application uploads use retained local persistent volumes
below `/var/lib/ai-studio` on `k8s-master`. The frontend is exposed through
NodePort `30080`.

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

`build-images.sh` uses the repository root for the backend image. It does not
build an AMD64 image; an AMD64 worker requires a registry-backed BuildKit
workflow such as `docker buildx build --platform linux/amd64,linux/arm64
--push ...`, followed by a manifest/image reference change and a staged rollout.

Before applying a change, render and inspect the complete manifest:

```bash
kubectl kustomize deploy/k8s > /tmp/ai-studio-k8s-rendered.yaml
kubectl apply --dry-run=server -k deploy/k8s
```

`deploy.sh` performs a read-only preflight first. It requires at least one Ready
ARM64 node and waits for all `k8s-app=calico-node` Pods to be Ready, then applies
the resources and waits for the workload rollouts.

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
kubectl get nodes -o wide
kubectl -n kube-system get pods -l k8s-app=calico-node -o wide
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

## Network and policy boundaries

The current audit found both nodes Ready, Calico BGP Established, a reachable
TCP/179 peer, and the expected PodCIDR route. The worker join also produced
transient Calico BGP-not-established events, so node-network readiness is now a
deployment preflight rather than an assumption.

This is a dual-NIC setup on `k8s-master`. Calico must select the `192.168.1.x`
interface for node-to-node traffic. Configure the Calico installation with an
explicit `IP_AUTODETECTION_METHOD`, for example `can-reach=192.168.1.10` or an
interface-specific method that resolves to `enp26s0` on the master. Validate the
corresponding worker setting resolves to `192.168.1.10` on `enp0s3`. The node
firewall/network must permit TCP 179 and Calico IP-in-IP (IP protocol 4) between
the node-network addresses, in addition to Kubernetes API and DNS traffic.

The Kubernetes `NetworkPolicy` resources in `networkpolicy.yaml` apply an
ingress default-deny policy inside `ai-studio`
and then allows NodePort traffic to the frontend, frontend/worker traffic to the
API, and backend/worker traffic to MySQL, Redis, RabbitMQ, and Qdrant. It does
not add egress isolation, so configured LLM, embedding, Ollama, and DNS calls
remain available.

The checked-in StatefulSets each have one replica because local RWO volumes are
bound to `k8s-master`. This separates the application definition from the
AMD64 worker but is not highly available: MySQL, RabbitMQ, Qdrant, Redis, and
uploads each have a single local failure domain. Enterprise HA requires managed
MySQL/Qdrant/RabbitMQ/Redis or replicated storage; RabbitMQ HA specifically
requires a managed service or at least three nodes across failure domains.
Point `RABBITMQ_HOST` and the Secret-backed credentials at that service before
removing the in-cluster broker.

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
