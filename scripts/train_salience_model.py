#!/usr/bin/env python3
"""
Train Salience Scoring Model

This script trains a GradientBoostingRegressor model for salience scoring
using historical flashbulb incident data.
"""

import sys
import os
import json
import numpy as np
from typing import List, Dict, Any
import logging

# Add the project root to the Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.seedcore.ml.salience.scorer import SalienceScorer
from src.seedcore.memory.flashbulb_memory import FlashbulbMemoryManager
from src.seedcore.database import get_mysql_session

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def generate_synthetic_training_data(num_samples: int = 1000) -> tuple:
    """Generate synthetic training data for model training."""
    logger.info(f"Generating {num_samples} synthetic training samples")
    
    training_data = []
    salience_scores = []
    
    for i in range(num_samples):
        # Generate random features
        features = {
            'task_risk': np.random.uniform(0.1, 1.0),
            'failure_severity': np.random.uniform(0.1, 1.0),
            'agent_capability': np.random.uniform(0.2, 1.0),
            'system_load': np.random.uniform(0.1, 1.0),
            'memory_usage': np.random.uniform(0.1, 1.0),
            'cpu_usage': np.random.uniform(0.1, 1.0),
            'response_time': np.random.uniform(0.1, 5.0),
            'error_rate': np.random.uniform(0.0, 0.3),
            'task_complexity': np.random.uniform(0.1, 1.0),
            'user_impact': np.random.uniform(0.1, 1.0),
            'business_criticality': np.random.uniform(0.1, 1.0),
            'agent_memory_util': np.random.uniform(0.0, 1.0)
        }
        
        # Generate synthetic salience score based on features
        # Higher scores for high-risk, high-severity, high-impact events
        base_score = (
            features['task_risk'] * 0.3 +
            features['failure_severity'] * 0.3 +
            features['user_impact'] * 0.2 +
            features['business_criticality'] * 0.2
        )
        
        # Add some noise and ensure it's between 0 and 1
        score = base_score + np.random.normal(0, 0.1)
        score = max(0.0, min(1.0, score))
        
        training_data.append(features)
        salience_scores.append(score)
    
    return training_data, salience_scores

def load_historical_incidents() -> tuple:
    """Load historical incidents from flashbulb memory."""
    try:
        logger.info("Loading historical incidents from flashbulb memory")
        
        # Get database session
        db = next(get_mysql_session())
        
        # Initialize flashbulb memory manager
        fbm = FlashbulbMemoryManager()
        
        # Get all incidents
        incidents = fbm.get_incidents_by_time_range(
            db, 
            start_time="2020-01-01T00:00:00Z",
            end_time="2025-12-31T23:59:59Z"
        )
        
        if not incidents:
            logger.warning("No historical incidents found, using synthetic data")
            return generate_synthetic_training_data()
        
        logger.info(f"Loaded {len(incidents)} historical incidents")
        
        # Extract features and scores from incidents
        training_data = []
        salience_scores = []
        
        for incident in incidents:
            event_data = incident['event_data']
            salience_score = incident['salience_score']
            
            # Extract features from event data
            features = {
                'task_risk': event_data.get('failed_task', {}).get('risk', 0.5),
                'failure_severity': 1.0,  # All incidents are failures
                'agent_capability': event_data.get('agent_state', {}).get('performance_metrics', {}).get('capability_score_c', 0.5),
                'system_load': 0.5,  # Default value
                'memory_usage': 0.5,  # Default value
                'cpu_usage': 0.5,     # Default value
                'response_time': 1.0,  # Default value
                'error_rate': 0.1,    # Default value
                'task_complexity': event_data.get('failed_task', {}).get('complexity', 0.5),
                'user_impact': event_data.get('failed_task', {}).get('user_impact', 0.5),
                'business_criticality': event_data.get('failed_task', {}).get('business_criticality', 0.5),
                'agent_memory_util': event_data.get('agent_state', {}).get('performance_metrics', {}).get('mem_util', 0.0)
            }
            
            training_data.append(features)
            salience_scores.append(salience_score)
        
        return training_data, salience_scores
        
    except Exception as e:
        logger.error(f"Error loading historical incidents: {e}")
        logger.info("Falling back to synthetic data")
        return generate_synthetic_training_data()

def train_model(training_data: List[Dict[str, Any]], 
                salience_scores: List[float],
                model_path: str = None) -> Dict[str, Any]:
    """Train the salience scoring model."""
    try:
        logger.info("Training salience scoring model")
        
        # Initialize scorer
        scorer = SalienceScorer()
        
        # Train model
        results = scorer.train_model(training_data, salience_scores, model_path)
        
        if "error" in results:
            logger.error(f"Training failed: {results['error']}")
            return results
        
        logger.info("✅ Model training completed successfully")
        logger.info(f"   Model saved to: {results['model_path']}")
        logger.info(f"   MSE: {results['mse']:.4f}")
        logger.info(f"   R²: {results['r2']:.4f}")
        
        return results
        
    except Exception as e:
        logger.error(f"Error training model: {e}")
        return {"error": str(e)}

def test_model(model_path: str, test_samples: int = 10):
    """Test the trained model with sample data."""
    try:
        logger.info("Testing trained model")
        
        # Initialize scorer with trained model
        scorer = SalienceScorer(model_path)
        
        # Generate test data
        test_data, _ = generate_synthetic_training_data(test_samples)
        
        # Score test data
        scores = scorer.score_features(test_data)
        
        logger.info("✅ Model testing completed")
        logger.info(f"   Test samples: {len(test_data)}")
        logger.info(f"   Average score: {np.mean(scores):.3f}")
        logger.info(f"   Score range: {np.min(scores):.3f} - {np.max(scores):.3f}")
        
        # Show a few examples
        for i in range(min(3, len(test_data))):
            logger.info(f"   Sample {i+1}: {scores[i]:.3f}")
        
        return True
        
    except Exception as e:
        logger.error(f"Error testing model: {e}")
        return False

def main():
    """Main training function."""
    logger.info("🎯 Salience Model Training")
    logger.info("=" * 50)
    
    # Configuration
    model_path = "src/seedcore/ml/models/salience_model.pkl"
    num_samples = 1000
    
    # Load training data
    training_data, salience_scores = load_historical_incidents()
    
    if len(training_data) < 100:
        logger.warning(f"Only {len(training_data)} samples available, generating synthetic data")
        training_data, salience_scores = generate_synthetic_training_data(num_samples)
    
    logger.info(f"Training data: {len(training_data)} samples")
    logger.info(f"Salience score range: {min(salience_scores):.3f} - {max(salience_scores):.3f}")
    
    # Train model
    results = train_model(training_data, salience_scores, model_path)
    
    if "error" in results:
        logger.error("❌ Training failed")
        return False
    
    # Test model
    if not test_model(model_path):
        logger.error("❌ Model testing failed")
        return False
    
    logger.info("🎉 Model training and testing completed successfully!")
    logger.info(f"📁 Model saved to: {model_path}")
    logger.info("🚀 Ready for deployment with Ray Serve")
    
    return True

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1) 