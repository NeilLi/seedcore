# docker/serve_entrypoint.py
import ray, os, time, sys, traceback
from ray import serve
from src.seedcore.ml.serve_app import create_serve_app

RAY_ADDRESS = os.getenv("RAY_ADDRESS", "auto")
APP_NAME = "seedcore-ml"
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
    
    max_attempts = 5
    attempt = 0
    
    while attempt < max_attempts:
        attempt += 1
        print(f"🔄 Attempt {attempt}/{max_attempts}")
        
        try:
            if not ray.is_initialized():
                print(f"🔧 Initializing Ray connection to {RAY_ADDRESS}...")
                # Use default namespace for Ray 2.9 compatibility
                ray.init(address=RAY_ADDRESS, log_to_driver=False)
                print("✅ Ray connection established in default namespace")

            # Wait a bit for Ray to be fully ready
            print("⏳ Waiting for Ray to be fully ready...")
            time.sleep(10)
            
            # Check Ray cluster resources
            print("🔍 Checking Ray cluster resources...")
            try:
                cluster_resources = ray.cluster_resources()
                print(f"✅ Ray cluster resources: {cluster_resources}")
            except Exception as e:
                print(f"⚠️ Could not get cluster resources: {e}")

            # Check if Serve is already running and connect to it
            print("🔧 Checking existing Serve instance...")
            try:
                serve_status = serve.status()
                print(f"✅ Found existing Serve instance: {serve_status}")
            except Exception as e:
                print(f"⚠️ No existing Serve instance found: {e}")
                # Start Serve if not running
                print("🔧 Starting new Serve instance...")
                serve.start(
                    http_options={
                        'host': '0.0.0.0',
                        'port': 8000
                    },
                    detached=True
                )
                print("✅ Serve instance started")

            print("🔧 Creating ML Serve application...")
            app = create_serve_app()

            print("🚀 Deploying ML application...")
            # Deploy in default namespace for Ray 2.9 compatibility
            # HTTP options are configured in serve.start() for Ray 2.20.0 compatibility
            serve.run(
                app, 
                name=APP_NAME
            )

            # Wait for the endpoint to be up
            print("⏳ Waiting for deployment to be ready...")
            url = f"http://localhost:8000/health"
            if not wait_for_http_ready(url, MAX_DEPLOY_RETRIES, DELAY):
                raise RuntimeError("Deployed service endpoint did not respond.")

            print("🟢 ML Serve deployments are live!")
            print("📊 Available endpoints:")
            print("   - Salience Scoring: /score/salience")
            print("   - Anomaly Detection: /detect/anomaly")
            print("   - Scaling Prediction: /predict/scaling")
            print("   - Health Check: /health")
            print("   - Application ready at: http://localhost:8000/")
            break

        except (ConnectionError, RuntimeError) as e:
            print(f"🔄 Ray or Serve not ready ({e}); retrying in 10s...")
            if attempt >= max_attempts:
                print(f"❌ Failed after {max_attempts} attempts. Exiting.")
                sys.exit(1)
            time.sleep(10)
        except Exception as e:
            print(f"❌ Unexpected error during deployment: {e}")
            print(f"Error type: {type(e).__name__}")
            traceback.print_exc()
            if attempt >= max_attempts:
                print(f"❌ Failed after {max_attempts} attempts. Exiting.")
                sys.exit(1)
            time.sleep(10)

if __name__ == "__main__":
    main() 