"""
Drift Detection Module for SeedCore

This module implements a Neural-CUSUM drift detector that:
1. Builds task feature vectors using SentenceTransformer embeddings + runtime metrics
2. Runs a lightweight two-layer MLP to output log-likelihood scores
3. Provides drift scores for OCPSValve integration

The drift detector is designed to run under 50ms for typical feature sizes.
"""

import os
import time
import logging
import numpy as np  # pyright: ignore[reportMissingImports]
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass
import torch  # pyright: ignore[reportMissingImports]
import torch.nn as nn  # pyright: ignore[reportMissingImports]
import torch.nn.functional as F  # pyright: ignore[reportMissingImports]
from sentence_transformers import SentenceTransformer  # pyright: ignore[reportMissingImports]
import asyncio
from concurrent.futures import ThreadPoolExecutor
from sklearn.feature_extraction.text import TfidfVectorizer  # pyright: ignore[reportMissingImports]
import re
import hashlib
import json
from datetime import datetime

logger = logging.getLogger(__name__)

@dataclass
class ModelVersion:
    """Model version information for reproducibility."""
    version: str
    checksum: str
    created_at: str
    sentence_transformer_model: str
    mlp_architecture: Dict[str, Any]
    tfidf_config: Dict[str, Any]

@dataclass
class DriftScore:
    """Drift score result with metadata."""
    score: float
    log_likelihood: float
    confidence: float
    feature_vector: Optional[np.ndarray] = None
    processing_time_ms: float = 0.0
    model_version: str = "1.0.0"
    model_checksum: str = ""
    drift_mode: str = "sentence_transformer"  # "sentence_transformer" or "tfidf"
    accuracy_warning: Optional[str] = None  # Warning about accuracy trade-offs

class LightweightFeaturizer:
    """
    Lightweight TF-IDF-based featurizer for CPU-only environments.
    
    ACCURACY TRADE-OFFS:
    - TF-IDF is significantly faster than SentenceTransformer (5-10ms vs 20-50ms)
    - However, it may UNDER-ESCALATE compared to embeddings due to:
      * Limited semantic understanding (no contextual meaning)
      * Bag-of-words approach loses word order and relationships
      * Fixed vocabulary may miss domain-specific terms
      * No cross-lingual or multilingual capabilities
    
    EXPECTED BEHAVIOR:
    - Lower precision: May miss subtle drift patterns that embeddings would catch
    - Higher recall: Still catches obvious drift patterns based on term frequency
    - Conservative scoring: Tends to produce lower drift scores overall
    - Suitable for: High-throughput scenarios where speed > accuracy
    
    PRODUCTION MONITORING:
    - Monitor drift_mode="tfidf" in logs/metrics to track fallback usage
    - Compare escalation rates between SentenceTransformer and TF-IDF modes
    - Alert if TF-IDF mode usage exceeds expected threshold (e.g., >20%)
    """
    
    def __init__(self, max_features: int = 1000, ngram_range: Tuple[int, int] = (1, 2)):
        self.max_features = max_features
        self.ngram_range = ngram_range
        self.vectorizer = TfidfVectorizer(
            max_features=max_features,
            ngram_range=ngram_range,
            stop_words='english',
            lowercase=True,
            strip_accents='unicode'
        )
        self._fitted = False
    
    def _preprocess_text(self, text: str) -> str:
        """Preprocess text for TF-IDF vectorization."""
        if not text:
            return ""
        
        # Basic cleaning
        text = re.sub(r'[^\w\s]', ' ', text.lower())
        text = re.sub(r'\s+', ' ', text).strip()
        return text
    
    def fit(self, texts: List[str]):
        """Fit the TF-IDF vectorizer on training texts."""
        processed_texts = [self._preprocess_text(text) for text in texts]
        self.vectorizer.fit(processed_texts)
        self._fitted = True
    
    def transform(self, text: str) -> np.ndarray:
        """Transform text to TF-IDF features."""
        if not self._fitted:
            # Use dummy fitting if not fitted
            self.fit([text])
        
        processed_text = self._preprocess_text(text)
        features = self.vectorizer.transform([processed_text]).toarray()
        return features.flatten()
    
    def get_feature_dim(self) -> int:
        """Get the dimension of the feature vector."""
        return self.max_features

class DriftDetectorMLP(nn.Module):
    """Lightweight two-layer MLP for drift detection."""
    
    def __init__(self, input_dim: int = 768, hidden_dim: int = 128, output_dim: int = 1):
        super().__init__()
        self.input_dim = input_dim
        self.hidden_dim = hidden_dim
        self.output_dim = output_dim
        
        # Two-layer MLP with dropout for regularization
        self.layers = nn.Sequential(
            nn.Linear(input_dim, hidden_dim),
            nn.ReLU(),
            nn.Dropout(0.1),
            nn.Linear(hidden_dim, hidden_dim // 2),
            nn.ReLU(),
            nn.Dropout(0.1),
            nn.Linear(hidden_dim // 2, output_dim)
        )
        
        # Initialize weights
        self._init_weights()
    
    def _init_weights(self):
        """Initialize weights using Xavier uniform initialization."""
        for layer in self.layers:
            if isinstance(layer, nn.Linear):
                nn.init.xavier_uniform_(layer.weight)
                nn.init.zeros_(layer.bias)
    
    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """Forward pass through the MLP."""
        return self.layers(x)

class DriftDetector:
    """
    Neural-CUSUM drift detector that combines text embeddings with runtime metrics.
    
    This detector:
    1. Extracts text embeddings using SentenceTransformer
    2. Combines with runtime metrics (latency, memory, etc.)
    3. Runs through a lightweight MLP to produce log-likelihood scores
    4. Returns drift scores suitable for OCPSValve integration
    """
    
    def __init__(
        self,
        model_name: str = "all-MiniLM-L6-v2",
        input_dim: int = 768,
        hidden_dim: int = 128,
        device: str = "cpu",
        max_text_length: int = 512,
        enable_fallback: bool = True
    ):
        self.model_name = model_name
        self.input_dim = input_dim
        self.hidden_dim = hidden_dim
        self.device = device
        self.max_text_length = max_text_length
        self.enable_fallback = enable_fallback
        
        # Initialize components
        self._sentence_transformer = None
        self._mlp = None
        self._fallback_featurizer = None
        self._thread_pool = ThreadPoolExecutor(max_workers=2)
        
        # Performance tracking
        self._total_requests = 0
        self._total_time_ms = 0.0
        self._model_loaded = False
        self._warmed_up = False
        
        # Model versioning
        self._model_version = None
        self._model_checksum = None
        
        # Fallback configuration
        if self.enable_fallback:
            self._fallback_featurizer = LightweightFeaturizer(max_features=1000)
            self._fallback_input_dim = self._fallback_featurizer.get_feature_dim()
        
        logger.info(f"DriftDetector initialized with model={model_name}, device={device}, fallback={enable_fallback}")
    
    async def _load_models(self):
        """Load the sentence transformer and MLP models asynchronously."""
        if self._model_loaded:
            return
        
        try:
            # Load sentence transformer in thread pool to avoid blocking
            def _load_sentence_transformer():
                return SentenceTransformer(self.model_name, device=self.device)
            
            self._sentence_transformer = await asyncio.get_event_loop().run_in_executor(
                self._thread_pool, _load_sentence_transformer
            )
            
            # Initialize MLP with appropriate input dimension
            if self._sentence_transformer:
                mlp_input_dim = self.input_dim
            elif self.enable_fallback and self._fallback_featurizer:
                mlp_input_dim = self._fallback_input_dim + len(self._extract_runtime_features({}))
            else:
                mlp_input_dim = self.input_dim
                
            self._mlp = DriftDetectorMLP(
                input_dim=mlp_input_dim,
                hidden_dim=self.hidden_dim,
                output_dim=1
            ).to(self.device)
            
            # Load pre-trained weights if available
            await self._load_pretrained_weights()
            
            self._model_loaded = True
            
            # Generate model version and checksum for reproducibility
            self._model_version, self._model_checksum = self._generate_model_version()
            
            logger.info("✅ DriftDetector models loaded successfully")
            logger.info(f"📋 Model version: {self._model_version}")
            logger.info(f"🔐 Model checksum: {self._model_checksum}")
            
        except Exception as e:
            logger.error(f"❌ Failed to load DriftDetector models: {e}")
            raise
    
    async def _load_pretrained_weights(self):
        """Load pre-trained MLP weights if available."""
        try:
            # Try to load from a standard location
            weights_path = os.path.join(
                os.getenv("SEEDCORE_MODEL_PATH", "/app/models"),
                "drift_detector_mlp.pth"
            )
            
            if os.path.exists(weights_path):
                state_dict = torch.load(weights_path, map_location=self.device)
                self._mlp.load_state_dict(state_dict)
                logger.info(f"✅ Loaded pre-trained MLP weights from {weights_path}")
            else:
                logger.info("No pre-trained weights found, using random initialization")
                
        except Exception as e:
            logger.warning(f"Failed to load pre-trained weights: {e}")
    
    def _generate_model_version(self) -> Tuple[str, str]:
        """
        Generate model version and checksum for reproducibility.
        
        This ensures that drift scores are reproducible across deployments
        by tracking the exact model configuration and weights.
        """
        try:
            # Collect model configuration
            config = {
                "sentence_transformer_model": self.model_name,
                "mlp_architecture": {
                    "input_dim": self.input_dim,
                    "hidden_dim": self.hidden_dim,
                    "device": self.device
                },
                "tfidf_config": {
                    "max_features": self._fallback_featurizer.max_features if self._fallback_featurizer else None,
                    "ngram_range": self._fallback_featurizer.ngram_range if self._fallback_featurizer else None
                },
                "timestamp": datetime.now().isoformat()
            }
            
            # Generate checksum from model weights and config
            checksum_data = {
                "config": config,
                "mlp_weights": self._get_mlp_weights_hash(),
                "sentence_transformer_hash": self._get_sentence_transformer_hash()
            }
            
            # Create deterministic checksum
            checksum_str = json.dumps(checksum_data, sort_keys=True)
            checksum = hashlib.sha256(checksum_str.encode()).hexdigest()[:16]
            
            # Generate version string
            version = f"drift-detector-{checksum}"
            
            return version, checksum
            
        except Exception as e:
            logger.warning(f"Failed to generate model version: {e}")
            return "drift-detector-unknown", "unknown"
    
    def _get_mlp_weights_hash(self) -> str:
        """Get hash of MLP weights for reproducibility."""
        if not self._mlp:
            return "no_mlp"
        
        try:
            # Get state dict and create hash
            state_dict = self._mlp.state_dict()
            weights_str = str(sorted(state_dict.items()))
            return hashlib.sha256(weights_str.encode()).hexdigest()[:16]
        except Exception:
            return "mlp_error"
    
    def _get_sentence_transformer_hash(self) -> str:
        """Get hash of SentenceTransformer model for reproducibility."""
        if not self._sentence_transformer:
            return "no_st"
        
        try:
            # Get model config and create hash
            config = getattr(self._sentence_transformer, 'config', {})
            config_str = str(sorted(config.items())) if config else "no_config"
            return hashlib.sha256(config_str.encode()).hexdigest()[:16]
        except Exception:
            return "st_error"
    
    async def warmup(self, sample_texts: Optional[List[str]] = None):
        """
        Warm up the drift detector to avoid cold start latency.
        
        This method:
        1. Loads models if not already loaded
        2. Performs a test computation to warm up the system
        3. Fits fallback featurizer if needed
        """
        if self._warmed_up:
            return
        
        try:
            # Load models first
            await self._load_models()
            
            # Prepare sample texts for warmup
            if sample_texts is None:
                sample_texts = [
                    "Test task for warmup",
                    "General query about system status",
                    "Anomaly detection task with high priority",
                    "Execute complex workflow with multiple steps"
                ]
            
            # Fit fallback featurizer if using fallback mode
            if self.enable_fallback and self._fallback_featurizer and not self._sentence_transformer:
                self._fallback_featurizer.fit(sample_texts)
                logger.info("Fallback featurizer fitted with sample texts")
            
            # Perform warmup computation
            warmup_task = {
                "id": "warmup_task",
                "type": "general_query",
                "description": sample_texts[0],
                "priority": 5,
                "complexity": 0.5,
                "latency_ms": 100.0,
                "memory_usage": 0.5,
                "cpu_usage": 0.5,
                "history_ids": []
            }
            
            # Run warmup computation
            await self.compute_drift_score(warmup_task, sample_texts[0])
            
            self._warmed_up = True
            logger.info("✅ DriftDetector warmup completed successfully")
            
        except Exception as e:
            logger.warning(f"DriftDetector warmup failed: {e}")
            # Don't raise - warmup is best effort
    
    def _extract_text_features(self, text: str) -> Tuple[np.ndarray, str, Optional[str]]:
        """
        Extract text embeddings using SentenceTransformer or fallback featurizer.
        
        Returns:
            Tuple of (features, drift_mode, accuracy_warning)
        """
        logger.debug(f"Extracting text features for: '{text[:50]}...' (len={len(text)})")
        logger.debug(f"SentenceTransformer available: {self._sentence_transformer is not None}")
        logger.debug(f"Fallback featurizer available: {self._fallback_featurizer is not None}")
        
        if self._sentence_transformer:
            # Use SentenceTransformer if available
            if len(text) > self.max_text_length:
                text = text[:self.max_text_length]
            logger.debug(f"Using SentenceTransformer for text: '{text[:50]}...'")
            embeddings = self._sentence_transformer.encode([text], convert_to_tensor=True)
            return embeddings.cpu().numpy().flatten(), "sentence_transformer", None
        elif self.enable_fallback and self._fallback_featurizer:
            # Use lightweight TF-IDF featurizer as fallback
            logger.debug(f"Using TF-IDF fallback for text: '{text[:50]}...'")
            warning = ("Using TF-IDF fallback mode - may under-escalate compared to embeddings. "
                      "Monitor drift_mode='tfidf' in metrics and consider GPU availability.")
            return self._fallback_featurizer.transform(text), "tfidf", warning
        else:
            raise RuntimeError("No text featurizer available")
    
    def _extract_runtime_features(self, task: Dict[str, Any]) -> np.ndarray:
        """Extract runtime metrics from task."""
        features = []
        
        # Task metadata
        features.append(float(task.get("priority", 5)) / 10.0)  # Normalize to [0,1]
        features.append(float(task.get("complexity", 0.5)))     # Already [0,1]
        
        # Runtime metrics
        features.append(float(task.get("latency_ms", 0)) / 1000.0)  # Normalize to seconds
        features.append(float(task.get("memory_usage", 0.5)))       # Already [0,1]
        features.append(float(task.get("cpu_usage", 0.5)))          # Already [0,1]
        
        # Task type encoding (simple one-hot)
        task_type = str(task.get("type", "unknown")).lower()
        type_features = [0.0] * 5  # Support up to 5 task types
        type_mapping = {
            "general_query": 0, "anomaly_triage": 1, "execute": 2, 
            "health_check": 3, "unknown": 4
        }
        type_idx = type_mapping.get(task_type, 4)
        type_features[type_idx] = 1.0
        features.extend(type_features)
        
        # History features
        history_ids = task.get("history_ids", [])
        features.append(min(len(history_ids) / 10.0, 1.0))  # Normalize history length
        
        return np.array(features, dtype=np.float32)
    
    def _combine_features(self, text_features: np.ndarray, runtime_features: np.ndarray) -> np.ndarray:
        """Combine text and runtime features into a single feature vector."""
        logger.debug(f"[DriftDetector] Combining features - text: {text_features.shape}, runtime: {runtime_features.shape}")
        
        # Determine target dimension based on current featurizer
        if self._sentence_transformer:
            target_dim = self.input_dim
        elif self.enable_fallback and self._fallback_featurizer:
            target_dim = self._fallback_input_dim + len(runtime_features)
        else:
            target_dim = self.input_dim
        
        logger.debug(f"[DriftDetector] Target dimension: {target_dim}")
        
        # Pad or truncate text features to fit with runtime features
        available_text_dim = target_dim - len(runtime_features)
        logger.debug(f"[DriftDetector] Available text dimension: {available_text_dim}")
        
        if len(text_features) > available_text_dim:
            text_features = text_features[:available_text_dim]
            logger.debug(f"[DriftDetector] Truncated text features to: {text_features.shape}")
        elif len(text_features) < available_text_dim:
            padding = np.zeros(available_text_dim - len(text_features))
            text_features = np.concatenate([text_features, padding])
            logger.debug(f"[DriftDetector] Padded text features to: {text_features.shape}")
        
        # Combine features
        combined = np.concatenate([text_features, runtime_features])
        logger.debug(f"[DriftDetector] Final combined features shape: {combined.shape}")
        
        # Ensure correct dimension
        if len(combined) != target_dim:
            if len(combined) > target_dim:
                combined = combined[:target_dim]
            else:
                padding = np.zeros(target_dim - len(combined))
                combined = np.concatenate([combined, padding])
        
        return combined.astype(np.float32)
    
    def _compute_log_likelihood(self, features: np.ndarray) -> float:
        """Compute log-likelihood using the MLP."""
        if not self._mlp:
            raise RuntimeError("MLP not loaded")
        
        # Convert to tensor
        features_tensor = torch.from_numpy(features).unsqueeze(0).to(self.device)
        
        # Forward pass
        with torch.no_grad():
            logits = self._mlp(features_tensor)
            # Convert to log-likelihood (log probability)
            log_likelihood = F.logsigmoid(logits).item()
        
        return log_likelihood
    
    async def compute_drift_score(
        self, 
        task: Dict[str, Any], 
        text: Optional[str] = None
    ) -> DriftScore:
        """
        Compute drift score for a task.
        
        Args:
            task: Task dictionary with metadata and runtime metrics
            text: Optional text description to embed
            
        Returns:
            DriftScore object with score, log-likelihood, and metadata
        """
        start_time = time.time()
        
        # Debug logging to see what we're receiving
        logger.info(f"[DriftDetector] Received task: {task}")
        logger.info(f"[DriftDetector] Received text: {text}")
        
        try:
            # Ensure models are loaded
            await self._load_models()
            
            # Extract text features if text provided
            if text:
                text_features, drift_mode, accuracy_warning = self._extract_text_features(text)
            else:
                # Use task description or type as text
                task_text = task.get("description", str(task.get("type", "unknown")))
                text_features, drift_mode, accuracy_warning = self._extract_text_features(task_text)
            
            logger.debug(f"[DriftDetector] Text features shape: {text_features.shape}, mode: {drift_mode}")
            
            # Extract runtime features
            runtime_features = self._extract_runtime_features(task)
            logger.debug(f"[DriftDetector] Runtime features shape: {runtime_features.shape}")
            
            # Combine features
            combined_features = self._combine_features(text_features, runtime_features)
            logger.debug(f"[DriftDetector] Combined features shape: {combined_features.shape}")
            
            # Compute log-likelihood
            logger.debug(f"[DriftDetector] MLP input dimension: {self._mlp.input_dim if self._mlp else 'None'}")
            logger.debug(f"[DriftDetector] Combined features dimension: {combined_features.shape[0]}")
            log_likelihood = self._compute_log_likelihood(combined_features)
            
            # Convert log-likelihood to drift score (higher = more drift)
            # Use negative log-likelihood as drift score
            drift_score = -log_likelihood
            
            # Compute confidence based on feature quality
            confidence = min(1.0, max(0.1, 1.0 - abs(log_likelihood)))
            
            processing_time = (time.time() - start_time) * 1000
            
            # Update performance tracking
            self._total_requests += 1
            self._total_time_ms += processing_time
            
            return DriftScore(
                score=drift_score,
                log_likelihood=log_likelihood,
                confidence=confidence,
                feature_vector=combined_features,
                processing_time_ms=processing_time,
                model_version=self._model_version or "1.0.0",
                model_checksum=self._model_checksum or "",
                drift_mode=drift_mode,
                accuracy_warning=accuracy_warning
            )
            
        except Exception as e:
            import traceback
            logger.error(f"[DriftDetector] Exception in compute_drift_score: {e}")
            logger.error(f"[DriftDetector] Full traceback:\n{traceback.format_exc()}")
            
            # Return fallback score
            processing_time = (time.time() - start_time) * 1000
            return DriftScore(
                score=0.5,  # Neutral drift score
                log_likelihood=-0.5,
                confidence=0.1,
                processing_time_ms=processing_time,
                model_version=self._model_version or "1.0.0",
                model_checksum=self._model_checksum or "",
                drift_mode="fallback",
                accuracy_warning="Drift detection failed - using neutral fallback score"
            )
    
    def get_performance_stats(self) -> Dict[str, Any]:
        """Get performance statistics."""
        avg_time = self._total_time_ms / max(1, self._total_requests)
        return {
            "total_requests": self._total_requests,
            "total_time_ms": self._total_time_ms,
            "average_time_ms": avg_time,
            "model_loaded": self._model_loaded,
            "model_name": self.model_name,
            "device": self.device
        }
    
    async def close(self):
        """Clean up resources."""
        if self._thread_pool:
            self._thread_pool.shutdown(wait=True)

# Global drift detector instance
_drift_detector: Optional[DriftDetector] = None

def get_drift_detector() -> DriftDetector:
    """Get the global drift detector instance."""
    global _drift_detector
    if _drift_detector is None:
        device = "cuda" if torch.cuda.is_available() else "cpu"
        _drift_detector = DriftDetector(device=device)
    return _drift_detector

async def compute_drift_score(task: Dict[str, Any], text: Optional[str] = None) -> DriftScore:
    """Convenience function to compute drift score."""
    detector = get_drift_detector()
    return await detector.compute_drift_score(task, text)
