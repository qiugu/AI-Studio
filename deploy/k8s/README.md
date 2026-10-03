# Kubernetes deployment

Kubernetes is an additional deployment option for AI-Studio. It does not
replace local development or the existing Docker Compose workflow.

This deployment targets the single ARM64 node `k8s-master` at `192.168.99.131`.
It uses retained local persistent volumes below `/var/lib/ai-studio` and exposes
only the frontend through NodePort `30080`.

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

The first run creates `ai-studio-secrets` with generated database, JWT, and
Fernet keys. Later runs reuse that Secret so existing database credentials and
encrypted provider keys remain valid.

## Verify

```bash
kubectl -n ai-studio get pods,svc,pvc
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
kubectl -n ai-studio logs statefulset/mysql --tail=100
```

## Roll back application workloads

```bash
kubectl -n ai-studio rollout undo deployment/backend
kubectl -n ai-studio rollout undo deployment/celery-worker
kubectl -n ai-studio rollout undo deployment/frontend
```

Deleting workloads does not delete the host data. Persistent volumes use the
`Retain` policy; do not remove `/var/lib/ai-studio` unless permanent data loss
is intended.
