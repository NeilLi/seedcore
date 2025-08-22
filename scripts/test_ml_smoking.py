#!/usr/bin/env python3
import requests
import json

BASE_URL = "http://127.0.0.1:8000/ml"

def pretty_print(title, resp):
    print(f"\n=== {title} ===")
    print(f"Status: {resp.status_code}")
    try:
        print(json.dumps(resp.json(), indent=2))
    except Exception:
        print(resp.text)

def main():
    # 1. Salience Scoring
    resp = requests.post(f"{BASE_URL}/score/salience", json={
        "features": [
            {"type": "system_event", "severity": "high", "frequency": 0.8},
            {"type": "user_interaction", "engagement": 0.6, "duration": 120},
            {"type": "resource_usage", "cpu": 0.9, "memory": 0.7}
        ]
    })
    pretty_print("Salience Scoring", resp)

    # 2. Anomaly Detection
    resp = requests.post(f"{BASE_URL}/detect/anomaly", json={
        "data": [0.95, 0.3, 0.1, 0.85, 0.2]
    })
    pretty_print("Anomaly Detection", resp)

    # 3. Scaling Prediction
    resp = requests.post(f"{BASE_URL}/predict/scaling", json={
        "metrics": {"cpu_usage": 0.7, "memory_usage": 0.6}
    })
    pretty_print("Scaling Prediction", resp)

    # 4a. XGBoost Train
    resp = requests.post(f"{BASE_URL}/xgboost/train", json={
        "use_sample_data": True,
        "sample_size": 100,
        "sample_features": 5,
        "label_column": "target",
        "name": "test_model"
    })
    pretty_print("XGBoost Train", resp)

    # 4b. XGBoost Predict
    resp = requests.post(f"{BASE_URL}/xgboost/predict", json={
        "features": [[0.1,0.2,0.3,0.4,0.5]]
    })
    pretty_print("XGBoost Predict", resp)

    # 4e. List Models
    resp = requests.get(f"{BASE_URL}/xgboost/list_models")
    pretty_print("List Models", resp)

    # 4f. Model Info
    resp = requests.get(f"{BASE_URL}/xgboost/model_info")
    pretty_print("Model Info", resp)

if __name__ == "__main__":
    main()
