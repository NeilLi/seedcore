# docker/serve_entrypoint.py
import ray, os, time, sys, traceback
from ray import serve
from src.seedcore.ml.serve_app import create_serve_app

# Handle Ray initialization for both head and worker containers
RAY_ADDRESS = os.getenv("RAY_ADDRESS")
if RAY_ADDRESS:
    # We're in a worker or external environment, connect via RAY_ADDRESS
    if not ray.is_initialized():
        ray.init(address=RAY_ADDRESS, log_to_driver=False)
        print(f"✅ Connected to Ray cluster at {RAY_ADDRESS}")
    else:
        print("✅ Ray is already initialized, skipping initialization")
else:
    # Fallback: We're in the head container without RAY_ADDRESS, connect to the existing Ray instance
    if not ray.is_initialized():
        ray.init()
        print("✅ Connected to existing Ray instance in head container")
    else:
        print("✅ Ray is already initialized, skipping initialization")
# ---------------------------------------------------
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
    if RAY_ADDRESS:
        print(f"🚀 Starting ML Serve deployment with Ray address: {RAY_ADDRESS}")
    else:
        print("🚀 Starting ML Serve deployment in head container")
    
    max_attempts = 5
    attempt = 0
    
    while attempt < max_attempts:
        attempt += 1
        print(f"🔄 Attempt {attempt}/{max_attempts}")
        
        try:
            if not ray.is_initialized():
                if RAY_ADDRESS:
                    print(f"🔧 Initializing Ray connection to {RAY_ADDRESS}...")
                    # Use default namespace for Ray 2.9 compatibility
                    ray.init(address=RAY_ADDRESS, log_to_driver=False)
                    print("✅ Ray connection established in default namespace")
                else:
                    print("🔧 Connecting to existing Ray instance in head container...")
                    ray.init()
                    print("✅ Ray connection established in head container")

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

            # Safety-net that starts an HTTP proxy if one isn't present
            if not serve.status().proxies:
                print("🔧 No HTTP proxy found, starting one...")
                serve.start(detached=True,
                            http_options={"host": "0.0.0.0", "port": 8000})
                print("✅ HTTP proxy started")

            print("🔧 Creating ML Serve application...")
            app = create_serve_app()

            print("🚀 Deploying ML application...")
            # Deploy in default namespace for Ray 2.9 compatibility
            # HTTP options are configured in serve.start() for Ray 2.33.0 compatibility
            serve.run(
                app, 
                name=APP_NAME
            )

            # Wait for the endpoint to be up
            print("⏳ Waiting for deployment to be ready...")
            url = f"http://localhost:8000/health"
            if not wait_for_http_ready(url, MAX_DEPLOY_RETRIES, DELAY):
                raise RuntimeError("Deployed service endpoint did not respond.")

            # Initialize XGBoost service (after Ray and Serve are ready)
            print("🔧 Initializing XGBoost service...")
            try:
                # Import and initialize XGBoost service directly (avoid subprocess for better integration)
                from seedcore.ml.models.xgboost_service import get_xgboost_service
                
                # Get the service instance (this will use the already initialized Ray)
                xgb_service = get_xgboost_service()
                
                if xgb_service is None:
                    raise RuntimeError("Failed to get XGBoost service instance")
                
                print("✅ XGBoost service initialized successfully")
                
                # Test basic functionality
                print("🧪 Testing XGBoost service functionality...")
                test_dataset = xgb_service.create_sample_dataset(n_samples=100, n_features=5)
                print(f"✅ XGBoost service test passed - created dataset with {test_dataset.count()} samples")
                
            except Exception as e:
                print(f"⚠️ XGBoost service initialization warning: {e}")
                print("   XGBoost endpoints may not work properly")
                # Don't fail the entire deployment for XGBoost issues

            print("🟢 ML Serve deployments are live!")
            print("📊 Available endpoints:")
            print("   - Salience Scoring: /score/salience")
            print("   - Anomaly Detection: /detect/anomaly")
            print("   - Scaling Prediction: /predict/scaling")
            print("   - XGBoost Training: /xgboost/train")
            print("   - XGBoost Prediction: /xgboost/predict")
            print("   - XGBoost Batch Prediction: /xgboost/batch_predict")
            print("   - XGBoost Model Management: /xgboost/list_models, /xgboost/model_info")
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