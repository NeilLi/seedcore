#!/usr/bin/env python3
"""
ML Service Client for SeedCore

This client provides a clean interface to the deployed ML service
with all drift detection, salience scoring, and XGBoost endpoints.
"""

import logging
from typing import Dict, Any, List
from .base_client import BaseServiceClient, CircuitBreaker, RetryConfig

logger = logging.getLogger(__name__)

class MLServiceClient(BaseServiceClient):
    """
    Client for the deployed ML service that handles:
    - LLM: chat/completions, embeddings, rerank
    - Drift detection and scoring
    - Salience scoring
    - Anomaly detection
    - XGBoost model operations
    - Scaling predictions
    - Intent compilation: deterministic natural-language → function call translation
    """
    
    def __init__(self, 
                 base_url: str = None, 
                 timeout: float = 10.0,
                 warmup_timeout: float = 30.0):
        # Use centralized gateway discovery
        if base_url is None:
            try:
                from seedcore.utils.ray_utils import ML
                base_url = ML
            except Exception:
                base_url = "http://127.0.0.1:8000/ml"
        
        # Configure circuit breaker for ML service
        circuit_breaker = CircuitBreaker(
            failure_threshold=5,
            recovery_timeout=30.0,
            expected_exception=(Exception,)  # Catch all exceptions
        )
        
        # Configure retry for ML service
        retry_config = RetryConfig(
            max_attempts=2,
            base_delay=1.0,
            max_delay=5.0
        )
        
        super().__init__(
            service_name="ml_service",
            base_url=base_url,
            timeout=timeout,
            circuit_breaker=circuit_breaker,
            retry_config=retry_config
        )
        
        self.warmup_timeout = warmup_timeout
    
    # Drift Detection Methods
    async def compute_drift_score(self, task: Dict[str, Any], text: str = None) -> Dict[str, Any]:
        """
        Compute drift score for a task using the Neural-CUSUM drift detector.
        
        Args:
            task: Task dictionary with metadata and runtime metrics
            text: Optional text description to embed
            
        Returns:
            Drift score result with metadata
        """
        request_data = {
            "task": task,
            "text": text
        }
        
        return await self.post("/drift/score", json=request_data)
    
    async def warmup_drift_detector(self, sample_texts: List[str] = None) -> Dict[str, Any]:
        """
        Warm up the drift detector to avoid cold start latency.
        
        Args:
            sample_texts: Optional sample texts for warmup
            
        Returns:
            Warmup result with performance stats
        """
        request_data = {}
        if sample_texts:
            request_data["sample_texts"] = sample_texts
        
        # Use longer timeout for warmup
        original_timeout = self.timeout
        self.timeout = self.warmup_timeout
        
        try:
            return await self.post("/drift/warmup", json=request_data)
        finally:
            self.timeout = original_timeout
    
    # Salience Scoring Methods
    async def compute_salience_score(self, text: str, context: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Compute salience score for text.
        
        Args:
            text: Text to score
            context: Optional context information
            
        Returns:
            Salience score result
        """
        request_data = {
            "text": text,
            "context": context or {}
        }
        
        return await self.post("/score/salience", json=request_data)
    
    # Anomaly Detection Methods
    async def detect_anomaly(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Detect anomalies in data.
        
        Args:
            data: Data to analyze for anomalies
            
        Returns:
            Anomaly detection result
        """
        return await self.post("/detect/anomaly", json=data)
    
    # XGBoost Methods
    async def train_xgboost_model(self, training_data: Dict[str, Any]) -> Dict[str, Any]:
        """Train an XGBoost model."""
        return await self.post("/xgboost/train", json=training_data)
    
    async def predict_xgboost(self, features: List[List[float]]) -> Dict[str, Any]:
        """Make predictions using XGBoost model."""
        request_data = {"features": features}
        return await self.post("/xgboost/predict", json=request_data)
    
    async def batch_predict_xgboost(self, features: List[List[float]]) -> Dict[str, Any]:
        """Make batch predictions using XGBoost model."""
        request_data = {"features": features}
        return await self.post("/xgboost/batch_predict", json=request_data)
    
    async def load_xgboost_model(self, model_path: str) -> Dict[str, Any]:
        """Load an XGBoost model."""
        request_data = {"model_path": model_path}
        return await self.post("/xgboost/load_model", json=request_data)
    
    async def list_xgboost_models(self) -> Dict[str, Any]:
        """List available XGBoost models."""
        return await self.get("/xgboost/list_models")
    
    async def get_xgboost_model_info(self) -> Dict[str, Any]:
        """Get information about the current XGBoost model."""
        return await self.get("/xgboost/model_info")
    
    async def delete_xgboost_model(self, model_name: str) -> Dict[str, Any]:
        """Delete an XGBoost model."""
        request_data = {"model_name": model_name}
        return await self.post("/xgboost/delete_model", json=request_data)
    
    async def tune_xgboost(self, tuning_config: Dict[str, Any]) -> Dict[str, Any]:
        """Tune XGBoost hyperparameters."""
        return await self.post("/xgboost/tune", json=tuning_config)
    
    async def submit_tuning_job(self, job_config: Dict[str, Any]) -> Dict[str, Any]:
        """Submit an async tuning job."""
        return await self.post("/xgboost/tune/submit", json=job_config)
    
    async def get_tuning_status(self, job_id: str) -> Dict[str, Any]:
        """Get status of a tuning job."""
        return await self.get(f"/xgboost/tune/status/{job_id}")
    
    async def list_tuning_jobs(self) -> Dict[str, Any]:
        """List all tuning jobs."""
        return await self.get("/xgboost/tune/jobs")
    
    async def refresh_xgboost_model(self) -> Dict[str, Any]:
        """Refresh the current XGBoost model."""
        return await self.post("/xgboost/refresh_model")
    
    # Scaling Prediction Methods
    async def predict_scaling(self, metrics: Dict[str, Any]) -> Dict[str, Any]:
        """
        Predict scaling requirements based on metrics.
        
        Args:
            metrics: System metrics for scaling prediction
            
        Returns:
            Scaling prediction result
        """
        return await self.post("/predict/scaling", json=metrics)

    async def predict_all(self, metrics: Dict[str, Any]) -> Dict[str, Any]:
        """
        Unified ML inference (roles, drift, anomaly, scaling) from StateService metrics.
        
        Args:
            metrics: Either the raw /state/system-metrics response or the nested metrics dict.
        """
        payload = metrics or {}
        return await self.post("/integrations/predict_all", json=payload)
    
    async def get_adaptive_params(self) -> Dict[str, Any]:
        """Get adaptive parameters from MLService."""
        return await self.get("/integrations/adaptive_params")

    async def update_adaptive_params(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Sends feedback to ML Service to adjust dynamic parameters (e.g. temperature).
        """
        url = f"{self.base_url}/integrations/adaptive_params"
        async with self._session.post(url, json=params) as resp:
            resp.raise_for_status()
            return await resp.json()
    
    # --- LLM Endpoints ---
    async def chat(self, model: str, messages: List[Dict[str, str]], **params) -> Dict[str, Any]:
        """
        Chat/completions via MLService.
        
        Args:
            model: Model name to use for chat
            messages: List of message dictionaries with "role" and "content" keys
            **params: Additional parameters for the chat request
            
        Returns:
            Chat completion response
        """
        payload = {"model": model, "messages": messages, **params}
        return await self.post("/chat", json=payload)

    async def embeddings(self, model: str, inputs: List[str] | str, **params) -> Dict[str, Any]:
        """
        Embeddings via MLService.
        
        Args:
            model: Model name to use for embeddings
            inputs: Single string or list of strings to embed
            **params: Additional parameters for the embeddings request
            
        Returns:
            Embeddings response
        """
        payload = {"model": model, "input": inputs, **params}
        return await self.post("/embeddings", json=payload)

    async def rerank(self, model: str, query: str, documents: List[str], top_k: int = 10, **params) -> Dict[str, Any]:
        """
        Rerank via MLService.
        
        Args:
            model: Model name to use for reranking
            query: Query string
            documents: List of documents to rerank
            top_k: Number of top results to return
            **params: Additional parameters for the rerank request
            
        Returns:
            Rerank response
        """
        payload = {"model": model, "query": query, "documents": documents, "top_k": top_k, **params}
        return await self.post("/rerank", json=payload)

    async def list_models(self) -> Dict[str, Any]:
        """
        List available models from MLService.
        
        Returns:
            List of available models
        """
        return await self.get("/models")

    # --- Intent Compilation Endpoints ---
    async def compile_intent(
        self,
        text: str,
        context: Dict[str, Any] = None,
        **params
    ) -> Dict[str, Any]:
        """
        Compile natural language text into a structured function call.
        
        Uses FunctionGemma as a deterministic intent compiler to convert
        user text into validated function calls without executing them.
        
        Args:
            text: Natural language input (e.g., "turn on the bedroom light")
            context: Optional context (domain, vendor, room_map, etc.)
            **params: Additional parameters for the intent compilation request
            
        Returns:
            Intent compilation result with function name, arguments, and confidence
        """
        payload = {
            "text": text,
            "context": context or {},
            **params
        }
        return await self.post("/intent/compile", json=payload)

    async def get_intent_schema(
        self,
        function_name: str = None,
        domain: str = None
    ) -> Dict[str, Any]:
        """
        Get function schema(s) for intent compilation.
        
        Args:
            function_name: Get schema for specific function (optional)
            domain: Filter schemas by domain (e.g., "device", "energy") (optional)
            
        Returns:
            Schema(s) response - single schema if function_name provided,
            otherwise list of schemas filtered by domain if provided
        """
        params = {}
        if function_name:
            params["function_name"] = function_name
        if domain:
            params["domain"] = domain
        
        query_string = "&".join([f"{k}={v}" for k, v in params.items()])
        url = "/intent/schema"
        if query_string:
            url += f"?{query_string}"
        
        return await self.get(url)

    async def validate_intent(
        self,
        function: str,
        arguments: Dict[str, Any],
        **params
    ) -> Dict[str, Any]:
        """
        Validate a generated function call against its schema.
        
        Args:
            function: Function name to validate
            arguments: Function arguments to validate
            **params: Additional parameters for validation
            
        Returns:
            Validation result with valid flag and any errors
        """
        payload = {
            "function": function,
            "arguments": arguments,
            **params
        }
        return await self.post("/intent/validate", json=payload)

    async def health(self) -> Dict[str, Any]:
        """
        Check MLService health status.
        
        Returns:
            Health status response
        """
        return await self.get("/health")
    
    # Service Information
    async def get_service_info(self) -> Dict[str, Any]:
        """Get ML service information and available endpoints."""
        return await self.get("/")
    
    async def is_healthy(self) -> bool:
        """Check if the ML service is healthy."""
        try:
            health = await self.health_check()
            return health.get("status") == "healthy"
        except Exception:
            return False
