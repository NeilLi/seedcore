# 📘 SeedCore ML Service – Development, Deployment & Verification Guide

This document provides a complete reference for working with the **SeedCore ML Service**, including architecture, development workflow, deployment practices, smoke testing, and advanced operations.

---

## 1. Overview

The **ML Service** is a microservice in **SeedCore** responsible for:

* **Salience Scoring** → prioritizing events by importance.
* **Anomaly Detection** → flagging unusual behavior in metrics/time series.
* **Scaling Prediction** → recommending scale-up/down actions.
* **XGBoost Lifecycle Management** → train, predict, tune, and manage ML models.

It is implemented using:

* **Ray Serve** (for distributed model serving & scaling).
* **FastAPI** (for HTTP ingress).
* **XGBoost** (for ML model training and inference).

---

## 2. Architecture

### Components

* **MLService**: Main Ray Serve deployment exposing all endpoints.
* **FastAPI Router**: Defines REST API endpoints.
* **XGBoost Worker**: Manages training, predictions, and tuning jobs.
* **Cluster Backend**: Ray head + worker nodes handle distributed execution.

### Routes

If deployed with `route_prefix: /ml` (recommended):

* Health:
  * `GET /ml/health`
* Core ML:
  * `POST /ml/score/salience`
  * `POST /ml/detect/anomaly`
  * `POST /ml/predict/scaling`
* XGBoost:
  * `POST /ml/xgboost/train`
  * `POST /ml/xgboost/predict`
  * `POST /ml/xgboost/batch_predict`
  * `GET /ml/xgboost/list_models`
  * `GET /ml/xgboost/model_info`
  * `DELETE /ml/xgboost/delete_model`
  * `POST /ml/xgboost/tune` (+ async submit/status/jobs)
  * `POST /ml/xgboost/refresh_model`
  * `POST /ml/xgboost/promote`

Docs:
* Swagger UI → `/ml/docs`
* OpenAPI spec → `/ml/openapi.json`

---

## 3. Development Workflow

### Setup Environment

```bash
git clone <repo>
cd seedcore
conda activate base   # or use venv/poetry
pip install -r requirements.txt
```

### Local Development with Ray Serve

```bash
ray start --head
python src/seedcore/ml/serve_app.py
```

Then open:
* `http://127.0.0.1:8000/ml/docs`

### Iterating on Code

* Update models, endpoints, or logic in `serve_app.py`.
* Restart service or use `serve.run()` reload.
* Unit tests under `tests/ml/`.

---

## 4. Deployment

### Ray Serve YAML (`serveConfigV2`)

Example:

```yaml
serveConfigV2: |
  http_options:
    host: 0.0.0.0
    port: 8000
    location: HeadOnly

  applications:
    - name: ml_service
      import_path: src.seedcore.ml.serve_app:build_ml_service
      route_prefix: /ml
```

> Note: `build_ml_service(args: dict)` must exist in `serve_app.py`.

### Deploy via Kubernetes

```bash
kubectl apply -f deploy/rayservice.yaml
```

Check status:

```bash
kubectl get RayService
kubectl describe RayService seedcore-svc
```

---

## 5. Verification & Smoke Testing

### API Docs

* Verify Swagger:
  ```
  http://<host>:8000/ml/docs
  ```
* Check `/ml/openapi.json` for registered endpoints.

### Python Smoke Test

Use [`smoke_test.py`](../deploy/smoke_test.py):

```bash
pip install requests
python3 smoke_test.py
```

Expected results:
* Salience scoring → JSON scores.
* Anomaly detection → anomalies flagged.
* Scaling prediction → recommendation.
* XGBoost → successful training & prediction.

---

## 6. Troubleshooting

| Symptom                             | Likely Cause                | Fix                                           |
| ----------------------------------- | --------------------------- | --------------------------------------------- |
| `404 Not Found`                     | Wrong `route_prefix`        | Ensure requests use `/ml/...`                 |
| `DEPLOY_FAILED`                     | Wrong `import_path` in YAML | Use `build_ml_service` function               |
| `/docs` loads but endpoints missing | App didn't start properly   | Check Ray Serve logs                          |
| Training too slow                   | Using large dataset         | Use `"use_sample_data": true` for quick tests |

Logs:

```bash
kubectl logs -f <head-pod> -c ray-head
```

---

## 7. Advanced Operations

### XGBoost Model Lifecycle

* **Train** with sample or real dataset.
* **Predict** single row or batch.
* **Tune** hyperparameters (sync or async).
* **Promote** new model if metrics improve.
* **Refresh** to reload active model.

### Async Jobs

1. Submit:
   ```bash
   POST /ml/xgboost/tune/submit
   ```
2. Poll status:
   ```bash
   GET /ml/xgboost/tune/status/{job_id}
   ```
3. List jobs:
   ```bash
   GET /ml/xgboost/tune/jobs
   ```

### CI/CD Integration

* Run `smoke_test.py` in post-deployment pipeline.
* Fail deployment if any core endpoint returns non-200.

---

## 8. Best Practices

* Always use `route_prefix` (e.g. `/ml`) to avoid conflicts.
* Separate **ML service** from **cognitive service** (`/cognitive`).
* Use **sample data** for smoke tests.
* Keep **long-running jobs** async (submit → status → fetch results).
* Monitor via Ray Dashboard (`http://<head-node>:8265`).

---

## 9. Roadmap / Future Enhancements

* Add Prometheus/Grafana metrics for inference latency & throughput.
* Auto-promote models using SLA checks.
* Add multi-model support (e.g., ensembles).
* Integrate with **SeedCore cognitive core** for higher-level reasoning.

---

## 10. Quick Commands Reference

```bash
# Health
curl http://127.0.0.1:8000/ml/health

# Salience Scoring
curl -X POST http://127.0.0.1:8000/ml/score/salience -H "Content-Type: application/json" -d '{"features":[{"type":"system_event","severity":"high"}]}'

# Anomaly Detection
curl -X POST http://127.0.0.1:8000/ml/detect/anomaly -H "Content-Type: application/json" -d '{"data":[0.1,0.2,5.0]}'

# Scaling Prediction
curl -X POST http://127.0.0.1:8000/ml/predict/scaling -H "Content-Type: application/json" -d '{"metrics":{"cpu_usage":0.8,"memory_usage":0.6}}'

# XGBoost List Models
curl http://127.0.0.1:8000/ml/xgboost/list_models
```

---

✅ With this reference, your team has a **single source of truth** for developing, deploying, and verifying the ML Service in SeedCore.
