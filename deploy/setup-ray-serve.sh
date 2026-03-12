#!/usr/bin/env bash
# SeedCore RayService deployment helper for local Kind clusters.

set -euo pipefail
trap 'echo "🛑 Interrupted"; exit 1' INT TERM

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
TMP_DIR="$(mktemp -d)"

cleanup() {
  rm -rf "${TMP_DIR}"
}
trap cleanup EXIT

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

print_status() {
  local status="$1"
  local message="$2"
  case "${status}" in
    OK) echo -e "${GREEN}✅ ${message}${NC}" ;;
    WARN) echo -e "${YELLOW}⚠️  ${message}${NC}" ;;
    INFO) echo -e "${BLUE}ℹ️  ${message}${NC}" ;;
    *) echo -e "${RED}❌ ${message}${NC}" ;;
  esac
}

die() {
  print_status "ERROR" "$1"
  exit 1
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "'$1' is not installed or not on PATH"
}

is_true() {
  case "${1:-}" in
    1|true|TRUE|yes|YES|y|Y|on|ON) return 0 ;;
    *) return 1 ;;
  esac
}

usage() {
  local stable_service_default="${STABLE_SERVE_SVC_NAME:-${RS_NAME}-stable-svc}"
  cat <<EOF
Usage: $(basename "$0") [options]

Options:
  -n, --namespace <ns>          Kubernetes namespace (default: ${NAMESPACE:-seedcore-dev})
  -c, --cluster <name>          Kind cluster name (default: ${CLUSTER_NAME:-seedcore-dev})
  -i, --image <img:tag>         Ray image to deploy (default: ${RAY_IMAGE:-seedcore:latest})
  -r, --rayservice <path>       RayService manifest path
      --rayservice-name <name>  RayService metadata.name override
      --stable-service <name>   Stable head/serve service name override (default: ${stable_service_default})
      --env-file <path>         Env file used to create/update the secret
      --secret-name <name>      Secret name for env injection
      --worker-replicas <n>     Worker replica count override
      --skip-load               Skip loading the Docker image into Kind
      --skip-host-data-setup    Skip preparing the hostPath data directory
      --host-data-dir <path>    HostPath data directory (default: /tmp/seedcore-data)
  -h, --help                    Show this help
EOF
}

CLUSTER_NAME="${CLUSTER_NAME:-seedcore-dev}"
NAMESPACE="${NAMESPACE:-seedcore-dev}"
RAY_VERSION="${RAY_VERSION:-2.53.0}"
RAY_IMAGE="${RAY_IMAGE:-seedcore:latest}"
WORKER_REPLICAS="${WORKER_REPLICAS:-1}"
RS_NAME="${RS_NAME:-seedcore-svc}"
RAYSERVICE_FILE="${RAYSERVICE_FILE:-${SCRIPT_DIR}/rayservice.yaml}"
STABLE_SERVE_SVC_FILE="${STABLE_SERVE_SVC_FILE:-${SCRIPT_DIR}/ray-stable-svc.yaml}"
STABLE_SERVE_SVC_NAME="${STABLE_SERVE_SVC_NAME:-}"
ENV_FILE_PATH="${ENV_FILE_PATH:-${SCRIPT_DIR}/../docker/.env}"
SECRET_NAME="${SECRET_NAME:-seedcore-env-secret}"
HOST_DATA_DIR="${HOST_DATA_DIR:-/tmp/seedcore-data}"
SKIP_LOAD="${SKIP_LOAD:-false}"
SKIP_HOST_DATA_SETUP="${SKIP_HOST_DATA_SETUP:-false}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    -n|--namespace) NAMESPACE="$2"; shift 2 ;;
    -c|--cluster) CLUSTER_NAME="$2"; shift 2 ;;
    -i|--image) RAY_IMAGE="$2"; shift 2 ;;
    -r|--rayservice) RAYSERVICE_FILE="$2"; shift 2 ;;
    --rayservice-name) RS_NAME="$2"; shift 2 ;;
    --stable-service) STABLE_SERVE_SVC_NAME="$2"; shift 2 ;;
    --env-file) ENV_FILE_PATH="$2"; shift 2 ;;
    --secret-name) SECRET_NAME="$2"; shift 2 ;;
    --worker-replicas) WORKER_REPLICAS="$2"; shift 2 ;;
    --skip-load) SKIP_LOAD=true; shift ;;
    --skip-host-data-setup) SKIP_HOST_DATA_SETUP=true; shift ;;
    --host-data-dir) HOST_DATA_DIR="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) die "Unknown argument: $1" ;;
  esac
done

if [[ -z "${STABLE_SERVE_SVC_NAME}" ]]; then
  STABLE_SERVE_SVC_NAME="${RS_NAME}-stable-svc"
fi

render_top_level_metadata() {
  local src="$1"
  local dst="$2"
  local rendered_name="$3"
  local rendered_namespace="$4"

  awk -v name="${rendered_name}" -v namespace="${rendered_namespace}" '
    BEGIN { in_metadata = 0; metadata_done = 0 }
    !metadata_done && /^metadata:[[:space:]]*$/ { in_metadata = 1; print; next }
    in_metadata && /^  name:[[:space:]]*/ { print "  name: " name; next }
    in_metadata && /^  namespace:[[:space:]]*/ { print "  namespace: " namespace; next }
    in_metadata && /^spec:[[:space:]]*$/ { in_metadata = 0; metadata_done = 1; print; next }
    { print }
  ' "${src}" > "${dst}"
}

render_rayservice_manifest() {
  local src="$1"
  local dst="$2"
  local meta_tmp="${TMP_DIR}/rayservice-meta.yaml"

  render_top_level_metadata "${src}" "${meta_tmp}" "${RS_NAME}" "${NAMESPACE}"

  awk \
    -v ray_image="${RAY_IMAGE}" \
    -v ray_version="${RAY_VERSION}" \
    -v worker_replicas="${WORKER_REPLICAS}" '
    BEGIN { in_small_worker_group = 0 }
    /^    rayVersion:[[:space:]]*/ {
      print "    rayVersion: \"" ray_version "\""
      next
    }
    /^([[:space:]]*)image:[[:space:]]*/ {
      match($0, /^[[:space:]]*/)
      print substr($0, RSTART, RLENGTH) "image: " ray_image
      next
    }
    /^      - groupName:[[:space:]]*small[[:space:]]*$/ {
      in_small_worker_group = 1
      print
      next
    }
    in_small_worker_group && /^        replicas:[[:space:]]*[0-9]+[[:space:]]*$/ {
      print "        replicas: " worker_replicas
      in_small_worker_group = 0
      next
    }
    { print }
  ' "${meta_tmp}" > "${dst}"
}

ensure_kind_cluster() {
  if kind get clusters 2>/dev/null | grep -Fxq "${CLUSTER_NAME}"; then
    print_status "OK" "Kind cluster '${CLUSTER_NAME}' already exists"
    return 0
  fi

  print_status "INFO" "Creating Kind cluster '${CLUSTER_NAME}' with project mount..."
  CLUSTER_NAME="${CLUSTER_NAME}" "${SCRIPT_DIR}/setup-kind-only.sh"
  print_status "OK" "Kind cluster created"
}

ensure_namespace() {
  print_status "INFO" "Creating namespace '${NAMESPACE}' (if missing)..."
  kubectl create namespace "${NAMESPACE}" --dry-run=client -o yaml | kubectl apply -f - >/dev/null
  print_status "OK" "Namespace ready"
}

ensure_local_image() {
  docker image inspect "${RAY_IMAGE}" >/dev/null 2>&1 || die "Image ${RAY_IMAGE} not found locally. Build it first."

  local image_platform
  image_platform="$(docker image inspect "${RAY_IMAGE}" --format '{{.Architecture}}/{{.Os}}' 2>/dev/null || echo "unknown")"
  if [[ "${image_platform}" != "amd64/linux" && "${image_platform}" != "unknown" ]]; then
    print_status "WARN" "Image platform is ${image_platform}; Kind nodes usually expect amd64/linux"
  fi
}

load_image_into_kind() {
  local node
  local nodes
  local alt_image="${RAY_IMAGE}"
  local node_has_image=true

  if is_true "${SKIP_LOAD}"; then
    print_status "WARN" "Skipping image load (requested via SKIP_LOAD)"
    return 0
  fi

  ensure_local_image

  if [[ "${RAY_IMAGE}" != */* ]]; then
    alt_image="docker.io/library/${RAY_IMAGE}"
  fi

  nodes="$(kind get nodes --name "${CLUSTER_NAME}" 2>/dev/null || true)"
  if [[ -z "${nodes}" ]]; then
    node_has_image=false
  else
    for node in ${nodes}; do
      if ! docker exec "${node}" sh -lc "
        refs=\$(ctr -n k8s.io images ls -q 2>/dev/null || true)
        echo \"\$refs\" | grep -Fxq '${alt_image}' || echo \"\$refs\" | grep -Fxq '${RAY_IMAGE}'
      " >/dev/null 2>&1; then
        node_has_image=false
        break
      fi
    done
  fi

  if [[ "${node_has_image}" == "true" ]]; then
    print_status "OK" "Image ${RAY_IMAGE} already present on all Kind nodes"
    return 0
  fi

  print_status "INFO" "Loading image ${RAY_IMAGE} into Kind cluster ${CLUSTER_NAME}..."
  kind load docker-image "${RAY_IMAGE}" --name "${CLUSTER_NAME}"
  print_status "OK" "Image loaded into Kind nodes"
}

ensure_host_data_dir() {
  if is_true "${SKIP_HOST_DATA_SETUP}"; then
    print_status "WARN" "Skipping host data directory setup"
    return 0
  fi

  local sudo_cmd=()
  if [[ ! -d "${HOST_DATA_DIR}" || ! -w "${HOST_DATA_DIR}" ]]; then
    if command -v sudo >/dev/null 2>&1; then
      sudo_cmd=(sudo)
    elif [[ ! -w "$(dirname "${HOST_DATA_DIR}")" ]]; then
      die "Need sudo access or a writable HOST_DATA_DIR to prepare ${HOST_DATA_DIR}"
    fi
  fi

  print_status "INFO" "Preparing host data directory ${HOST_DATA_DIR}..."
  "${sudo_cmd[@]}" mkdir -p "${HOST_DATA_DIR}"
  "${sudo_cmd[@]}" chown -R 1000:1000 "${HOST_DATA_DIR}" >/dev/null 2>&1 || true
  "${sudo_cmd[@]}" chmod -R 755 "${HOST_DATA_DIR}" >/dev/null 2>&1 || true
  print_status "OK" "Host data directory ready"
}

install_kuberay() {
  print_status "INFO" "Installing/upgrading KubeRay operator..."
  helm repo add kuberay https://ray-project.github.io/kuberay-helm/ >/dev/null 2>&1 || true
  helm repo update >/dev/null

  if ! kubectl get namespace kuberay-system >/dev/null 2>&1; then
    helm install kuberay-operator kuberay/kuberay-operator \
      --namespace kuberay-system \
      --create-namespace \
      --wait
  else
    helm upgrade kuberay-operator kuberay/kuberay-operator \
      --namespace kuberay-system \
      --wait >/dev/null
  fi

  kubectl wait --for=condition=ready pod \
    -l app.kubernetes.io/name=kuberay-operator \
    -n kuberay-system \
    --timeout=300s >/dev/null
  print_status "OK" "KubeRay operator ready"
}

create_env_secret() {
  if [[ ! -f "${ENV_FILE_PATH}" ]]; then
    print_status "WARN" "${ENV_FILE_PATH} not found. Skipping secret creation."
    return 0
  fi

  print_status "INFO" "Creating/updating secret '${SECRET_NAME}' from ${ENV_FILE_PATH}..."
  kubectl -n "${NAMESPACE}" create secret generic "${SECRET_NAME}" \
    --from-env-file="${ENV_FILE_PATH}" \
    --dry-run=client \
    -o yaml | kubectl apply -f - >/dev/null

  local encoded_pkg_path
  encoded_pkg_path="$(printf '%s' '/app/data/opt/pkg/policy_rules.wasm' | base64 | tr -d '\n')"
  kubectl -n "${NAMESPACE}" patch secret "${SECRET_NAME}" \
    --type merge \
    -p "{\"data\":{\"PKG_WASM_PATH\":\"${encoded_pkg_path}\"}}" >/dev/null
  print_status "OK" "Secret '${SECRET_NAME}' ready"
}

apply_rendered_manifests() {
  [[ -f "${RAYSERVICE_FILE}" ]] || die "RayService file not found: ${RAYSERVICE_FILE}"
  [[ -f "${STABLE_SERVE_SVC_FILE}" ]] || die "Stable service file not found: ${STABLE_SERVE_SVC_FILE}"

  local rendered_rayservice="${TMP_DIR}/rayservice.rendered.yaml"
  local rendered_stable_svc="${TMP_DIR}/ray-stable-svc.rendered.yaml"

  render_rayservice_manifest "${RAYSERVICE_FILE}" "${rendered_rayservice}"
  render_top_level_metadata "${STABLE_SERVE_SVC_FILE}" "${rendered_stable_svc}" "${STABLE_SERVE_SVC_NAME}" "${NAMESPACE}"

  print_status "INFO" "Applying RayService manifest..."
  kubectl apply -f "${rendered_rayservice}" >/dev/null

  print_status "INFO" "Applying stable Ray head/serve service..."
  kubectl apply -f "${rendered_stable_svc}" >/dev/null
}

wait_for_head_pod() {
  local head_pod=""
  local attempt

  print_status "INFO" "Waiting for RayService '${RS_NAME}'..."
  kubectl -n "${NAMESPACE}" get rayservice "${RS_NAME}" >/dev/null

  for attempt in $(seq 1 120); do
    head_pod="$(kubectl -n "${NAMESPACE}" get pods \
      -l ray.io/node-type=head \
      --no-headers 2>/dev/null | awk -v name="${RS_NAME}" '$1 ~ name {print $1; exit}')"
    if [[ -n "${head_pod}" ]]; then
      break
    fi
    sleep 5
  done

  [[ -n "${head_pod}" ]] || die "Ray head pod for ${RS_NAME} was not created in time"

  print_status "INFO" "Waiting for head pod '${head_pod}' to become Ready..."
  kubectl -n "${NAMESPACE}" wait --for=condition=ready "pod/${head_pod}" --timeout=900s >/dev/null
  echo "${head_pod}"
}

setup_pkg_wasm_placeholder() {
  local head_pod="$1"
  local attempt

  print_status "INFO" "Ensuring PKG WASM placeholder exists in ${head_pod}..."
  sleep 15
  for attempt in 1 2 3; do
    if kubectl exec -n "${NAMESPACE}" "${head_pod}" -- bash -lc '
      mkdir -p /app/data/opt/pkg
      cat > /app/data/opt/pkg/policy_rules.wasm << "WASM_EOF"
# Dummy PKG WASM for testing
# Replace with a real WASM binary in production.
WASM_EOF
      chmod 644 /app/data/opt/pkg/policy_rules.wasm
    ' >/dev/null 2>&1; then
      print_status "OK" "PKG WASM placeholder created"
      return 0
    fi
    sleep 10
  done

  print_status "WARN" "Could not create PKG WASM placeholder in ${head_pod}"
}

print_summary() {
  local head_pod="$1"

  print_status "INFO" "RayService status summary:"
  kubectl -n "${NAMESPACE}" get rayservice "${RS_NAME}" -o yaml | sed -n '/^status:/,$p' | head -n 120 || true

  print_status "INFO" "Relevant services:"
  kubectl -n "${NAMESPACE}" get svc "${STABLE_SERVE_SVC_NAME}" "${RS_NAME}-head-svc" "${RS_NAME}-serve-svc" 2>/dev/null || true

  echo
  print_status "OK" "Ray deployment complete"
  echo "   Kind cluster:      ${CLUSTER_NAME}"
  echo "   Namespace:         ${NAMESPACE}"
  echo "   RayService:        ${RS_NAME}"
  echo "   Ray image:         ${RAY_IMAGE}"
  echo "   Stable service:    ${STABLE_SERVE_SVC_NAME}"
  echo "   Head pod:          ${head_pod}"
  echo "   Host data dir:     ${HOST_DATA_DIR}"
  echo
  echo "   Dashboard:         kubectl -n ${NAMESPACE} port-forward svc/${STABLE_SERVE_SVC_NAME} 8265:8265"
  echo "   Ray client:        kubectl -n ${NAMESPACE} port-forward svc/${STABLE_SERVE_SVC_NAME} 10001:10001"
  echo "   Serve HTTP:        kubectl -n ${NAMESPACE} port-forward svc/${STABLE_SERVE_SVC_NAME} 8000:8000"
  echo "   Replace PKG WASM:  kubectl cp policy_rules.wasm ${NAMESPACE}/${head_pod}:/app/data/opt/pkg/policy_rules.wasm"
}

main() {
  require_cmd kind
  require_cmd kubectl
  require_cmd helm
  require_cmd docker
  require_cmd base64

  print_status "INFO" "Setting up Kind + KubeRay + RayService"

  ensure_kind_cluster
  kubectl cluster-info --context "kind-${CLUSTER_NAME}" >/dev/null
  ensure_namespace
  load_image_into_kind
  ensure_host_data_dir
  install_kuberay
  create_env_secret
  apply_rendered_manifests

  local head_pod
  head_pod="$(wait_for_head_pod)"
  setup_pkg_wasm_placeholder "${head_pod}"
  print_summary "${head_pod}"
}

main "$@"
