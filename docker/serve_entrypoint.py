# docker/serve_entrypoint.py
import ray, os, time
from ray import serve
from src.seedcore.ml.serve_app import create_serve_app

RAY_ADDRESS = os.getenv("RAY_ADDRESS", "ray://seedcore-ray-head:10001")

while True:
    try:
        # Check if Ray is already initialized
        if not ray.is_initialized():
            ray.init(address=RAY_ADDRESS, log_to_driver=False, namespace="serve")
        
        # Connect to existing Serve instance
        serve.connect()

        app = create_serve_app()  # returns a single deployment
        serve.run(app, name="seedcore-ml")  # deploy with name

        print("🟢 Serve deployments are live. Blocking to keep container up ...")
        print("📊 Available endpoints:")
        print("   - Salience Scoring: /")
        print("   - Application ready at: http://localhost:8000/")
        
        while True:
            time.sleep(3600)
    except (ConnectionError, RuntimeError) as e:
        print(f"🔄 Ray not ready ({e}); retrying in 3 s …")
        time.sleep(3) 