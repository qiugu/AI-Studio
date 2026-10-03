#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NAMESPACE="ai-studio"
SECRET_NAME="ai-studio-secrets"
SECRET_FILE=""

cleanup() {
  if [[ -n "${SECRET_FILE}" && -f "${SECRET_FILE}" ]]; then
    rm -f "${SECRET_FILE}"
  fi
}
trap cleanup EXIT

command -v kubectl >/dev/null || { echo "kubectl is required" >&2; exit 1; }
command -v openssl >/dev/null || { echo "openssl is required" >&2; exit 1; }

sudo install -d -m 0777 \
  /var/lib/ai-studio/mysql \
  /var/lib/ai-studio/redis \
  /var/lib/ai-studio/qdrant \
  /var/lib/ai-studio/uploads \
  /var/lib/ai-studio/hf-cache

kubectl apply -f "${SCRIPT_DIR}/namespace.yaml"

if ! kubectl --namespace "${NAMESPACE}" get secret "${SECRET_NAME}" >/dev/null 2>&1; then
  echo "Creating Kubernetes Secret ${SECRET_NAME}..."
  umask 077
  SECRET_FILE="$(mktemp)"
  mysql_root_password="$(openssl rand -hex 24)"
  mysql_password="$(openssl rand -hex 24)"
  jwt_secret_key="$(openssl rand -hex 32)"
  fernet_key="$(openssl rand -base64 32 | tr '+/' '-_' | tr -d '\n')"
  printf '%s\n' \
    "MYSQL_ROOT_PASSWORD=${mysql_root_password}" \
    "MYSQL_PASSWORD=${mysql_password}" \
    "DATABASE_PASSWORD=${mysql_password}" \
    "JWT_SECRET_KEY=${jwt_secret_key}" \
    "FERNET_KEY=${fernet_key}" >"${SECRET_FILE}"
  kubectl --namespace "${NAMESPACE}" create secret generic "${SECRET_NAME}" \
    --from-env-file="${SECRET_FILE}"
else
  echo "Reusing existing Kubernetes Secret ${SECRET_NAME}."
fi

kubectl apply -k "${SCRIPT_DIR}"

for deployment in backend celery-worker frontend; do
  kubectl --namespace "${NAMESPACE}" rollout restart "deployment/${deployment}"
done

kubectl --namespace "${NAMESPACE}" wait \
  --for=jsonpath='{.status.phase}'=Bound pvc --all --timeout=180s

for statefulset in mysql redis qdrant; do
  kubectl --namespace "${NAMESPACE}" rollout status "statefulset/${statefulset}" --timeout=600s
done

for deployment in backend celery-worker frontend; do
  kubectl --namespace "${NAMESPACE}" rollout status "deployment/${deployment}" --timeout=900s
done

kubectl --namespace "${NAMESPACE}" get pods,services,persistentvolumeclaims
echo "AI-Studio is available at http://192.168.99.131:30080"
