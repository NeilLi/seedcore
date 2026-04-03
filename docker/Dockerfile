# docker/Dockerfile
# 1. UPGRADE to Python 3.12 as requested
FROM rust:1.87-slim AS rust-builder

WORKDIR /workspace/rust
COPY rust/Cargo.toml rust/Cargo.lock ./
COPY rust/crates ./crates
RUN cargo build --release -p seedcore-verify

FROM rayproject/ray:2.53.0-py312

SHELL ["/bin/bash", "-euo", "pipefail", "-c"]

ARG BUILD_DATE
ARG VCS_REF
ARG ENABLE_ML=0
LABEL org.opencontainers.image.title="seedcore-serve" \
      org.opencontainers.image.description="SeedCore Serve on Ray (Py3.12)" \
      org.opencontainers.image.version="2.53.0-py312" \
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
      iputils-ping dnsutils \
    && rm -rf /var/lib/apt/lists/*

# Install OPA (Open Policy Agent) binary for PKG WASM compilation
RUN curl -L -o /usr/local/bin/opa https://openpolicyagent.org/downloads/latest/opa_linux_amd64 \
    && chmod +x /usr/local/bin/opa \
    && opa version

# Install SeedCore Rust verifier binary for authority-critical verification flows.
COPY --from=rust-builder /workspace/rust/target/release/seedcore-verify /usr/local/bin/seedcore-verify
RUN chmod +x /usr/local/bin/seedcore-verify

# ---- Python Environment Setup ----
USER ray
# Upgrade pip first
RUN python -m pip install --upgrade pip wheel setuptools

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

# ---- Application Requirements ----
COPY docker/requirements.base.txt /tmp/requirements.base.txt
COPY docker/requirements.optional-ml.txt /tmp/requirements.optional-ml.txt
RUN --mount=type=cache,target=/home/ray/.cache/pip,uid=1000,gid=1000 \
    python -m pip install -r /tmp/requirements.base.txt

# ---- Optional ML / local-AI stack ----
# Default builds stay lean and CPU-only. Set ENABLE_ML=1 to include the local
# ML runtime (Torch/DGL/Transformers/XGBoost); CUDA-specific packages remain out
# of scope unless you create a dedicated GPU image.
RUN --mount=type=cache,target=/home/ray/.cache/pip,uid=1000,gid=1000 \
    if [[ "${ENABLE_ML}" == "1" ]]; then \
      python -m pip install \
        torch==2.2.2+cpu \
        --index-url https://download.pytorch.org/whl/cpu && \
      python -m pip install torchdata==0.7.1 && \
      python -m pip install --no-index \
        -f https://data.dgl.ai/wheels/torch-2.2/repo.html \
        dgl==2.2.1 && \
      python -m pip install -r /tmp/requirements.optional-ml.txt && \
      python -c 'import dgl, inspect, pathlib, sys; libs = [p.name for p in (pathlib.Path(inspect.getfile(dgl)).parent / "graphbolt").glob("libgraphbolt_pytorch_*.so")]; print(f"Found GraphBolt libs: {libs}"); sys.exit(0 if libs else 1)' ; \
    else \
      echo "Skipping optional ML/local-AI dependency layer (ENABLE_ML=${ENABLE_ML})"; \
    fi

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
# DGL_GRAPHBOLT_SKIP stays on by default because the lean image does not ship
# the graph runtime unless ENABLE_ML=1.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app:/app/src \
    PATH="/home/ray/.local/bin:${PATH}" \
    SEEDCORE_VERIFY_BIN=/usr/local/bin/seedcore-verify \
    RAY_USAGE_STATS_ENABLED=0 \
    SEEDCORE_OPTIONAL_ML=${ENABLE_ML} \
    DGL_GRAPHBOLT_SKIP=1 \
    RAY_NAMESPACE="seedcore-dev" \
    SEEDCORE_HOT_PATH_DEPLOYMENT_ROLE=docker

# Ray Dashboard, Serve HTTP, Metrics
EXPOSE 8265 8000 8002

# ---- Optimized Healthcheck ----
# Uses curl instead of spinning up Python interpreter (lighter weight)
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=5 \
  CMD curl -f http://127.0.0.1:8000/health || exit 1
