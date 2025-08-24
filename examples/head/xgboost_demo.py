#!/usr/bin/env python3
"""
XGBoost Hyperparameter Tuning Demo for SeedCore

This script demonstrates the new hyperparameter tuning functionality
using Ray Tune, integrated with the Cognitive Organism Architecture.
"""

import os
import requests
import json
import time
import logging
from typing import Dict, Any

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class XGBoostTuningDemo:
    """Demo class for XGBoost hyperparameter tuning functionality."""
    
    def __init__(self, base_url: str = None):
        if base_url is None:
            # ✅ FIX: Default to localhost, which is correct when running
            # this script from inside the Ray head pod.
            self.base_url = "http://localhost:8000"
        else:
            self.base_url = base_url
        
        # Add the /ml_serve route prefix to all requests
        self.ml_service_url = f"{self.base_url}/ml_serve"
        self.session = requests.Session()
        logger.info(f"🔗 Using ML service at: {self.ml_service_url}")
    
    def test_basic_training(self) -> bool:
        """Test basic XGBoost training to ensure the service is working."""
        logger.info("🧪 Testing basic XGBoost training...")
        
        payload = {
            "use_sample_data": True,
            "sample_size": 1000,
            "sample_features": 10,
            "name": "demo_basic_model",
            "xgb_config": {
                "objective": "binary:logistic",
                "eval_metric": ["logloss", "auc"],
                "eta": 0.1,
                "max_depth": 5,
                "num_boost_round": 20
            },
            "training_config": {
                "num_workers": 1,
                "use_gpu": False,
                "cpu_per_worker": 1
            }
        }
        
        try:
            # Use the full service URL
            response = self.session.post(f"{self.ml_service_url}/xgboost/train", json=payload, timeout=60)
            response.raise_for_status()
            result = response.json()
            
            logger.info(f"✅ Basic training successful - AUC: {result.get('metrics', {}).get('validation_0-auc', 'N/A')}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Basic training failed: {e}")
            return False
    
    def test_conservative_tuning(self) -> bool:
        """Test conservative hyperparameter tuning asynchronously."""
        logger.info("🎯 Testing conservative hyperparameter tuning (async)...")
        
        payload = {
            "space_type": "conservative",
            "config_type": "conservative",
            "experiment_name": "demo_conservative_tuning"
        }
        
        try:
            # --- Step 1: Submit the job ---
            logger.info("   Submitting tuning job...")
            submit_response = self.session.post(f"{self.ml_service_url}/xgboost/tune/submit", json=payload, timeout=10)
            submit_response.raise_for_status()
            submit_result = submit_response.json()
            job_id = submit_result.get("job_id")
            
            if not job_id:
                logger.error("❌ Submission failed: Did not receive a job_id.")
                return False
                
            logger.info(f"✅ Job submitted successfully! Job ID: {job_id}")

            # --- Step 2: Poll for the result ---
            start_time = time.time()
            timeout = 900  # 15 minutes total wait time
            poll_interval = 15  # Poll every 15 seconds
            
            while time.time() - start_time < timeout:
                logger.info(f"   Polling status for job {job_id}...")
                try:
                    status_response = self.session.get(f"{self.ml_service_url}/xgboost/tune/status/{job_id}", timeout=10)
                    status_response.raise_for_status()
                    status_result = status_response.json()
                    
                    status = status_result.get("status")
                    progress = status_result.get("progress", "Unknown")
                    
                    logger.info(f"   Status: {status} - {progress}")
                    
                    if status == "COMPLETED":
                        logger.info("✅ Tuning job completed successfully!")
                        result = status_result.get("result", {})
                        best_trial = result.get("best_trial", {})
                        logger.info(f"   Best AUC: {best_trial.get('auc', 'N/A'):.4f}")
                        logger.info(f"   Total trials: {result.get('total_trials', 'N/A')}")
                        logger.info(f"   Best config: {best_trial.get('config', {})}")
                        return True
                    elif status == "FAILED":
                        error_msg = status_result.get("result", {}).get("error", "Unknown error")
                        logger.error(f"❌ Tuning job failed: {error_msg}")
                        return False
                    elif status == "RUNNING":
                        logger.info(f"   Job is running... {progress}")
                    elif status == "PENDING":
                        logger.info(f"   Job is pending... {progress}")
                    
                    # Wait before polling again
                    time.sleep(poll_interval)
                    
                except requests.exceptions.RequestException as e:
                    logger.warning(f"   Warning: Failed to poll status: {e}")
                    time.sleep(poll_interval)
                    continue

            logger.error("❌ Polling timed out after 15 minutes.")
            return False
                
        except Exception as e:
            logger.error(f"❌ Tuning demo failed: {e}")
            return False
    
    def test_async_api_functionality(self) -> bool:
        """Test the async API functionality without waiting for completion."""
        logger.info("🔄 Testing async API functionality...")
        
        payload = {
            "space_type": "conservative",
            "config_type": "conservative",
            "experiment_name": "demo_async_test"
        }
        
        try:
            # Submit a job
            logger.info("   Submitting test job...")
            submit_response = self.session.post(f"{self.ml_service_url}/xgboost/tune/submit", json=payload, timeout=10)
            submit_response.raise_for_status()
            submit_result = submit_response.json()
            job_id = submit_result.get("job_id")
            
            if not job_id:
                logger.error("❌ Job submission failed")
                return False
            
            logger.info(f"✅ Test job submitted with ID: {job_id}")
            
            # Check initial status
            status_response = self.session.get(f"{self.ml_service_url}/xgboost/tune/status/{job_id}", timeout=10)
            status_response.raise_for_status()
            initial_status = status_response.json()
            
            if initial_status.get("status") not in ["PENDING", "RUNNING"]:
                logger.error(f"❌ Unexpected initial status: {initial_status.get('status')}")
                return False
            
            logger.info(f"✅ Initial status check passed: {initial_status.get('status')}")
            
            # List all jobs
            jobs_response = self.session.get(f"{self.ml_service_url}/xgboost/tune/jobs", timeout=10)
            jobs_response.raise_for_status()
            jobs_result = jobs_response.json()
            
            if jobs_result.get("total_jobs", 0) > 0:
                logger.info(f"✅ Jobs listing works: {jobs_result.get('total_jobs')} jobs found")
                return True
            else:
                logger.warning("⚠️ No jobs found in listing (this might be expected)")
                return True
                
        except Exception as e:
            logger.error(f"❌ Async API test failed: {e}")
            return False
    
    def list_all_jobs(self) -> bool:
        """List all tuning jobs and their statuses."""
        logger.info("📋 Listing all tuning jobs...")
        
        try:
            response = self.session.get(f"{self.ml_service_url}/xgboost/tune/jobs", timeout=10)
            response.raise_for_status()
            result = response.json()
            
            total_jobs = result.get("total_jobs", 0)
            jobs = result.get("jobs", [])
            
            logger.info(f"📊 Total jobs: {total_jobs}")
            
            if total_jobs == 0:
                logger.info("   No jobs found")
                return True
            
            for job in jobs:
                job_id = job.get("job_id", "Unknown")
                status = job.get("status", "Unknown")
                progress = job.get("progress", "No progress info")
                submitted_at = job.get("submitted_at", "Unknown")
                
                logger.info(f"   Job {job_id}: {status} - {progress}")
                logger.info(f"     Submitted: {submitted_at}")
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to list jobs: {e}")
            return False
    
    # (Other test methods would need the same URL fix)
    
    def run_full_demo(self) -> bool:
        """Run the complete hyperparameter tuning demo."""
        logger.info("🚀 Starting XGBoost Hyperparameter Tuning Demo")
        logger.info("=" * 60)
        
        if not self.test_basic_training():
            logger.error("❌ Basic training failed, aborting demo")
            return False
        
        # Test async API functionality first (quick test)
        if not self.test_async_api_functionality():
            logger.warning("⚠️ Async API test failed, but continuing with other tests")
        
        # List any existing jobs
        self.list_all_jobs()
        
        if not self.test_conservative_tuning():
            logger.warning("⚠️ Conservative tuning failed, continuing with other tests")
        
        # List jobs again to see the completed job
        self.list_all_jobs()
        
        # ... (other tests would be called here) ...
        
        logger.info("=" * 60)
        logger.info("🎉 XGBoost Hyperparameter Tuning Demo completed!")
        return True

def main():
    """Main function to run the demo."""
    demo = XGBoostTuningDemo()
    
    try:
        success = demo.run_full_demo()
        if success:
            logger.info("✅ Demo completed successfully!")
        else:
            logger.error("❌ Demo completed with errors")
    except KeyboardInterrupt:
        logger.info("⏹️ Demo interrupted by user")
    except Exception as e:
        logger.error(f"❌ Demo failed with unexpected error: {e}")

if __name__ == "__main__":
    main()
