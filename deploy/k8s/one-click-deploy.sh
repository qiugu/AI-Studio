#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
K8S_DEPLOY_HOST="${K8S_DEPLOY_HOST:-192.168.99.131}"
K8S_DEPLOY_USER="${K8S_DEPLOY_USER:-qiugu}"
K8S_DEPLOY_SSH_KEY="${K8S_DEPLOY_SSH_KEY:-}"
REMOTE_TARGET="${K8S_DEPLOY_USER}@${K8S_DEPLOY_HOST}"
REMOTE_DIR=""
LOCAL_ENV_FILE=""

cd "${PROJECT_ROOT}"

usage() {
  cat <<'EOF'
Usage: ./deploy/k8s/one-click-deploy.sh [up|build|deploy|status] [--skip-build]

up            upload the project, build/import images on the server, deploy
build         upload the project and build/import images on the server only
deploy        upload the project and run the server-side deployment only
status        show the Kubernetes status on the deployment server
--skip-build  for the default up command, skip remote image build/import

Local requirements: ssh and tar.
Server requirements: Docker, ctr, kubectl, sudo, openssl, and base64.
Configure K8S_DEPLOY_HOST, K8S_DEPLOY_USER, and optionally
K8S_DEPLOY_SSH_KEY when the defaults do not match the target server.
EOF
}

die() {
  echo "one-click-deploy.sh: $*" >&2
  exit 1
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || die "${1} is required on the local machine"
}

ssh_options=()
if [[ -n "${K8S_DEPLOY_SSH_KEY}" ]]; then
  ssh_options+=(-i "${K8S_DEPLOY_SSH_KEY}")
fi

ssh_remote() {
  ssh "${ssh_options[@]}" -o BatchMode=yes "${REMOTE_TARGET}" "$@"
}

read_env_value() {
  local key="$1"
  local env_file="$2"
  awk -F= -v key="${key}" '$1 == key {sub(/^[^=]*=/, ""); print; exit}' "${env_file}" \
    | sed 's/[[:space:]]*#.*$//'
}

local_env_value() {
  local key="$1"
  local value=""
  if [[ -n "${!key+x}" ]]; then
    value="${!key}"
  elif [[ -f "${PROJECT_ROOT}/.env" ]]; then
    value="$(read_env_value "${key}" "${PROJECT_ROOT}/.env")"
  fi
  printf '%s' "${value}"
}

prepare_env_file() {
  local key value
  LOCAL_ENV_FILE="$(mktemp)"
  umask 077
  for key in PLATFORM_ADMIN_EMAIL PLATFORM_ADMIN_PASSWORD \
    MEMBERSHIP_DUAL_WRITE_ENABLED MEMBERSHIP_READ_MODE; do
    value="$(local_env_value "${key}")"
    [[ -n "${value}" ]] && printf '%s=%q\n' "${key}" "${value}" >>"${LOCAL_ENV_FILE}"
  done
}

cleanup() {
  if [[ -n "${LOCAL_ENV_FILE}" && -f "${LOCAL_ENV_FILE}" ]]; then
    rm -f "${LOCAL_ENV_FILE}"
  fi
  if [[ -n "${REMOTE_DIR}" ]]; then
    ssh_remote "case \"${REMOTE_DIR}\" in /tmp/ai-studio-k8s-deploy.*) rm -rf -- \"${REMOTE_DIR}\" ;; esac" \
      >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

create_remote_workspace() {
  REMOTE_DIR="$(ssh_remote 'mktemp -d /tmp/ai-studio-k8s-deploy.XXXXXX')"
  [[ "${REMOTE_DIR}" == /tmp/ai-studio-k8s-deploy.* ]] || \
    die "server returned an unsafe temporary directory"
}

upload_project() {
  require_command ssh
  require_command tar
  if [[ -n "${K8S_DEPLOY_SSH_KEY}" && ! -f "${K8S_DEPLOY_SSH_KEY}" ]]; then
    die "SSH key not found: ${K8S_DEPLOY_SSH_KEY}"
  fi

  echo "Creating temporary workspace on ${REMOTE_TARGET}..."
  create_remote_workspace
  echo "Uploading project to ${REMOTE_TARGET}:${REMOTE_DIR}..."
  tar \
    --exclude=.git \
    --exclude=.venv \
    --exclude=.env \
    --exclude=frontend/node_modules \
    --exclude=frontend/dist \
    --exclude='*.pyc' \
    -czf - -C "${PROJECT_ROOT}" . \
    | ssh_remote "tar -xzf - -C '${REMOTE_DIR}'"

  prepare_env_file
  ssh_remote "cat > '${REMOTE_DIR}/.env.k8s' && chmod 600 '${REMOTE_DIR}/.env.k8s'" \
    <"${LOCAL_ENV_FILE}"
}

run_remote() {
  local build_images="$1"
  local command=""

  if [[ "${build_images}" == "true" ]]; then
    command+='chmod +x deploy/k8s/build-images.sh deploy/k8s/deploy.sh && '
    command+='bash deploy/k8s/build-images.sh && '
  fi
  command+='bash deploy/k8s/deploy.sh'
  echo "Executing deployment on ${REMOTE_TARGET}..."
  ssh_remote "cd '${REMOTE_DIR}' && if [ -s .env.k8s ]; then set -a; . ./.env.k8s; set +a; fi; ${command}"
}

run_remote_build() {
  echo "Executing image build/import on ${REMOTE_TARGET}..."
  ssh_remote "cd '${REMOTE_DIR}' && chmod +x deploy/k8s/build-images.sh && bash deploy/k8s/build-images.sh"
}

run_remote_status() {
  require_command ssh
  ssh_remote "kubectl -n ai-studio get pods,services,persistentvolumeclaims"
}

command_name="up"
skip_build="false"
for arg in "$@"; do
  case "${arg}" in
    up|build|deploy|status) command_name="${arg}" ;;
    --skip-build) skip_build="true" ;;
    -h|--help) usage; exit 0 ;;
    *) usage >&2; die "unknown argument: ${arg}" ;;
  esac
done

if [[ "${skip_build}" == "true" && "${command_name}" != "up" ]]; then
  usage >&2
  die "--skip-build can only be used with the default up command"
fi

case "${command_name}" in
  status)
    run_remote_status
    ;;
  build|deploy|up)
    upload_project
    case "${command_name}" in
      build) run_remote_build ;;
      deploy) run_remote false ;;
      up)
        if [[ "${skip_build}" == "true" ]]; then
          run_remote false
        else
          run_remote true
        fi
        ;;
    esac
    ;;
esac
