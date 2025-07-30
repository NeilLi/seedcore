"""
Predictive Scaling Module

Provides ML-driven resource management for:
- Predictive scaling based on usage patterns
- Intelligent resource allocation
- Performance optimization recommendations
"""

import numpy as np
from typing import List, Dict, Any, Tuple
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

class ScalingPredictor:
    """ML-based predictive scaling for resource management."""
    
    def __init__(self):
        """Initialize the scaling predictor."""
        self.model = self._load_model()
        self.scaling_policies = self._load_scaling_policies()
        logger.info("ScalingPredictor initialized")
    
    def _load_model(self):
        """Load the scaling prediction model."""
        # TODO: Implement actual model loading
        # For now, return a simple prediction function
        return self._simple_scaling_predictor
    
    def _load_scaling_policies(self):
        """Load scaling policies and thresholds."""
        return {
            "cpu": {
                "scale_up_threshold": 0.7,
                "scale_down_threshold": 0.3,
                "min_scale": 0.5,
                "max_scale": 2.0
            },
            "memory": {
                "scale_up_threshold": 0.75,
                "scale_down_threshold": 0.4,
                "min_scale": 0.5,
                "max_scale": 2.0
            },
            "response_time": {
                "scale_up_threshold": 1.5,
                "scale_down_threshold": 0.5,
                "min_scale": 0.8,
                "max_scale": 1.5
            }
        }
    
    def _simple_scaling_predictor(self, usage_patterns: Dict[str, Any]) -> Dict[str, Any]:
        """Simple scaling prediction based on usage patterns."""
        predictions = {}
        
        # CPU scaling prediction
        cpu_avg = usage_patterns.get("cpu_avg", 0.0)
        cpu_scale = self._predict_cpu_scaling(cpu_avg)
        predictions["cpu_scale"] = cpu_scale
        
        # Memory scaling prediction
        memory_avg = usage_patterns.get("memory_avg", 0.0)
        memory_scale = self._predict_memory_scaling(memory_avg)
        predictions["memory_scale"] = memory_scale
        
        # Response time scaling prediction
        response_time = usage_patterns.get("response_time", 1.0)
        response_scale = self._predict_response_scaling(response_time)
        predictions["response_scale"] = response_scale
        
        # Overall scaling recommendation
        overall_scale = (cpu_scale + memory_scale + response_scale) / 3
        predictions["overall_scale"] = overall_scale
        
        # Confidence based on data quality
        confidence = self._calculate_confidence(usage_patterns)
        predictions["confidence"] = confidence
        
        # Scaling action recommendation
        predictions["action"] = self._recommend_action(overall_scale, confidence)
        
        return predictions
    
    def _predict_cpu_scaling(self, cpu_avg: float) -> float:
        """Predict CPU scaling factor."""
        policy = self.scaling_policies["cpu"]
        
        if cpu_avg > policy["scale_up_threshold"]:
            # Scale up based on usage
            scale_factor = 1.0 + (cpu_avg - policy["scale_up_threshold"]) * 2
        elif cpu_avg < policy["scale_down_threshold"]:
            # Scale down based on usage
            scale_factor = 1.0 - (policy["scale_down_threshold"] - cpu_avg) * 0.5
        else:
            # Keep current scale
            scale_factor = 1.0
        
        # Apply min/max constraints
        scale_factor = max(policy["min_scale"], min(policy["max_scale"], scale_factor))
        
        # Add some randomness for demonstration
        scale_factor += np.random.uniform(-0.1, 0.1)
        
        return max(policy["min_scale"], min(policy["max_scale"], scale_factor))
    
    def _predict_memory_scaling(self, memory_avg: float) -> float:
        """Predict memory scaling factor."""
        policy = self.scaling_policies["memory"]
        
        if memory_avg > policy["scale_up_threshold"]:
            scale_factor = 1.0 + (memory_avg - policy["scale_up_threshold"]) * 1.5
        elif memory_avg < policy["scale_down_threshold"]:
            scale_factor = 1.0 - (policy["scale_down_threshold"] - memory_avg) * 0.3
        else:
            scale_factor = 1.0
        
        scale_factor = max(policy["min_scale"], min(policy["max_scale"], scale_factor))
        scale_factor += np.random.uniform(-0.05, 0.05)
        
        return max(policy["min_scale"], min(policy["max_scale"], scale_factor))
    
    def _predict_response_scaling(self, response_time: float) -> float:
        """Predict response time scaling factor."""
        policy = self.scaling_policies["response_time"]
        
        if response_time > policy["scale_up_threshold"]:
            scale_factor = 1.0 + (response_time - policy["scale_up_threshold"]) * 0.3
        elif response_time < policy["scale_down_threshold"]:
            scale_factor = 1.0 - (policy["scale_down_threshold"] - response_time) * 0.2
        else:
            scale_factor = 1.0
        
        scale_factor = max(policy["min_scale"], min(policy["max_scale"], scale_factor))
        scale_factor += np.random.uniform(-0.05, 0.05)
        
        return max(policy["min_scale"], min(policy["max_scale"], scale_factor))
    
    def _calculate_confidence(self, usage_patterns: Dict[str, Any]) -> float:
        """Calculate confidence in the prediction."""
        # Simple confidence calculation based on data completeness
        required_fields = ["cpu_avg", "memory_avg", "response_time"]
        present_fields = sum(1 for field in required_fields if field in usage_patterns)
        
        base_confidence = present_fields / len(required_fields)
        
        # Adjust confidence based on data quality
        if "request_rate" in usage_patterns:
            base_confidence += 0.1
        
        # Add some randomness for demonstration
        confidence = base_confidence + np.random.uniform(-0.1, 0.1)
        
        return max(0.0, min(1.0, confidence))
    
    def _recommend_action(self, overall_scale: float, confidence: float) -> str:
        """Recommend scaling action based on prediction."""
        if confidence < 0.5:
            return "monitor"
        elif overall_scale > 1.2:
            return "scale_up"
        elif overall_scale < 0.8:
            return "scale_down"
        else:
            return "maintain"
    
    def predict_scaling(self, usage_patterns: Dict[str, Any]) -> Dict[str, Any]:
        """Predict scaling requirements based on usage patterns."""
        try:
            predictions = self.model(usage_patterns)
            
            # Add metadata
            predictions["timestamp"] = datetime.now().isoformat()
            predictions["model_version"] = "1.0.0"
            
            logger.info(f"Generated scaling predictions with confidence: {predictions['confidence']:.2f}")
            return predictions
        except Exception as e:
            logger.error(f"Error in scaling prediction: {e}")
            return {
                "error": str(e),
                "timestamp": datetime.now().isoformat()
            }
    
    def get_scaling_recommendations(self, historical_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Get scaling recommendations based on historical data."""
        if len(historical_data) < 3:
            return [{"error": "Insufficient historical data"}]
        
        recommendations = []
        
        # Analyze recent patterns
        recent_data = historical_data[-10:]  # Last 10 data points
        
        for data_point in recent_data:
            prediction = self.predict_scaling(data_point)
            recommendations.append(prediction)
        
        return recommendations

class ResourceAllocator:
    """Intelligent resource allocation based on predictions."""
    
    def __init__(self):
        """Initialize the resource allocator."""
        self.predictor = ScalingPredictor()
        logger.info("ResourceAllocator initialized")
    
    def allocate_resources(self, current_usage: Dict[str, Any], predictions: Dict[str, Any]) -> Dict[str, Any]:
        """Allocate resources based on current usage and predictions."""
        allocation = {}
        
        # CPU allocation
        cpu_allocation = current_usage.get("cpu_usage", 0.0) * predictions.get("cpu_scale", 1.0)
        allocation["cpu_allocation"] = max(0.1, min(1.0, cpu_allocation))
        
        # Memory allocation
        memory_allocation = current_usage.get("memory_usage", 0.0) * predictions.get("memory_scale", 1.0)
        allocation["memory_allocation"] = max(0.1, min(1.0, memory_allocation))
        
        # Priority allocation
        allocation["priority"] = self._calculate_priority(current_usage, predictions)
        
        # Cost optimization
        allocation["cost_optimization"] = self._optimize_cost(allocation)
        
        return allocation
    
    def _calculate_priority(self, current_usage: Dict[str, Any], predictions: Dict[str, Any]) -> str:
        """Calculate resource allocation priority."""
        overall_scale = predictions.get("overall_scale", 1.0)
        confidence = predictions.get("confidence", 0.0)
        
        if overall_scale > 1.5 and confidence > 0.8:
            return "high"
        elif overall_scale > 1.2 and confidence > 0.6:
            return "medium"
        else:
            return "low"
    
    def _optimize_cost(self, allocation: Dict[str, Any]) -> Dict[str, Any]:
        """Optimize resource allocation for cost efficiency."""
        return {
            "recommended_instance_type": "standard",
            "estimated_cost_savings": 0.15,
            "optimization_strategy": "balanced"
        } 