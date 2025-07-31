# docker/serve_entrypoint.py
import ray, os, time, sys, traceback
from ray import serve
from src.seedcore.ml.serve_app import create_serve_app

RAY_ADDRESS = os.getenv("RAY_ADDRESS", "auto")
APP_NAME = "seedcore-ml"
ROUTE_PREFIX = "/ml"
MAX_DEPLOY_RETRIES = 30
DELAY = 2

def wait_for_http_ready(url, max_retries=30, delay=2):
    """Wait for HTTP endpoint to be ready."""
    import urllib.request
    for attempt in range(max_retries):
        try:
            with urllib.request.urlopen(url, timeout=5) as resp:
                if resp.status == 200:
                    print(f"✅ Service ready at {url}")
                    return True
        except Exception as e:
            if attempt < max_retries - 1:
                print(f"🔄 Service not ready ({e}); retrying in {delay}s...")
                time.sleep(delay)
            else:
                print(f"❌ Service at {url} failed to become ready after {max_retries} attempts.")
    return False

def main():
    print(f"🚀 Starting ML Serve deployment with Ray address: {RAY_ADDRESS}")
    
    while True:
        try:
            if not ray.is_initialized():
                print(f"🔧 Initializing Ray connection to {RAY_ADDRESS}...")
                ray.init(address=RAY_ADDRESS, log_to_driver=False, namespace="serve")
                print("✅ Ray connection established")

            print("🔧 Creating ML Serve application...")
            app = create_serve_app()

            print("🚀 Deploying ML application with route prefix /ml...")
            serve.run(app, name=APP_NAME, route_prefix=ROUTE_PREFIX)

            # Wait for the endpoint to be up
            print("⏳ Waiting for deployment to be ready...")
            url = f"http://localhost:8000/ml/score/salience"
            if not wait_for_http_ready(url, MAX_DEPLOY_RETRIES, DELAY):
                raise RuntimeError("Deployed service endpoint did not respond.")

            print("🟢 ML Serve deployments are live!")
            print("📊 Available endpoints:")
            print("   - Salience Scoring: /ml/score/salience")
            print("   - Anomaly Detection: /ml/detect/anomaly")
            print("   - Scaling Prediction: /ml/predict/scaling")
            print("   - Application ready at: http://localhost:8000/ml/")
            break

        except (ConnectionError, RuntimeError) as e:
            print(f"🔄 Ray or Serve not ready ({e}); retrying in 3s...")
            time.sleep(3)
        except Exception as e:
            print(f"❌ Unexpected error during deployment: {e}")
            print(f"Error type: {type(e).__name__}")
            traceback.print_exc()
            time.sleep(3)

if __name__ == "__main__":
    main() 