#!/usr/bin/env bash
# ==========================================
# SeedCore Environment Bootstrap Script
# Installs & initializes Docker, Kind, Python 3.10.14, and kubectl
# ==========================================

set -euo pipefail
IFS=$'\n\t'

# -------- Config -------
CLUSTER_NAME="${CLUSTER_NAME:-seedcore-cluster}"
PY_VER="3.10.14"
KIND_VERSION="${KIND_VERSION:-v0.24.0}"
ARCH="$(uname -m)"       # expected x86_64/amd64/aarch64
OS="$(uname -s)"         # expected Linux
APT_FLAGS=( -y -qq )

# -------- Helpers -------
log()   { echo -e "\033[1;32m[+] $*\033[0m"; }
warn()  { echo -e "\033[1;33m[!] $*\033[0m"; }
error() { echo -e "\033[1;31m[✗] $*\033[0m" >&2; }
die()   { error "$*"; exit 1; }
have()  { command -v "$1" >/dev/null 2>&1; }

require_linux_ubuntu() {
  [[ "$OS" == "Linux" ]] || die "This script supports Linux only (detected: $OS)."
  if ! have apt-get; then
    die "apt-get not found; this script targets Debian/Ubuntu. Please adapt for your distro."
  fi
}

noninteractive_apt() {
  export DEBIAN_FRONTEND=noninteractive
  sudo apt-get update -qq
  sudo apt-get install "${APT_FLAGS[@]}" "$@"
}

systemctl_safe() {
  if have systemctl; then
    sudo systemctl "$@"
  else
    warn "systemctl not available; skipping: systemctl $*"
  fi
}

wait_for_docker() {
  local tries=20
  while ! docker info >/dev/null 2>&1; do
    ((tries--)) || { error "Docker daemon not ready."; return 1; }
    sleep 1
  done
}

# -------- Sanity checks -------
require_linux_ubuntu

if [[ "$ARCH" == "x86_64" ]]; then
  ARCH_DL="amd64"
elif [[ "$ARCH" == "aarch64" || "$ARCH" == "arm64" ]]; then
  ARCH_DL="arm64"
else
  die "Unsupported architecture: $ARCH"
fi

# Ensure prerequisites early
log "Installing base prerequisites (curl, wget, ca-certificates, gnupg, lsb-release, build tools)..."
noninteractive_apt ca-certificates curl wget gnupg lsb-release software-properties-common

# -------- Docker --------
if have docker; then
  log "Docker already installed: $(docker --version)"
else
  log "Installing Docker Engine..."
  sudo install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
  sudo chmod a+r /etc/apt/keyrings/docker.gpg
  echo \
    "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | \
    sudo tee /etc/apt/sources.list.d/docker.list >/dev/null

  sudo apt-get update -qq
  noninteractive_apt docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

  systemctl_safe enable docker
  systemctl_safe start docker
  log "Docker installed."
fi

# Optional: add current user to docker group (newgrp needed for current shell)
if groups "$USER" | grep -qv '\bdocker\b'; then
  if getent group docker >/dev/null 2>&1; then
    log "Adding $USER to docker group..."
    sudo usermod -aG docker "$USER" || warn "Could not add user to docker group."
    warn "You may need to log out/in or run: newgrp docker"
  fi
fi

# Ensure Docker daemon is up
if have docker; then
  log "Waiting for Docker daemon..."
  if ! wait_for_docker; then
    warn "Docker not ready; kind cluster creation may fail. Continuing..."
  fi
fi

# -------- Python 3.10.14 --------
if have python3 && python3 --version 2>/dev/null | grep -q "$PY_VER"; then
  log "Python $PY_VER already installed (python3)."
elif have python3.10 && python3.10 --version 2>/dev/null | grep -q "$PY_VER"; then
  log "Python $PY_VER already installed (python3.10)."
else
  log "Installing Python $PY_VER from source..."
  noninteractive_apt build-essential libssl-dev zlib1g-dev \
    libncurses5-dev libffi-dev libsqlite3-dev libreadline-dev \
    libbz2-dev liblzma-dev tk-dev uuid-dev

  pushd /tmp >/dev/null
  wget -q "https://www.python.org/ftp/python/${PY_VER}/Python-${PY_VER}.tgz"
  tar -xzf "Python-${PY_VER}.tgz"
  pushd "Python-${PY_VER}" >/dev/null
  ./configure --enable-optimizations
  make -j"$(nproc)"
  sudo make altinstall
  popd >/dev/null
  rm -rf "Python-${PY_VER}" "Python-${PY_VER}.tgz"
  popd >/dev/null

  # Confirm install
  if ! python3.10 --version 2>/dev/null | grep -q "$PY_VER"; then
    die "Python $PY_VER installation appears to have failed."
  fi
  log "Python $PY_VER installed (python3.10)."
fi
# NOTE: We intentionally do NOT replace system /usr/bin/python3 symlink.

# -------- kind --------
if have kind; then
  log "kind already installed: $(kind --version)"
  # Require kind >= 0.24.0 (optional)
  KIND_MIN="0.24.0"
  KIND_CUR="$(kind --version | sed -n 's/.*version[[:space:]]*\([0-9.]\+\).*/\1/p')"
  if [[ -n "$KIND_CUR" ]] && [[ "$(printf '%s\n' "$KIND_MIN" "$KIND_CUR" | sort -V | head -n1)" != "$KIND_MIN" ]]; then
    warn "kind $KIND_CUR detected (< $KIND_MIN). Consider upgrading:"
    warn "  sudo curl -Lo /usr/local/bin/kind \"https://kind.sigs.k8s.io/dl/v0.24.0/kind-linux-${ARCH_DL}\" && sudo chmod +x /usr/local/bin/kind"
  fi
else
  log "Installing kind ${KIND_VERSION} for ${ARCH_DL}..."
  curl -Lo ./kind "https://kind.sigs.k8s.io/dl/${KIND_VERSION}/kind-linux-${ARCH_DL}"
  chmod +x ./kind
  sudo mv ./kind /usr/local/bin/kind
  log "kind installed."
fi

# -------- kubectl --------
if have kubectl; then
  if kubectl version --client --short >/dev/null 2>&1; then
    # Newer kubectl supports --short
    log "kubectl already installed: $(kubectl version --client --short)"
  else
    # Fallback for older kubectl (no --short)
    # Try YAML/JSON outputs; if not, parse the plain text first line
    VER="$(kubectl version --client -o yaml 2>/dev/null | awk '/gitVersion:/ {print $2; exit}')"
    if [[ -z "${VER:-}" ]]; then
      VER="$(kubectl version --client -o json 2>/dev/null | sed -n 's/.*"gitVersion":[[:space:]]*"\(v[^"]*\)".*/\1/p' | head -n1)"
    fi
    if [[ -z "${VER:-}" ]]; then
      VER="$(kubectl version --client 2>/dev/null | sed -n '1p' | sed 's/^Client Version: *//')"
    fi
    log "kubectl already installed: ${VER:-unknown version}"
  fi
else
  log "Installing latest stable kubectl for ${ARCH_DL}..."
  KUBECTL_VERSION="$(curl -L -s https://dl.k8s.io/release/stable.txt)"
  curl -LO "https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/${ARCH_DL}/kubectl"
  # Optional checksum verification — uncomment to enforce:
  # curl -LO "https://dl.k8s.io/${KUBECTL_VERSION}/bin/linux/${ARCH_DL}/kubectl.sha256"
  # echo "$(cat kubectl.sha256)  kubectl" | sha256sum --check - || die "kubectl checksum mismatch"
  chmod +x kubectl
  sudo mv kubectl /usr/local/bin/kubectl
  log "kubectl installed."
fi

# -------- kind cluster init --------
if ! have docker || ! docker info >/dev/null 2>&1; then
  warn "Docker not available; skipping kind cluster creation."
else
  if kind get clusters | grep -Fxq "$CLUSTER_NAME"; then
    log "kind cluster '${CLUSTER_NAME}' already exists."
  else
    log "Creating kind cluster '${CLUSTER_NAME}'..."
    cat <<EOF > kind-config.yaml
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
nodes:
  - role: control-plane
  - role: worker
EOF
    if ! kind create cluster --name "$CLUSTER_NAME" --config kind-config.yaml; then
      rm -f kind-config.yaml
      die "Failed to create kind cluster '${CLUSTER_NAME}'."
    fi
    rm -f kind-config.yaml
    log "kind cluster '${CLUSTER_NAME}' created."
  fi

  # Verify cluster connectivity
  log "Verifying cluster connectivity..."
  kubectl cluster-info --context "kind-${CLUSTER_NAME}"
  kubectl get nodes -o wide
fi

log "✅ Environment initialized successfully."

