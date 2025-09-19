# docker/Dockerfile
FROM rayproject/ray:2.33.0-py310

SHELL ["/bin/bash", "-euo", "pipefail", "-c"]

ARG BUILD_DATE
ARG VCS_REF
LABEL org.opencontainers.image.title="seedcore-serve" \
      org.opencontainers.image.description="SeedCore Serve on Ray" \
      org.opencontainers.image.version="2.33.0-py310" \
      org.opencontainers.image.created="${BUILD_DATE}" \
      org.opencontainers.image.revision="${VCS_REF}" \
      org.opencontainers.image.source="seedcore"

# ---- System deps (minimal) ----
USER root
RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential curl git ca-certificates \
      libglib2.0-0 libsm6 libxrender1 libxext6 \
  && rm -rf /var/lib/apt/lists/*

# ---- Use Conda's Python in base image for all installs ----
USER ray
RUN python -m pip install --upgrade pip wheel setuptools

# ---- Clean any preinstalled DGL/CUDA bits ----
RUN set -eux; \
  # Uninstall any dgl / dgl-cu* that might be present in the image
  pip freeze | awk -F'[= ]' '/^dgl($|==)|^dgl-cu/ {print $1}' | xargs -r pip uninstall -y; \
  # Clean up dangling metadata that causes "invalid distribution -gl" warnings
  python - <<'PY'
import site, glob, os, shutil
paths = set(site.getsitepackages() + [site.getusersitepackages()])
for s in paths:
    if not s or not os.path.isdir(s):
        continue
    for pat in ("*-gl*", "dgl*.dist-info", "dgl*.egg-info"):
        for p in glob.glob(os.path.join(s, pat)):
            print("Removing", p)
            shutil.rmtree(p, ignore_errors=True)
PY

# Pin NumPy < 2.0 to avoid ABI breakage with compiled libs
RUN pip install --no-cache-dir "numpy==1.26.4"

# Torch CPU (no CUDA) from official PyTorch CPU index
RUN pip install --no-cache-dir \
      torch==2.2.2+cpu \
      --index-url https://download.pytorch.org/whl/cpu

# Install torchdata from PyPI (needs index), then DGL from the DGL wheel repo
RUN pip install --no-cache-dir torchdata==0.7.1 && \
    pip install --no-cache-dir --no-index \
      -f https://data.dgl.ai/wheels/torch-2.2/repo.html \
      dgl==2.2.1

# Optional sanity check that GraphBolt .so exists
RUN python - <<'PY'
import dgl,inspect,pathlib
gb = (pathlib.Path(inspect.getfile(dgl)).parent / "graphbolt").glob("libgraphbolt_pytorch_*.so")
libs = [p.name for p in gb]
print("GraphBolt libs:", libs)
assert libs, "Missing GraphBolt .so"
PY

# ---- App requirements (Torch/DGL/NumPy were installed above) ----
COPY docker/requirements-minimal.txt /tmp/requirements.txt
RUN PIP_NO_CACHE_DIR=1 pip install --no-cache-dir -r /tmp/requirements.txt && \
    rm -rf ~/.cache/pip

# ---- App files ----
USER root
WORKDIR /app
COPY --chown=ray:ray src/ ./src/
COPY --chown=ray:ray scripts/ ./scripts/
COPY --chown=ray:ray docker/ ./docker/
COPY --chown=ray:ray entrypoints/ ./entrypoints/
COPY --chown=ray:ray bootstraps/ ./bootstraps/
COPY --chown=ray:ray config/ ./config/
USER ray

# ---- Runtime env ----
# Default: skip GraphBolt init defensively (override in K8s if needed)
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app:/app/src \
    PATH="/home/ray/.local/bin:${PATH}" \
    RAY_USAGE_STATS_ENABLED=0 \
    DGL_GRAPHBOLT_SKIP=1

EXPOSE 8000 8002 8265

# Healthcheck expects your service to expose /health on 8000 (adjust as needed)
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=10 \
  CMD ["python","-c","import sys,urllib.request; u='http://127.0.0.1:8000/health'; \
try:\n r=urllib.request.urlopen(u, timeout=5); sys.exit(0 if r.getcode()==200 else 1)\nexcept Exception:\n sys.exit(1)"]

# No ENTRYPOINT/CMD: you’ll pass command/args from Kubernetes
