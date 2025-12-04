# docker/Dockerfile
# 1. UPGRADE to Python 3.11 as requested
FROM rayproject/ray:2.33.0-py311

SHELL ["/bin/bash", "-euo", "pipefail", "-c"]

ARG BUILD_DATE
ARG VCS_REF
LABEL org.opencontainers.image.title="seedcore-serve" \
      org.opencontainers.image.description="SeedCore Serve on Ray (Py3.11)" \
      org.opencontainers.image.version="2.33.0-py311" \
      org.opencontainers.image.created="${BUILD_DATE}" \
      org.opencontainers.image.revision="${VCS_REF}" \
      org.opencontainers.image.source="seedcore"

# ---- System deps (minimal) ----
USER root
# Added --mount=type=cache for apt to speed up re-runs
RUN rm -f /etc/apt/apt.conf.d/docker-clean; echo 'Binary::apt::APT::Keep-Downloaded-Packages "true";' > /etc/apt/apt.conf.d/keep-cache
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && apt-get install -y --no-install-recommends \
      build-essential curl git ca-certificates \
      libglib2.0-0 libsm6 libxrender1 libxext6 \
      # Useful for debugging network issues inside pods
      iputils-ping dnsutils

# ---- Python Environment Setup ----
USER ray
# Upgrade pip first
RUN pip install --upgrade pip wheel setuptools

# ---- Clean Pre-installed DGL/CUDA (Crucial for CPU images) ----
RUN set -eux; \
  pip freeze | awk -F'[= ]' '/^dgl($|==)|^dgl-cu/ {print $1}' | xargs -r pip uninstall -y; \
  python - <<'PY'
import site, glob, os, shutil
paths = set(site.getsitepackages() + [site.getusersitepackages()])
for s in paths:
    if not s or not os.path.isdir(s):
        continue
    # Clean up lingering metadata that confuses pip
    for pat in ("*-gl*", "dgl*.dist-info", "dgl*.egg-info"):
        for p in glob.glob(os.path.join(s, pat)):
            print(f"Cleaning {p}")
            shutil.rmtree(p, ignore_errors=True)
PY

# ---- Core Numerical Stack ----
# Pin NumPy < 2.0.0 (1.26.4 is the gold standard for Py3.11 + Torch 2.x compatibility)
RUN --mount=type=cache,target=/home/ray/.cache/pip \
    pip install "numpy==1.26.4"

# ---- Torch & DGL (CPU Optimized) ----
# 1. Install PyTorch CPU first from official index
RUN --mount=type=cache,target=/home/ray/.cache/pip \
    pip install \
      torch==2.2.2+cpu \
      --index-url https://download.pytorch.org/whl/cpu

# 2. Install torchdata and DGL
# Note: torchdata 0.7.1 is compatible with torch 2.2.x
RUN --mount=type=cache,target=/home/ray/.cache/pip \
    pip install torchdata==0.7.1 && \
    pip install --no-index \
      -f https://data.dgl.ai/wheels/torch-2.2/repo.html \
      dgl==2.2.1

# 3. Validation: Verify DGL GraphBolt libraries loaded correctly
RUN python - <<'PY'
import dgl, inspect, pathlib, sys
try:
    gb = (pathlib.Path(inspect.getfile(dgl)).parent / "graphbolt").glob("libgraphbolt_pytorch_*.so")
    libs = [p.name for p in gb]
    print(f"Found GraphBolt libs: {libs}")
    if not libs:
        print("Error: Missing GraphBolt .so")
        sys.exit(1)
except Exception as e:
    print(f"Validation failed: {e}")
    sys.exit(1)
PY

# ---- Application Requirements ----
COPY docker/requirements-minimal.txt /tmp/requirements.txt
RUN --mount=type=cache,target=/home/ray/.cache/pip \
    pip install -r /tmp/requirements.txt

# ---- Application Code ----
# Switch to root to copy files (preserves permissions), then switch back
USER root
WORKDIR /app

# Copy optimized source structure
COPY --chown=ray:ray src/ ./src/
COPY --chown=ray:ray scripts/ ./scripts/
COPY --chown=ray:ray docker/ ./docker/
COPY --chown=ray:ray entrypoints/ ./entrypoints/
COPY --chown=ray:ray bootstraps/ ./bootstraps/
COPY --chown=ray:ray config/ ./config/

# Revert to unprivileged user
USER ray

# ---- Runtime Environment ----
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app:/app/src \
    PATH="/home/ray/.local/bin:${PATH}" \
    RAY_USAGE_STATS_ENABLED=0 \
    # Skip GraphBolt Defensively (Enable via K8s env var if needed for GNNs)
    DGL_GRAPHBOLT_SKIP=1 \
    # Standardize namespaces for our new bootstrap scripts
    RAY_NAMESPACE="seedcore-dev"

# Ray Dashboard, Serve HTTP, Metrics
EXPOSE 8265 8000 8002

# ---- Optimized Healthcheck ----
# Uses curl instead of spinning up Python interpreter (lighter weight)
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=5 \
  CMD curl -f http://127.0.0.1:8000/health || exit 1