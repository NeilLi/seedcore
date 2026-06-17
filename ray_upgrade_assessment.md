# Ray 2.55.1 Upgrade Assessment

Date: 2026-06-17

## Scope

This upgrade moves SeedCore's Ray runtime target from Ray 2.53.0 to Ray
2.55.1 on Python 3.12 across Python dependencies, Docker image builds, local
deployment helpers, KubeRay manifests, and Ray Serve configuration.

## Updated Surfaces

- `pyproject.toml` and `docker/requirements.base.txt` pin `ray==2.55.1`.
- `docker/Dockerfile` uses `rayproject/ray:2.55.1-py312`.
- `docker/Dockerfile.optimize` installs `ray[default]==2.55.1` on
  `python:3.12-slim`.
- KubeRay manifests and Helm values use Ray `2.55.1` or the matching
  `2.55.1-py312` image where they directly reference upstream Ray images.
- `deploy/deploy-ray-service.sh` defaults `RAY_VERSION` to `2.55.1`.
- Ray authz-cache verification now compares serialized `authority_paths`
  between the local compiled index and the Ray actor cache.

## Compatibility Findings

- Ray Serve deployment config for Ray 2.55.1 declares `max_ongoing_requests`,
  not `max_concurrent_queries`. The checked Serve configs now use
  `max_ongoing_requests` so concurrency limits remain effective instead of
  being ignored as unknown fields.
- `config/ray-serve.yaml` no longer sets `runtime_env.working_dir: "/app"`.
  Ray Serve config validation requires remote URIs for `working_dir`; SeedCore
  containers already expose the application through `PYTHONPATH=/app:/app/src`.
- `entrypoints/ops_entrypoint.py` now unwraps Ray Serve ingress classes before
  constructing embedded `OpsGateway` backends. Under Ray 2.55.1, constructing
  the ASGI ingress wrapper directly fails with `TypeError: __init__() should
  return None, not 'coroutine'`.
- The `rayproject/ray:2.55.1-py312` image manifest is published for both
  `amd64/linux` and `arm64/linux`.
- The local `.venv` resolves Ray `2.55.1`; `pip index versions ray` reports
  `2.55.1` as the installed and latest package version at validation time.

## Validation Evidence

Commands run during review:

```bash
./.venv/bin/python - <<'PY'
from pathlib import Path
from ray.serve.schema import ServeDeploySchema
import yaml

paths = ["deploy/k8s/rayservice.yaml", "deploy/aws_bak/rayservice-deployment.yaml"]
for path in paths:
    text = Path(path).read_text()
    for key, value in {
        "${NAMESPACE}": "seedcore",
        "${ECR_REPO}": "seedcore",
        "${SEEDCORE_IMAGE_TAG}": "latest",
        "${SEEDCORE_NS}": "seedcore",
        "${AWS_REGION}": "us-east-1",
    }.items():
        text = text.replace(key, value)
    manifest = yaml.safe_load(text)
    ServeDeploySchema.model_validate(yaml.safe_load(manifest["spec"]["serveConfigV2"]))

ServeDeploySchema.model_validate(yaml.safe_load(Path("config/ray-serve.yaml").read_text()))
PY

rg -n "max_concurrent_queries|runtime_env:|working_dir: \"/app\"|2\.53\.0" \
  config deploy pyproject.toml docker scripts --glob '!docker/docker-bak/**'

docker manifest inspect rayproject/ray:2.55.1-py312
git diff --check
./.venv/bin/pytest tests/test_pkg_authz_graph.py tests/test_action_intent.py tests/test_cognitive_service.py -q
./.venv/bin/pytest tests/test_ops_gateway_rpc.py -q
./.venv/bin/python -m pip check
APPS="ops mcp" START_DELAY_S=4 bash deploy/local/run-ray-stack.sh start
RAY_ADDRESS=ray://127.0.0.1:23001 RAY_NAMESPACE=seedcore-local SEEDCORE_NS=seedcore-local \
  bash scripts/host/verify_ray_authz_cache_actor.sh
bash scripts/host/verify_authz_graph_rfc_phases.sh
bash scripts/host/verify_q2_verification_contracts.sh
bash deploy/local/run-task-stack.sh start
```

Results:

- `deploy/k8s/rayservice.yaml`: YAML and Ray Serve schema validation passed.
- `deploy/aws_bak/rayservice-deployment.yaml`: YAML and Ray Serve schema
  validation passed after placeholder substitution.
- `config/ray-serve.yaml`: Ray Serve schema validation passed.
- No non-archived config references to `2.53.0` or `max_concurrent_queries`
  remain.
- Docker manifest lookup passed for `rayproject/ray:2.55.1-py312`.
- `git diff --check` passed.
- Focused Python tests passed: `73 passed`.
- Ops gateway regression tests passed: `5 passed`.
- `pip check` reported no broken requirements.
- `./.venv/bin/ray --version` reported `ray, version 2.55.1`.
- Local Ray/Serve runtime was started through `deploy/local/run-ray-stack.sh`.
  Serve controller status reported `organism`, `cognitive`, `coordinator`,
  `ops`, and `mcp` as running and healthy.
- `verify_ray_authz_cache_actor.sh` passed against the local Ray client
  endpoint in namespace `seedcore-local`; active snapshot loaded into Ray with
  10 nodes and 12 edges, and fixture decision parity matched the local compiled
  graph including `authority_paths`.
- `verify_authz_graph_rfc_phases.sh` passed: 79 focused tests plus 8 live
  phase checks, including Ray shard routing.
- `verify_q2_verification_contracts.sh` passed.
- `deploy/local/run-task-stack.sh start` completed; organism initialized,
  `seedcore_reaper` and `queue_dispatcher_0` were present, and the Serve route
  set remained `/organism`, `/cognitive`, `/pipeline`, `/ops`, and `/mcp`.

## Promotion Notes

1. Local validation: keep using `.venv` with Ray `2.55.1` for focused unit and
   host-script verification.
2. Image validation: build both Dockerfiles and confirm `ray --version` and
   Serve import paths inside each image before publishing.
3. Kind validation: deploy `deploy/k8s/rayservice.yaml` through
   `deploy/deploy-ray-service.sh` and confirm Serve application health.
4. Cluster promotion: promote only after KubeRay reconciles the RayService and
   SeedCore's authority-bearing verification paths still close evidence through
   the PDP, `ExecutionToken`, verifier, and evidence pipeline.

## Remaining Risks

- This review validates local schema compatibility and package/image
  availability. It does not prove KubeRay operator compatibility in a live
  cluster.
- Local runtime verification leaves developer services running by design:
  Postgres, Redis, Neo4j, API/HAL, Ray, Serve apps, and task dispatchers should
  be stopped through `deploy/local/stop-local-runtime.sh` when no longer needed.
