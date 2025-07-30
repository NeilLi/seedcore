"""
Salience Scoring Module

Provides ML-based salience scoring for ranking and prioritizing:
- System events and alerts
- Resource utilization patterns
- User interactions and behaviors
"""

import numpy as np
from typing import List, Dict, Any
import logging

logger = logging.getLogger(__name__)

class SalienceScorer:
    """ML-based salience scoring for system events and interactions."""
    
    def __init__(self):
        """Initialize the salience scorer."""
        self.model = self._load_model()
        logger.info("SalienceScorer initialized")
    
    def _load_model(self):
        """Load the salience scoring model."""
        # TODO: Implement actual model loading
        # For now, return a simple scoring function based on feature importance
        return self._simple_scoring_model
    
    def _simple_scoring_model(self, features: Dict[str, Any]) -> float:
        """Simple scoring model based on feature importance."""
        score = 0.0
        
        # System event scoring
        if features.get("type") == "system_event":
            severity = features.get("severity", "low")
            frequency = features.get("frequency", 0.0)
            
            severity_weights = {"low": 0.2, "medium": 0.5, "high": 0.8, "critical": 1.0}
            score += severity_weights.get(severity, 0.2) * frequency
        
        # User interaction scoring
        elif features.get("type") == "user_interaction":
            engagement = features.get("engagement", 0.0)
            duration = features.get("duration", 0)
            
            # Normalize duration (assuming max 300 seconds)
            duration_score = min(duration / 300.0, 1.0)
            score += (engagement * 0.6 + duration_score * 0.4)
        
        # Resource usage scoring
        elif features.get("type") == "resource_usage":
            cpu = features.get("cpu", 0.0)
            memory = features.get("memory", 0.0)
            
            # Higher resource usage = higher salience
            score += (cpu * 0.6 + memory * 0.4)
        
        # Add some randomness for demonstration
        score += np.random.uniform(-0.1, 0.1)
        
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

class SalienceModel:
    """Alternative interface for salience scoring."""
    
    def __init__(self):
        """Initialize the salience model."""
        self.scorer = SalienceScorer()
    
    def predict(self, features: List[Dict[str, Any]]) -> List[float]:
        """Predict salience scores for features."""
        return self.scorer.score_features(features) 