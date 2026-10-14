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
command -v base64 >/dev/null || { echo "base64 is required" >&2; exit 1; }

membership_dual_write_enabled="${MEMBERSHIP_DUAL_WRITE_ENABLED:-false}"
membership_read_mode="${MEMBERSHIP_READ_MODE:-legacy}"
case "${membership_dual_write_enabled,,}" in
  true|false) ;;
  *)
    echo "MEMBERSHIP_DUAL_WRITE_ENABLED must be true or false." >&2
    exit 1
    ;;
esac
case "${membership_read_mode,,}" in
  legacy|shadow|membership) ;;
  *)
    echo "MEMBERSHIP_READ_MODE must be legacy, shadow, or membership." >&2
    exit 1
    ;;
esac
if [[ "${membership_read_mode,,}" != "legacy" && "${membership_dual_write_enabled,,}" != "true" ]]; then
  echo "MEMBERSHIP_READ_MODE=${membership_read_mode} requires MEMBERSHIP_DUAL_WRITE_ENABLED=true." >&2
  exit 1
fi

patch_secret_key_if_missing() {
  local key="$1"
  local value="$2"
  local current encoded

  current="$(kubectl --namespace "${NAMESPACE}" get secret "${SECRET_NAME}" \
    -o "jsonpath={.data.${key}}" 2>/dev/null || true)"
  if [[ -n "${current}" ]]; then
    return
  fi

  encoded="$(printf '%s' "${value}" | base64 | tr -d '\n')"
  kubectl --namespace "${NAMESPACE}" patch secret "${SECRET_NAME}" \
    --type merge \
    -p "{\"data\":{\"${key}\":\"${encoded}\"}}"
}

if [[ -n "${PLATFORM_ADMIN_EMAIL:-}" && -z "${PLATFORM_ADMIN_PASSWORD:-}" ]] || \
   [[ -z "${PLATFORM_ADMIN_EMAIL:-}" && -n "${PLATFORM_ADMIN_PASSWORD:-}" ]]; then
  echo "Set both PLATFORM_ADMIN_EMAIL and PLATFORM_ADMIN_PASSWORD, or leave both unset." >&2
  exit 1
fi
if [[ -n "${PLATFORM_ADMIN_PASSWORD:-}" && ${#PLATFORM_ADMIN_PASSWORD} -lt 12 ]]; then
  echo "PLATFORM_ADMIN_PASSWORD must contain at least 12 characters." >&2
  exit 1
fi

sudo install -d -m 0777 \
  /var/lib/ai-studio/mysql \
  /var/lib/ai-studio/redis \
  /var/lib/ai-studio/rabbitmq \
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
  rabbitmq_password="$(openssl rand -hex 32)"
  printf '%s\n' \
    "MYSQL_ROOT_PASSWORD=${mysql_root_password}" \
    "MYSQL_PASSWORD=${mysql_password}" \
    "DATABASE_PASSWORD=${mysql_password}" \
    "JWT_SECRET_KEY=${jwt_secret_key}" \
    "FERNET_KEY=${fernet_key}" \
    "RABBITMQ_USERNAME=ai_studio" \
    "RABBITMQ_PASSWORD=${rabbitmq_password}" \
    "RABBITMQ_VHOST=ai-studio" >"${SECRET_FILE}"
  if [[ -n "${PLATFORM_ADMIN_EMAIL:-}" ]]; then
    printf '%s\n' \
      "PLATFORM_ADMIN_EMAIL=${PLATFORM_ADMIN_EMAIL}" \
      "PLATFORM_ADMIN_PASSWORD=${PLATFORM_ADMIN_PASSWORD}" >>"${SECRET_FILE}"
  fi
  kubectl --namespace "${NAMESPACE}" create secret generic "${SECRET_NAME}" \
    --from-env-file="${SECRET_FILE}"
else
  echo "Reusing existing Kubernetes Secret ${SECRET_NAME}."
  # 兼容迁移前已存在的 Secret：只补 RabbitMQ 缺失键，不轮换数据库/JWT/Fernet。
  rabbitmq_password="$(openssl rand -hex 32)"
  patch_secret_key_if_missing "RABBITMQ_USERNAME" "ai_studio"
  patch_secret_key_if_missing "RABBITMQ_PASSWORD" "${rabbitmq_password}"
  patch_secret_key_if_missing "RABBITMQ_VHOST" "ai-studio"
fi

kubectl apply -k "${SCRIPT_DIR}"

# Keep the rollout switch in the ConfigMap so API and Celery consume the same
# decision.  The backend is restarted below after the patch; legacy remains the
# safe default when no rollout variables are supplied.
kubectl --namespace "${NAMESPACE}" patch configmap ai-studio-config \
  --type merge \
  -p "{\"data\":{\"MEMBERSHIP_DUAL_WRITE_ENABLED\":\"${membership_dual_write_enabled,,}\",\"MEMBERSHIP_READ_MODE\":\"${membership_read_mode,,}\"}}"

kubectl --namespace "${NAMESPACE}" rollout restart deployment/backend

kubectl --namespace "${NAMESPACE}" wait \
  --for=jsonpath='{.status.phase}'=Bound pvc --all --timeout=180s

for statefulset in mysql redis rabbitmq qdrant; do
  kubectl --namespace "${NAMESPACE}" rollout status "statefulset/${statefulset}" --timeout=600s
done

kubectl --namespace "${NAMESPACE}" rollout status deployment/backend --timeout=900s

# Run first-admin bootstrap as a durable one-shot Job, after backend init
# containers have completed the schema migration. A completed Job is retained
# and will not run again on subsequent deploys.
kubectl --namespace "${NAMESPACE}" apply -f "${SCRIPT_DIR}/bootstrap-platform-admin-job.yaml"
kubectl --namespace "${NAMESPACE}" wait \
  --for=condition=complete job/bootstrap-platform-admin \
  --timeout=300s

for deployment in celery-worker frontend; do
  kubectl --namespace "${NAMESPACE}" rollout restart "deployment/${deployment}"
  kubectl --namespace "${NAMESPACE}" rollout status "deployment/${deployment}" --timeout=900s
done

kubectl --namespace "${NAMESPACE}" get pods,services,persistentvolumeclaims
echo "AI-Studio is available at http://192.168.99.131:30080"
