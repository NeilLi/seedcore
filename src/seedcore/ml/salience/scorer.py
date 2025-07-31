"""
Salience Scoring Module

Provides ML-based salience scoring for ranking and prioritizing:
- System events and alerts
- Resource utilization patterns
- User interactions and behaviors
"""

import numpy as np
import pickle
import os
from typing import List, Dict, Any, Optional
import logging
from pathlib import Path

# Import scikit-learn components
try:
    from sklearn.ensemble import GradientBoostingRegressor
    from sklearn.preprocessing import StandardScaler, LabelEncoder
    from sklearn.model_selection import train_test_split
    from sklearn.metrics import mean_squared_error, r2_score
    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False
    GradientBoostingRegressor = None
    StandardScaler = None
    LabelEncoder = None

logger = logging.getLogger(__name__)

class SalienceScorer:
    """ML-based salience scoring for system events and interactions."""
    
    def __init__(self, model_path: Optional[str] = None):
        """Initialize the salience scorer."""
        self.model_path = model_path or self._get_default_model_path()
        self.model = None
        self.scaler = None
        self.label_encoders = {}
        self.feature_names = [
            'task_risk', 'failure_severity', 'agent_capability', 'system_load',
            'memory_usage', 'cpu_usage', 'response_time', 'error_rate',
            'task_complexity', 'user_impact', 'business_criticality'
        ]
        
        self.model = self._load_model()
        logger.info("SalienceScorer initialized")
    
    def _get_default_model_path(self) -> str:
        """Get the default path for the trained model."""
        # Look for model in the ML models directory
        ml_dir = Path(__file__).parent.parent
        model_path = ml_dir / "models" / "salience_model.pkl"
        return str(model_path)
    
    def _load_model(self):
        """Load the salience scoring model."""
        if not SKLEARN_AVAILABLE:
            logger.warning("scikit-learn not available, falling back to simple model")
            return self._simple_scoring_model
        
        try:
            if os.path.exists(self.model_path):
                with open(self.model_path, 'rb') as f:
                    model_data = pickle.load(f)
                
                self.model = model_data['model']
                self.scaler = model_data.get('scaler')
                self.label_encoders = model_data.get('label_encoders', {})
                logger.info(f"✅ Loaded trained salience model from {self.model_path}")
                return self._ml_scoring_model
            else:
                logger.warning(f"Model file not found at {self.model_path}, using simple model")
                return self._simple_scoring_model
                
        except Exception as e:
            logger.error(f"Error loading model: {e}, falling back to simple model")
            return self._simple_scoring_model
    
    def _extract_features(self, features: Dict[str, Any]) -> np.ndarray:
        """Extract and normalize features for ML model."""
        feature_vector = []
        
        # Task-related features
        feature_vector.append(features.get('task_risk', 0.5))
        feature_vector.append(features.get('failure_severity', 0.5))
        feature_vector.append(features.get('task_complexity', 0.5))
        
        # Agent-related features
        feature_vector.append(features.get('agent_capability', 0.5))
        feature_vector.append(features.get('agent_memory_util', 0.0))
        
        # System-related features
        feature_vector.append(features.get('system_load', 0.5))
        feature_vector.append(features.get('memory_usage', 0.5))
        feature_vector.append(features.get('cpu_usage', 0.5))
        feature_vector.append(features.get('response_time', 1.0))
        feature_vector.append(features.get('error_rate', 0.0))
        
        # Business-related features
        feature_vector.append(features.get('user_impact', 0.5))
        feature_vector.append(features.get('business_criticality', 0.5))
        
        # Convert to numpy array
        feature_array = np.array(feature_vector).reshape(1, -1)
        
        # Apply scaling if available
        if self.scaler is not None:
            feature_array = self.scaler.transform(feature_array)
        
        return feature_array
    
    def _ml_scoring_model(self, features: Dict[str, Any]) -> float:
        """ML-based scoring model using trained GradientBoostingRegressor."""
        try:
            # Extract and normalize features
            feature_array = self._extract_features(features)
            
            # Make prediction
            score = self.model.predict(feature_array)[0]
            
            # Ensure score is between 0 and 1
            score = max(0.0, min(1.0, score))
            
            return score
            
        except Exception as e:
            logger.error(f"Error in ML scoring: {e}, falling back to simple model")
            return self._simple_scoring_model(features)
    
    def _simple_scoring_model(self, features: Dict[str, Any]) -> float:
        """Simple scoring model based on feature importance (fallback)."""
        score = 0.0
        
        # Task risk and severity
        task_risk = features.get('task_risk', 0.5)
        failure_severity = features.get('failure_severity', 0.5)
        score += task_risk * failure_severity * 0.4
        
        # Agent capability
        agent_capability = features.get('agent_capability', 0.5)
        score += agent_capability * 0.2
        
        # System load
        system_load = features.get('system_load', 0.5)
        memory_usage = features.get('memory_usage', 0.5)
        cpu_usage = features.get('cpu_usage', 0.5)
        score += (system_load + memory_usage + cpu_usage) / 3 * 0.2
        
        # Business impact
        user_impact = features.get('user_impact', 0.5)
        business_criticality = features.get('business_criticality', 0.5)
        score += (user_impact + business_criticality) / 2 * 0.2
        
        # Add small randomness for demonstration
        score += np.random.uniform(-0.05, 0.05)
        
        return max(0.0, min(1.0, score))
    
    def score_features(self, features: List[Dict[str, Any]]) -> List[float]:
        """Score a list of features and return salience scores."""
        try:
            scores = [self.model(feature) for feature in features]
            logger.info(f"Scored {len(features)} features")
            return scores
        except Exception as e:
            logger.error(f"Error in salience scoring: {e}")
            return [0.0] * len(features)
    
    def get_top_features(self, features: List[Dict[str, Any]], top_k: int = 5) -> List[Dict[str, Any]]:
        """Get the top-k most salient features."""
        if not features:
            return []
        
        # Score all features
        scores = self.score_features(features)
        
        # Create feature-score pairs
        feature_scores = list(zip(features, scores))
        
        # Sort by score (descending) and return top-k
        feature_scores.sort(key=lambda x: x[1], reverse=True)
        
        # Return features with their scores
        top_features = []
        for feature, score in feature_scores[:top_k]:
            feature_with_score = feature.copy()
            feature_with_score["salience_score"] = score
            top_features.append(feature_with_score)
        
        return top_features
    
    def train_model(self, training_data: List[Dict[str, Any]], 
                   salience_scores: List[float], 
                   save_path: Optional[str] = None) -> Dict[str, float]:
        """Train the salience scoring model on historical data."""
        if not SKLEARN_AVAILABLE:
            logger.error("scikit-learn not available for training")
            return {"error": "scikit-learn not available"}
        
        try:
            logger.info(f"Training salience model on {len(training_data)} samples")
            
            # Extract features
            X = []
            for data_point in training_data:
                feature_vector = self._extract_features(data_point).flatten()
                X.append(feature_vector)
            
            X = np.array(X)
            y = np.array(salience_scores)
            
            # Split data
            X_train, X_test, y_train, y_test = train_test_split(
                X, y, test_size=0.2, random_state=42
            )
            
            # Initialize and train model
            self.model = GradientBoostingRegressor(
                n_estimators=100,
                learning_rate=0.1,
                max_depth=5,
                random_state=42
            )
            
            self.model.fit(X_train, y_train)
            
            # Evaluate model
            y_pred = self.model.predict(X_test)
            mse = mean_squared_error(y_test, y_pred)
            r2 = r2_score(y_test, y_pred)
            
            # Initialize scaler
            self.scaler = StandardScaler()
            self.scaler.fit(X_train)
            
            # Save model
            save_path = save_path or self.model_path
            os.makedirs(os.path.dirname(save_path), exist_ok=True)
            
            model_data = {
                'model': self.model,
                'scaler': self.scaler,
                'label_encoders': self.label_encoders,
                'feature_names': self.feature_names
            }
            
            with open(save_path, 'wb') as f:
                pickle.dump(model_data, f)
            
            logger.info(f"✅ Model trained and saved to {save_path}")
            logger.info(f"   MSE: {mse:.4f}, R²: {r2:.4f}")
            
            return {
                "mse": mse,
                "r2": r2,
                "model_path": save_path
            }
            
        except Exception as e:
            logger.error(f"Error training model: {e}")
            return {"error": str(e)}

class SalienceModel:
    """Alternative interface for salience scoring."""
    
    def __init__(self, model_path: Optional[str] = None):
        """Initialize the salience model."""
        self.scorer = SalienceScorer(model_path)
    
    def predict(self, features: List[Dict[str, Any]]) -> List[float]:
        """Predict salience scores for features."""
        return self.scorer.score_features(features)
    
    def train(self, training_data: List[Dict[str, Any]], 
              salience_scores: List[float]) -> Dict[str, float]:
        """Train the model on historical data."""
        return self.scorer.train_model(training_data, salience_scores) 