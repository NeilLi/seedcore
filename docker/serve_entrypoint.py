# docker/serve_entrypoint.py
import ray, os, time
from ray import serve
from src.seedcore.ml.serve_app import create_serve_app

# When running in the head container, connect to local Ray instance
RAY_ADDRESS = os.getenv("RAY_ADDRESS", "ray://localhost:10001")

while True:
    try:
        # Check if Ray is already initialized
        if not ray.is_initialized():
            ray.init(address=RAY_ADDRESS, log_to_driver=False, namespace="serve")
        
        # Connect to existing Serve instance (connect() is deprecated in newer versions)
        # serve.connect()

        app = create_serve_app()  # returns a single deployment
        serve.run(app, name="seedcore-ml", route_prefix="/ml")  # deploy with name and route prefix

        print("🟢 ML Serve deployments are live!")
        print("📊 Available endpoints:")
        print("   - Salience Scoring: /ml/score/salience")
        print("   - Anomaly Detection: /ml/detect/anomaly")
        print("   - Scaling Prediction: /ml/predict/scaling")
        print("   - Application ready at: http://localhost:8000/ml/")
        
        # Exit successfully since we're running in the head container
        break
    except (ConnectionError, RuntimeError) as e:
        print(f"🔄 Ray not ready ({e}); retrying in 3 s …")
        time.sleep(3) 