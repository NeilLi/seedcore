#!/usr/bin/env bash
# Redis Verification Script
# Verifies that Redis is running and accessible

set -Eeuo pipefail

############################
# Config & CLI
############################
NAMESPACE="${1:-seedcore-dev}"

# Label selector for Redis
REDIS_SELECTOR="${REDIS_SELECTOR:-app=redis}"

TIMEOUT="${TIMEOUT:-180s}"

############################
# Helpers
############################
log()   { printf "%s\n" "[$(date +'%H:%M:%S')] $*"; }
die()   { printf "❌ %s\n" "$*" >&2; exit 1; }

usage() {
  cat <<EOF
Usage: $(basename "$0") [NAMESPACE]

Environment overrides:
  REDIS_SELECTOR
  TIMEOUT (kubectl wait timeout, e.g. 180s)

Examples:
  $(basename "$0")                    # uses namespace 'seedcore-dev'
  $(basename "$0") seedcore-staging   # different namespace
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage; exit 0
fi

command -v kubectl >/dev/null 2>&1 || die "kubectl is not installed or not in PATH."
kubectl get namespace "$NAMESPACE" >/dev/null 2>&1 || die "Namespace '$NAMESPACE' does not exist."

############################
# K8s helpers
############################
wait_for_pods_ready() {
  local selector="$1"
  log "⏳ Waiting for pods with selector '$selector' to be Ready (timeout $TIMEOUT)..."
  kubectl wait --for=condition=ready pod -l "$selector" -n "$NAMESPACE" --timeout="$TIMEOUT" \
    || die "Timeout waiting for selector '$selector'."
}

first_pod_name() {
  local selector="$1"
  kubectl get pods -n "$NAMESPACE" -l "$selector" \
    -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true
}

############################
# Verification
############################
verify_redis() {
  log "🔴 Verifying Redis..."
  wait_for_pods_ready "$REDIS_SELECTOR"
  local pod; pod="$(first_pod_name "$REDIS_SELECTOR")"
  [[ -n "$pod" ]] || die "Redis pod not found."

  log "🔍 Testing Redis connection..."
  if kubectl exec -n "$NAMESPACE" "$pod" -- redis-cli ping >/dev/null 2>&1; then
    log "✅ Redis is responding to PING"
    
    # Test a simple SET/GET operation
    if kubectl exec -n "$NAMESPACE" "$pod" -- redis-cli SET test_key "test_value" >/dev/null 2>&1 && \
       kubectl exec -n "$NAMESPACE" "$pod" -- redis-cli GET test_key | grep -q "test_value"; then
      log "✅ Redis SET/GET operations working correctly"
      # Clean up test key
      kubectl exec -n "$NAMESPACE" "$pod" -- redis-cli DEL test_key >/dev/null 2>&1 || true
    else
      log "⚠️  Redis SET/GET test failed, but Redis is running"
    fi
  else
    die "Redis is not responding to PING"
  fi

  log "✅ Redis verified successfully."
}

############################
# Main
############################
main() {
  log "🚀 Starting Redis verification..."
  verify_redis
  log "🎉 Redis verification completed!"
}

main
