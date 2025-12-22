#!/usr/bin/env bash
# ==========================================
# SeedCore Environment Bootstrap Script
# Debian 11/12 | Google Cloud Compute Engine
# Installs: Docker, Python 3.11, kind, kubectl, Helm
# ==========================================

set -euo pipefail
IFS=$'\n\t'

# Fix locale warnings
export LC_ALL=C.UTF-8
export LANG=C.UTF-8

# -------- Config -------
CLUSTER_NAME="${CLUSTER_NAME:-seedcore-cluster}"
HELM_VERSION="v3.15.4"
KIND_VERSION="v0.24.0"
KIND_NODE_IMAGE="kindest/node:v1.30.0"

ARCH="$(uname -m)"
OS="$(uname -s)"

# -------- Helpers -------
log()  { echo -e "\033[1;32m[+] $*\033[0m"; }
warn() { echo -e "\033[1;33m[!] $*\033[0m"; }
die()  { echo -e "\033[1;31m[✗] $*\033[0m" >&2; exit 1; }
have() { command -v "$1" >/dev/null 2>&1; }

require_debian() {
  [[ "$OS" == "Linux" ]] || die "Linux only."
  have apt-get || die "apt-get not found (Debian only)."
}

require_debian

if [[ "$ARCH" == "x86_64" ]]; then
  ARCH_DL="amd64"
elif [[ "$ARCH" == "aarch64" ]]; then
  ARCH_DL="arm64"
else
  die "Unsupported architecture: $ARCH"
fi

# -------- Base packages -------
log "Installing base system packages..."
sudo apt update -qq
sudo apt install -y \
  ca-certificates curl wget gnupg lsb-release \
  software-properties-common build-essential \
  apt-transport-https

# -------- Docker --------
if have docker; then
  log "Docker already installed: $(docker --version)"
else
  log "Installing Docker (official Debian repo)..."
  sudo install -m 0755 -d /etc/apt/keyrings

  curl -fsSL https://download.docker.com/linux/debian/gpg | \
    sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg

  echo \
    "deb [arch=${ARCH_DL} signed-by=/etc/apt/keyrings/docker.gpg] \
    https://download.docker.com/linux/debian $(lsb_release -cs) stable" | \
    sudo tee /etc/apt/sources.list.d/docker.list >/dev/null

  sudo apt update -qq
  sudo apt install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
  sudo systemctl enable docker
  sudo systemctl start docker
fi

# Docker group
if ! id -nG "$USER" | grep -qw docker; then
  log "Adding $USER to docker group..."
  sudo usermod -aG docker "$USER"
  warn "Run: newgrp docker OR logout/login to activate docker group."
fi

# -------- Python 3.11 (Debian-native, correct way) --------
if have python3.11; then
  log "Python 3.11 already installed: $(python3.11 --version)"
else
  log "Installing Python 3.11 from Debian backports..."

  echo "deb http://deb.debian.org/debian bookworm-backports main" | \
    sudo tee /etc/apt/sources.list.d/backports.list >/dev/null

  sudo apt update -qq
  sudo apt install -y -t bookworm-backports \
    python3.11 python3.11-venv python3.11-dev

  sudo update-alternatives --install /usr/bin/python python /usr/bin/python3.11 1
fi

# -------- kubectl --------
if have kubectl; then
  log "kubectl already installed: $(kubectl version --client --short 2>/dev/null || true)"
else
  log "Installing kubectl..."

  KUBECTL_VERSION="$(curl -fsSL https://dl.k8s.io/release/stable.txt 2>/dev/null | tr -d '\n\r' || true)"
  if [[ -z "$KUBECTL_VERSION" ]]; then
    warn "Failed to fetch stable kubectl version. Falling back to v1.30.3"
    KUBECTL_VERSION="v1.30.3"
  fi

  curl -fsSL -o kubectl \
    "https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/${ARCH_DL}/kubectl"

  chmod +x kubectl
  sudo mv kubectl /usr/local/bin/
fi

# -------- kind --------
if have kind; then
  log "kind already installed: $(kind version)"
else
  log "Installing kind ${KIND_VERSION}..."
  curl -Lo kind "https://kind.sigs.k8s.io/dl/${KIND_VERSION}/kind-linux-${ARCH_DL}"
  chmod +x kind
  sudo mv kind /usr/local/bin/
fi

# -------- Helm --------
if have helm; then
  log "Helm already installed: $(helm version --short)"
else
  log "Installing Helm ${HELM_VERSION}..."
  curl -Lo helm.tar.gz "https://get.helm.sh/helm-${HELM_VERSION}-linux-${ARCH_DL}.tar.gz"
  tar -xzf helm.tar.gz
  sudo mv linux-${ARCH_DL}/helm /usr/local/bin/helm
  rm -rf linux-${ARCH_DL} helm.tar.gz
fi

# -------- kind cluster --------
if docker info >/dev/null 2>&1; then
  if kind get clusters | grep -q "^${CLUSTER_NAME}$"; then
    log "kind cluster '${CLUSTER_NAME}' already exists."
  else
    log "Creating kind cluster '${CLUSTER_NAME}'..."
    cat <<EOF > kind-config.yaml
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
nodes:
  - role: control-plane
    image: ${KIND_NODE_IMAGE}
  - role: worker
    image: ${KIND_NODE_IMAGE}
EOF
    kind create cluster --name "${CLUSTER_NAME}" --config kind-config.yaml
    rm -f kind-config.yaml
  fi

  log "Verifying cluster..."
  kubectl cluster-info --context "kind-${CLUSTER_NAME}"
  kubectl get nodes --context "kind-${CLUSTER_NAME}" -o wide
else
  warn "Docker not ready. Skipping kind cluster creation."
fi

log "✅ SeedCore Debian / GCP bootstrap complete."
