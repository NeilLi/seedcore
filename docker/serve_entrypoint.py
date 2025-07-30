# docker/serve_entrypoint.py
import os, time, ray
from ray import serve
from src.seedcore.ml.serve_app import create_serve_app

RAY_ADDRESS = os.getenv("RAY_ADDRESS", "ray://seedcore-ray-head:10001")

while True:
    try:
        ray.init(address=RAY_ADDRESS, namespace="serve")  # namespace avoids resource leaks
        serve.start(detached=True)                        # no RuntimeError if Serve already running

        app = create_serve_app()                          # returns a deployment graph
        serve.run(app, name="seedcore-ml", route_prefix="/")  # idempotent

        print("🟢 Serve app is live. Blocking to keep container up ...")
        print("📊 Available endpoints:")
        print("   - Salience Scoring: /SalienceScorer")
        print("   - Anomaly Detection: /AnomalyDetector") 
        print("   - Scaling Prediction: /ScalingPredictor")
        
        while True:
            time.sleep(3600)
    except (ConnectionError, RuntimeError) as e:
        print(f"🔄 Ray not ready ({e}); retrying in 3 s …")
        time.sleep(3) 