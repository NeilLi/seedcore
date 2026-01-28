#!/usr/bin/env python3
"""
Salience Model Training Script

This script trains the salience scoring model and saves it to the models directory.
It can be run manually or as part of CI/CD pipeline.
"""

import sys
import logging
from pathlib import Path

# Add project root to path (needed for other imports)
project_root = Path(__file__).parent.parent.parent.parent.parent
sys.path.insert(0, str(project_root))

# Import after path modification
from src.seedcore.ml.salience.scorer import SalienceScorer  # noqa

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def main():
    """Train the salience model and save it."""
    try:
        logger.info("🚀 Starting salience model training...")
        
        # Create models directory if it doesn't exist
        models_dir = project_root / "src" / "seedcore" / "ml" / "models"
        models_dir.mkdir(parents=True, exist_ok=True)
        
        # Initialize scorer
        model_path = str(models_dir / "salience_model.pkl")
        scorer = SalienceScorer(model_path=model_path)
        
        # Generate training data (synthetic for now)
        # In production, this would load from flashbulb memory
        logger.info("📊 Generating training data...")
        from src.seedcore.ml.salience.train_salience_model import generate_synthetic_training_data  # noqa: E402
        training_data, salience_scores = generate_synthetic_training_data(1000)
        
        # Train the model (saves automatically)
        logger.info("📊 Training salience model...")
        results = scorer.train_model(training_data, salience_scores, save_path=model_path)
        
        if "error" in results:
            logger.error(f"Training failed: {results['error']}")
            return 1
        
        logger.info(f"✅ Model trained and saved to {model_path}")
        logger.info(f"   MSE: {results['mse']:.4f}, R²: {results['r2']:.4f}")
        
        # Test the model
        logger.info("🧪 Testing trained model...")
        test_features = {
            'task_risk': 0.8,
            'failure_severity': 0.9,
            'agent_capability': 0.7,
            'system_load': 0.6,
            'memory_usage': 0.5,
            'cpu_usage': 0.4,
            'response_time': 2.0,
            'error_rate': 0.1,
            'task_complexity': 0.8,
            'user_impact': 0.9,
            'business_criticality': 0.8,
            'agent_memory_util': 0.3
        }
        
        score = scorer.score_features([test_features])[0]
        logger.info(f"✅ Test prediction: {score:.3f}")
        
        return 0
        
    except Exception as e:
        logger.error(f"❌ Training failed: {e}")
        return 1

if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code) 