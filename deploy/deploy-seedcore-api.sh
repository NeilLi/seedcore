#!/usr/bin/env bash
# deploy/deploy-seedcore-api.sh — SeedCore API deployer for Kind/Kubernetes
set -euo pipefail

# Resolve script directory for robust relative paths
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ---- Colors / status
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
log() { local lvl=$1 msg=$2; case "$lvl" in
  OK) echo -e "${GREEN}✅ $msg${NC}";;
  WARN) echo -e "${YELLOW}⚠️  $msg${NC}";;
  INFO) echo -e "${BLUE}ℹ️  $msg${NC}";;
  ERR) echo -e "${RED}❌ $msg${NC}";;
esac; }

# ---- Defaults (env-overridable)
CLUSTER_NAME="${CLUSTER_NAME:-seedcore-dev}"
NAMESPACE="${NAMESPACE:-seedcore-dev}"
SERVICE_NAME="${SERVICE_NAME:-seedcore-api}"
DEPLOY_NAME="${DEPLOY_NAME:-seedcore-api}"
API_IMAGE="${API_IMAGE:-seedcore:latest}"
REPLICAS="${REPLICAS:-1}"
ENV_FILE="${ENV_FILE:-${SCRIPT_DIR}/../docker/.env}"
ENV_MODE="${ENV_MODE:-auto}"                 # auto|cm|secret|file
SKIP_LOAD="${SKIP_LOAD:-0}"
PORT_FORWARD="${PORT_FORWARD:-0}"
LOCAL_PORT="${LOCAL_PORT:-8002}"

# Normalize boolean-ish env vars to 0/1
case "${SKIP_LOAD}" in
  1|true|TRUE|yes|YES|y|Y) SKIP_LOAD=1 ;;
  0|false|FALSE|no|NO|n|N|"") SKIP_LOAD=0 ;;
  *) echo "Invalid SKIP_LOAD='${SKIP_LOAD}' (use 0/1/true/false)"; exit 1 ;;
esac

case "${PORT_FORWARD}" in
  1|true|TRUE|yes|YES|y|Y) PORT_FORWARD=1 ;;
  0|false|FALSE|no|NO|n|N|"") PORT_FORWARD=0 ;;
  *) echo "Invalid PORT_FORWARD='${PORT_FORWARD}' (use 0/1/true/false)"; exit 1 ;;
esac

# Ray + misc
RAY_HEAD_SVC="${RAY_HEAD_SVC:-seedcore-svc-stable-svc}"
RAY_HEAD_PORT="${RAY_HEAD_PORT:-10001}"
SEEDCORE_NS="${SEEDCORE_NS:-seedcore-dev}"
HOSTPATH_PROJECT="${HOSTPATH_PROJECT:-/project}"

YAML_PATH="${YAML_PATH:-${SCRIPT_DIR}/k8s/seedcore-api.yaml}"

usage() {
  cat <<USAGE
Usage: $(basename "$0") [options]
  -n, --namespace <ns>       Namespace (default: $NAMESPACE)
  -c, --cluster <name>       Kind cluster (default: $CLUSTER_NAME)
  -i, --image <img:tag>      API image (default: $API_IMAGE)
  -e, --env <path>           .env file for fallback ConfigMap (default: $ENV_FILE)
  -r, --replicas <n>         Replicas (default: $REPLICAS)
      --skip-load            Skip 'kind load docker-image'
      --port-forward         Port-forward svc/${SERVICE_NAME} to localhost:${LOCAL_PORT}
      --env-mode <m>         Env wiring: auto|cm|secret|file (default: $ENV_MODE)
      --delete               Delete resources and exit
  -y, --yaml <path>          Path to templated YAML (default: $YAML_PATH)
  -h, --help                 Help
USAGE
}

DELETE_ONLY=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    -n|--namespace) NAMESPACE="$2"; shift 2;;
    -c|--cluster) CLUSTER_NAME="$2"; shift 2;;
    -i|--image) API_IMAGE="$2"; shift 2;;
    -e|--env) ENV_FILE="$2"; shift 2;;
    -r|--replicas) REPLICAS="$2"; shift 2;;
    --skip-load) SKIP_LOAD=1; shift;;
    --port-forward) PORT_FORWARD=1; shift;;
    --env-mode) ENV_MODE="$2"; shift 2;;
    --delete) DELETE_ONLY=1; shift;;
    -y|--yaml) YAML_PATH="$2"; shift 2;;
    -h|--help) usage; exit 0;;
    *) log ERR "Unknown arg: $1"; usage; exit 1;;
  esac
done

log INFO "NS=$NAMESPACE | cluster=kind-$CLUSTER_NAME | image=$API_IMAGE | env-mode=$ENV_MODE"

# ---- Tool checks
command -v kubectl >/dev/null || { log ERR "kubectl not found"; exit 1; }
if [[ "${SKIP_LOAD:-0}" -eq 0 ]]; then command -v kind >/dev/null || { log ERR "kind not found (or set SKIP_LOAD=1)"; exit 1; }; fi
command -v envsubst >/dev/null || { log ERR "envsubst not found (install gettext)"; exit 1; }

print_latest_api_list() {
  local repo_root="${SCRIPT_DIR}/.."

  if ! command -v python3 >/dev/null 2>&1; then
    log WARN "python3 not found; skipping latest API list."
    return 0
  fi

  if ! python3 - "$repo_root" <<'PY'
import ast
import re
import sys
from pathlib import Path


repo_root = Path(sys.argv[1]).resolve()
main_path = repo_root / "src/seedcore/main.py"
registry_path = repo_root / "src/seedcore/api/routers/__init__.py"
routers_root = registry_path.parent


def load_tree(path: Path) -> ast.AST:
    return ast.parse(path.read_text(), filename=str(path))


def read_assignment(tree: ast.AST, name: str):
    for node in getattr(tree, "body", []):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == name:
                return ast.literal_eval(node.value)
    raise RuntimeError(f"Could not find assignment for {name!r}")


def version_key(prefix: str) -> tuple[int, ...]:
    match = re.fullmatch(r"/api/v(\d+(?:\.\d+)*)", prefix)
    if not match:
        raise ValueError(prefix)
    return tuple(int(part) for part in match.group(1).split("."))


def join_paths(*parts: str) -> str:
    segments: list[str] = []
    for part in parts:
        if not part or part == "/":
            continue
        segments.extend(segment for segment in part.strip("/").split("/") if segment)
    return "/" + "/".join(segments)


main_tree = load_tree(main_path)
version_prefixes: list[str] = []
for node in ast.walk(main_tree):
    if not isinstance(node, ast.Call):
        continue
    if not isinstance(node.func, ast.Attribute) or node.func.attr != "include_router":
        continue
    for keyword in node.keywords:
        if (
            keyword.arg == "prefix"
            and isinstance(keyword.value, ast.Constant)
            and isinstance(keyword.value.value, str)
            and re.fullmatch(r"/api/v\d+(?:\.\d+)*", keyword.value.value)
        ):
            version_prefixes.append(keyword.value.value)

if not version_prefixes:
    raise RuntimeError("No versioned API prefix found in src/seedcore/main.py")

latest_prefix = max(version_prefixes, key=version_key)

registry_tree = load_tree(registry_path)
active_specs = read_assignment(registry_tree, "ACTIVE_ROUTER_SPECS")
router_modules = read_assignment(registry_tree, "_ROUTER_MODULES")

route_methods = {
    "get": ["GET"],
    "post": ["POST"],
    "put": ["PUT"],
    "patch": ["PATCH"],
    "delete": ["DELETE"],
    "options": ["OPTIONS"],
    "head": ["HEAD"],
}

tag_entries: list[tuple[str, list[tuple[str, str]]]] = []

for tag, router_name in active_specs:
    module_rel = router_modules[router_name]
    module_path = routers_root / (module_rel.lstrip(".").replace(".", "/") + ".py")
    module_tree = load_tree(module_path)

    router_prefix = ""
    for node in getattr(module_tree, "body", []):
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(target, ast.Name) and target.id == "router" for target in node.targets):
            continue
        if not isinstance(node.value, ast.Call):
            continue
        func = node.value.func
        func_name = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else None
        if func_name != "APIRouter":
            continue
        for keyword in node.value.keywords:
            if (
                keyword.arg == "prefix"
                and isinstance(keyword.value, ast.Constant)
                and isinstance(keyword.value.value, str)
            ):
                router_prefix = keyword.value.value
                break
        break

    routes: list[tuple[str, str]] = []
    for node in getattr(module_tree, "body", []):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            if not isinstance(decorator, ast.Call):
                continue
            if not isinstance(decorator.func, ast.Attribute):
                continue
            if not isinstance(decorator.func.value, ast.Name) or decorator.func.value.id != "router":
                continue

            if any(
                keyword.arg == "include_in_schema"
                and isinstance(keyword.value, ast.Constant)
                and keyword.value.value is False
                for keyword in decorator.keywords
            ):
                continue

            methods = route_methods.get(decorator.func.attr, [])
            if decorator.func.attr == "api_route":
                for keyword in decorator.keywords:
                    if keyword.arg != "methods" or not isinstance(keyword.value, (ast.List, ast.Tuple, ast.Set)):
                        continue
                    methods = [
                        item.value.upper()
                        for item in keyword.value.elts
                        if isinstance(item, ast.Constant) and isinstance(item.value, str)
                    ]
                    break
            if not methods:
                continue

            path = None
            if decorator.args and isinstance(decorator.args[0], ast.Constant) and isinstance(decorator.args[0].value, str):
                path = decorator.args[0].value
            else:
                for keyword in decorator.keywords:
                    if (
                        keyword.arg == "path"
                        and isinstance(keyword.value, ast.Constant)
                        and isinstance(keyword.value.value, str)
                    ):
                        path = keyword.value.value
                        break
            if not path:
                continue

            full_path = join_paths(latest_prefix, router_prefix, path)
            for method in methods:
                routes.append((method, full_path))

    tag_entries.append((tag, routes))

total_routes = sum(len(routes) for _, routes in tag_entries)
print(f"Latest version API list ({latest_prefix})")
print(f"  {total_routes} endpoints across {len(tag_entries)} active routers")
for tag, routes in tag_entries:
    print(f"  [{tag}]")
    for method, path in routes:
        print(f"    {method:<7} {path}")
PY
  then
    log WARN "Failed to derive latest API list from source files."
  fi
}

# ---- Smart Kind image load (uses kind get nodes + ctr, works on Debian/Ubuntu/macOS)
smart_kind_load() {
  local img="$1" cluster="$2"
  [[ "$SKIP_LOAD" -eq 1 ]] && return 0
  
  # Get actual Kind node names dynamically (works regardless of naming scheme)
  local nodes; nodes=$(kind get nodes --name "$cluster" 2>/dev/null || :)
  if [[ -z "$nodes" ]]; then
    log WARN "Kind cluster '$cluster' not found. Skipping image load."
    return 0
  fi
  
  # Verify local image exists
  if ! docker inspect "$img" >/dev/null 2>&1; then
    log ERR "Local image '$img' not found. Build it first."
    exit 1
  fi
  
  # Prepare alternative image name (kind/containerd often uses docker.io/library/ prefix)
  local alt_img="$img"
  if [[ "$img" != */* ]]; then
    alt_img="docker.io/library/$img"
  fi
  
  # Check if image exists on all nodes using ctr (always available in kindest/node)
  local node_has_image=true
  if [[ -z "$nodes" ]]; then
    node_has_image=false
  else
    for node in $nodes; do
      if docker exec "$node" sh -lc "
        refs=\$(ctr -n k8s.io images ls -q 2>/dev/null || true)
        echo \"\$refs\" | grep -Fxq '${alt_img}' || echo \"\$refs\" | grep -Fxq '${img}'
      " >/dev/null 2>&1; then
        : # present
      else
        node_has_image=false
        break
      fi
    done
  fi
  
  if [[ "$node_has_image" == "true" ]]; then
    log INFO "Image already present on all Kind nodes; skip load."
  else
    log INFO "Loading image $img into Kind cluster $cluster ..."
    kind load docker-image "$img" --name "$cluster"
    log OK "Image loaded into Kind nodes"
  fi
}

# ---- Namespace ensure
kubectl get ns "$NAMESPACE" >/dev/null 2>&1 || {
  log INFO "Creating namespace $NAMESPACE ..."
  kubectl create namespace "$NAMESPACE"
  log OK "Namespace ensured"
}

# ---- Delete path
if [[ "$DELETE_ONLY" -eq 1 ]]; then
  log INFO "Deleting API resources in $NAMESPACE..."
  kubectl -n "$NAMESPACE" delete deploy/"$DEPLOY_NAME" svc/"$SERVICE_NAME" configmap/"$SERVICE_NAME"-config --ignore-not-found
  log OK "Deleted (if existed)."; exit 0
fi

# ---- Decide env wiring (auto/cm/secret/file)
use_shared_cm=false; use_client_cm=false; use_secret=false; use_file_cm=false
if [[ "$ENV_MODE" == "cm" ]]; then
  use_shared_cm=true; use_client_cm=true
elif [[ "$ENV_MODE" == "secret" ]]; then
  use_secret=true
elif [[ "$ENV_MODE" == "file" ]]; then
  use_file_cm=true
else
  # auto
  if kubectl -n "$NAMESPACE" get configmap seedcore-env >/dev/null 2>&1; then
    use_shared_cm=true
  fi
  if kubectl -n "$NAMESPACE" get configmap seedcore-client-env >/dev/null 2>&1; then
    use_client_cm=true
  fi
  if [[ "$use_shared_cm" != "true" ]] && [[ "$use_client_cm" != "true" ]]; then
    if kubectl -n "$NAMESPACE" get secret seedcore-env-secret >/dev/null 2>&1; then
      use_secret=true
    else
      use_file_cm=true
    fi
  fi
fi

# ---- Create/Update env sources when needed
env_sources_updated=0

if [[ "$use_shared_cm" == "true" ]] && [[ -f "$ENV_FILE" ]]; then
  log INFO "Updating shared ConfigMap seedcore-env from $ENV_FILE ..."
  kubectl -n "$NAMESPACE" create configmap seedcore-env --from-env-file="$ENV_FILE" -o yaml --dry-run=client | kubectl apply -f -
  log OK "ConfigMap seedcore-env updated"
  env_sources_updated=1
fi

if [[ "$use_file_cm" == "true" ]]; then
  if [[ -f "$ENV_FILE" ]]; then
    log INFO "Creating/Updating ${SERVICE_NAME}-config from $ENV_FILE ..."
    kubectl -n "$NAMESPACE" create configmap "${SERVICE_NAME}-config" --from-env-file="$ENV_FILE" -o yaml --dry-run=client | kubectl apply -f -
    log OK "ConfigMap ${SERVICE_NAME}-config updated"
    env_sources_updated=1
  else
    log WARN "Env file '$ENV_FILE' not found; continuing without fallback config."
  fi
fi

if [[ "$use_secret" == "true" ]]; then
  if [[ -f "$ENV_FILE" ]]; then
    log INFO "Creating/Updating Secret seedcore-env-secret from $ENV_FILE ..."
    kubectl -n "$NAMESPACE" create secret generic seedcore-env-secret --from-env-file="$ENV_FILE" -o yaml --dry-run=client | kubectl apply -f -
    log OK "Secret seedcore-env-secret updated"
    env_sources_updated=1
  else
    log WARN "Env file '$ENV_FILE' not found; continuing with existing seedcore-env-secret."
  fi
fi

# ---- Smart image load
smart_kind_load "$API_IMAGE" "$CLUSTER_NAME"

# ---- Render + apply YAML
export NAMESPACE SERVICE_NAME DEPLOY_NAME API_IMAGE REPLICAS \
       RAY_HEAD_SVC RAY_HEAD_PORT SEEDCORE_NS HOSTPATH_PROJECT
log INFO "Applying ${YAML_PATH} ..."
tmpfile="$(mktemp)"; envsubst < "${YAML_PATH}" > "$tmpfile"
kubectl apply -f "$tmpfile"
rm -f "$tmpfile"

# EnvFrom changes in ConfigMap/Secret don't hot-reload in existing pods.
if [[ "$env_sources_updated" -eq 1 ]]; then
  log INFO "Env sources updated; restarting Deployment to load latest env ..."
  kubectl -n "$NAMESPACE" rollout restart deploy/"$DEPLOY_NAME"
fi

# ---- Rollout + info
log INFO "Waiting for Deployment rollout ..."
kubectl -n "$NAMESPACE" rollout status deploy/"$DEPLOY_NAME" --timeout=180s || :

log INFO "Pods:"
kubectl -n "$NAMESPACE" get pods -l app="${SERVICE_NAME}" -o wide || :

log INFO "Service:"
kubectl -n "$NAMESPACE" get svc "${SERVICE_NAME}" || :

echo
log OK "API deployed as svc/${SERVICE_NAME} in ns/${NAMESPACE}"
echo "  - Tail logs:    kubectl -n ${NAMESPACE} logs deploy/${DEPLOY_NAME} -f --tail=200"
echo "  - Exec shell:   kubectl -n ${NAMESPACE} exec -it deploy/${DEPLOY_NAME} -- /bin/bash || /bin/sh"
echo "  - Port-forward: kubectl -n ${NAMESPACE} port-forward svc/${SERVICE_NAME} ${LOCAL_PORT}:8002"
echo "  - Health:       curl -sf http://127.0.0.1:${LOCAL_PORT}/health || :"
echo "  - Ready:        curl -si http://127.0.0.1:${LOCAL_PORT}/readyz | head -n1"
echo "  - Delete:       $(basename "$0") --delete -n ${NAMESPACE}"
echo
print_latest_api_list
echo

if [[ "$PORT_FORWARD" -eq 1 ]]; then
  log INFO "Starting port-forward on localhost:${LOCAL_PORT} (Ctrl+C to stop)..."
  kubectl -n "$NAMESPACE" port-forward svc/${SERVICE_NAME} ${LOCAL_PORT}:8002
fi
