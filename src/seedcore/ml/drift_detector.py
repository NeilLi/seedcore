"""
Drift Detection Module for SeedCore

This module implements a Neural-CUSUM drift detector that:
1. Builds task feature vectors using SentenceTransformer embeddings + runtime metrics
2. Runs a lightweight two-layer MLP to output in-distribution probabilities
3. Converts those into instantaneous + cumulative (CUSUM-like) drift scores
4. Provides drift scores for OCPSValve integration

The drift detector is designed to run under ~50ms for typical feature sizes.
"""

import os
import time
import logging
import numpy as np  # pyright: ignore[reportMissingImports]
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass
import torch  # pyright: ignore[reportMissingImports]
import torch.nn as nn  # pyright: ignore[reportMissingImports]
from sentence_transformers import SentenceTransformer  # pyright: ignore[reportMissingImports]
import asyncio
from concurrent.futures import ThreadPoolExecutor
from sklearn.feature_extraction.text import TfidfVectorizer  # pyright: ignore[reportMissingImports]
import re
import hashlib
import json
from datetime import datetime
import math

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


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

    score: float  # Final drift score in [0, 1] (higher = more drift)
    log_likelihood: float  # log p_in (log-probability of in-distribution)
    confidence: float  # Confidence in [0.1, 1.0]
    feature_vector: Optional[np.ndarray] = None
    processing_time_ms: float = 0.0
    model_version: str = "1.0.0"
    model_checksum: str = ""
    drift_mode: str = (
        "sentence_transformer"  # "sentence_transformer" | "tfidf" | "fallback"
    )
    accuracy_warning: Optional[str] = None  # Warning about accuracy trade-offs


# ---------------------------------------------------------------------------
# Lightweight TF-IDF Featurizer
# ---------------------------------------------------------------------------


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
    """

    def __init__(self, max_features: int = 1000, ngram_range: Tuple[int, int] = (1, 2)):
        self.max_features = max_features
        self.ngram_range = ngram_range
        self.vectorizer = TfidfVectorizer(
            max_features=max_features,
            ngram_range=ngram_range,
            stop_words="english",
            lowercase=True,
            strip_accents="unicode",
        )
        self._fitted = False

    def _preprocess_text(self, text: str) -> str:
        """Preprocess text for TF-IDF vectorization."""
        if not text:
            return ""

        # Basic cleaning
        text = re.sub(r"[^\w\s]", " ", text.lower())
        text = re.sub(r"\s+", " ", text).strip()
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
            self.fit([text or "dummy"])

        processed_text = self._preprocess_text(text or "")
        features = self.vectorizer.transform([processed_text]).toarray()
        return features.flatten()

    def get_feature_dim(self) -> int:
        """Get the dimension of the feature vector."""
        return self.max_features


# ---------------------------------------------------------------------------
# MLP
# ---------------------------------------------------------------------------


class DriftDetectorMLP(nn.Module):
    """Lightweight two-layer MLP for drift detection."""

    def __init__(self, input_dim: int, hidden_dim: int = 128, output_dim: int = 1):
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
            nn.Linear(hidden_dim // 2, output_dim),
        )

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


# ---------------------------------------------------------------------------
# Neural-CUSUM Drift Detector
# ---------------------------------------------------------------------------


class DriftDetector:
    """
    Neural-CUSUM drift detector that combines text embeddings with runtime metrics.

    This detector:
    1. Extracts text embeddings using SentenceTransformer (or TF-IDF fallback)
    2. Combines with runtime metrics (latency, memory, etc.)
    3. Runs through a lightweight MLP to produce in-distribution probabilities
    4. Converts those into drift scores with a CUSUM-like cumulative signal
    5. Returns drift scores suitable for OCPSValve integration
    """

    def __init__(
        self,
        model_name: str = "all-MiniLM-L6-v2",
        hidden_dim: int = 128,
        device: str = "cpu",
        max_text_length: int = 512,
        enable_fallback: bool = True,
        cusum_decay: float = 0.9,
        cusum_baseline: float = 0.5,
    ):
        self.model_name = model_name
        self.hidden_dim = hidden_dim
        self.device = device
        self.max_text_length = max_text_length
        self.enable_fallback = enable_fallback

        # Components
        self._sentence_transformer: Optional[SentenceTransformer] = None
        self._mlp: Optional[DriftDetectorMLP] = None
        self._fallback_featurizer: Optional[LightweightFeaturizer] = None
        self._thread_pool = ThreadPoolExecutor(max_workers=2)

        # Dimensions (determined at load time)
        self._text_dim: Optional[int] = None  # unified text feature dimension
        self._runtime_dim: Optional[int] = None  # runtime feature dimension
        self._combined_dim: Optional[int] = None  # input dim for MLP

        # Fallback
        if self.enable_fallback:
            self._fallback_featurizer = LightweightFeaturizer(max_features=1000)

        # Performance tracking
        self._total_requests = 0
        self._total_time_ms = 0.0
        self._model_loaded = False
        self._warmed_up = False

        # Model versioning
        self._model_version: Optional[str] = None
        self._model_checksum: Optional[str] = None

        # Neural-CUSUM state
        self._cusum_state: float = 0.0
        self._cusum_decay: float = cusum_decay
        self._cusum_baseline: float = cusum_baseline
        self._cusum_updates: int = 0

        logger.info(
            f"DriftDetector initialized with "
            f"model={model_name}, device={device}, fallback={enable_fallback}"
        )

    # ------------------------------------------------------------------
    # Model loading & versioning
    # ------------------------------------------------------------------

    async def _load_models(self):
        """Load the sentence transformer and MLP models asynchronously."""
        if self._model_loaded:
            return

        try:
            # Load sentence transformer (non-blocking)
            def _load_sentence_transformer():
                return SentenceTransformer(self.model_name, device=self.device)

            try:
                self._sentence_transformer = (
                    await asyncio.get_event_loop().run_in_executor(
                        self._thread_pool, _load_sentence_transformer
                    )
                )
                logger.info("✅ SentenceTransformer loaded successfully")
            except Exception as e:
                logger.warning(
                    f"❌ Failed to load SentenceTransformer '{self.model_name}': {e}. "
                    f"Falling back to TF-IDF if enabled."
                )
                self._sentence_transformer = None

            # Determine runtime feature dimension
            dummy_runtime = self._extract_runtime_features({})
            self._runtime_dim = int(dummy_runtime.shape[0])

            # Determine text feature dimension(s)
            st_dim = None
            if self._sentence_transformer is not None:
                # Dimension probe (only once)
                probe_text = "seedcore drift detector dimension probe"
                emb = self._sentence_transformer.encode(
                    [probe_text], convert_to_tensor=True, show_progress_bar=False
                )
                st_dim = int(emb.shape[-1])
                logger.info(f"SentenceTransformer text dim = {st_dim}")

            tfidf_dim = None
            if self.enable_fallback and self._fallback_featurizer is not None:
                tfidf_dim = self._fallback_featurizer.get_feature_dim()
                logger.info(f"TF-IDF fallback text dim = {tfidf_dim}")

            # Unified text dimension: single MLP that works for both modes
            candidate_dims = [d for d in (st_dim, tfidf_dim) if d is not None]
            if not candidate_dims:
                raise RuntimeError(
                    "No text featurizer (SentenceTransformer or TF-IDF) available"
                )

            self._text_dim = max(candidate_dims)
            self._combined_dim = self._text_dim + self._runtime_dim

            logger.info(
                f"DriftDetector feature dimensions: text_dim={self._text_dim}, "
                f"runtime_dim={self._runtime_dim}, combined_dim={self._combined_dim}"
            )

            # Initialize MLP
            self._mlp = DriftDetectorMLP(
                input_dim=self._combined_dim,
                hidden_dim=self.hidden_dim,
                output_dim=1,
            ).to(self.device)

            # Load pre-trained weights if available
            await self._load_pretrained_weights()

            # Versioning
            self._model_version, self._model_checksum = self._generate_model_version()

            self._model_loaded = True
            logger.info("✅ DriftDetector models loaded successfully")
            logger.info(f"📋 Model version: {self._model_version}")
            logger.info(f"🔐 Model checksum: {self._model_checksum}")

        except Exception as e:
            logger.error(f"❌ Failed to load DriftDetector models: {e}")
            raise

    async def _load_pretrained_weights(self):
        """Load pre-trained MLP weights if available."""
        if self._mlp is None:
            return

        try:
            weights_path = os.path.join(
                os.getenv("SEEDCORE_MODEL_PATH", "/app/models"),
                "drift_detector_mlp.pth",
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
        """
        try:
            config = {
                "sentence_transformer_model": self.model_name,
                "mlp_architecture": {
                    "hidden_dim": self.hidden_dim,
                    "device": self.device,
                    "combined_dim": self._combined_dim,
                    "text_dim": self._text_dim,
                    "runtime_dim": self._runtime_dim,
                },
                "tfidf_config": {
                    "max_features": (
                        self._fallback_featurizer.max_features
                        if self._fallback_featurizer
                        else None
                    ),
                    "ngram_range": (
                        self._fallback_featurizer.ngram_range
                        if self._fallback_featurizer
                        else None
                    ),
                },
                "timestamp": datetime.now().isoformat(),
            }

            checksum_data = {
                "config": config,
                "mlp_weights": self._get_mlp_weights_hash(),
                "sentence_transformer_hash": self._get_sentence_transformer_hash(),
            }

            checksum_str = json.dumps(checksum_data, sort_keys=True)
            checksum = hashlib.sha256(checksum_str.encode()).hexdigest()[:16]
            version = f"drift-detector-{checksum}"
            return version, checksum

        except Exception as e:
            logger.warning(f"Failed to generate model version: {e}")
            return "drift-detector-unknown", "unknown"

    def _get_mlp_weights_hash(self) -> str:
        if not self._mlp:
            return "no_mlp"
        try:
            state_dict = self._mlp.state_dict()
            weights_str = str(sorted(state_dict.items()))
            return hashlib.sha256(weights_str.encode()).hexdigest()[:16]
        except Exception:
            return "mlp_error"

    def _get_sentence_transformer_hash(self) -> str:
        if not self._sentence_transformer:
            return "no_st"
        try:
            config = getattr(self._sentence_transformer, "config", {})
            config_str = str(sorted(config.items())) if config else "no_config"
            return hashlib.sha256(config_str.encode()).hexdigest()[:16]
        except Exception:
            return "st_error"

    # ------------------------------------------------------------------
    # Warmup
    # ------------------------------------------------------------------

    async def warmup(self, sample_texts: Optional[List[str]] = None):
        """
        Warm up the drift detector to avoid cold start latency.
        """
        if self._warmed_up:
            return

        try:
            await self._load_models()

            if sample_texts is None:
                sample_texts = [
                    "Test task for warmup",
                    "General query about system status",
                    "Anomaly detection task with high priority",
                    "Execute complex workflow with multiple steps",
                ]

            # Fit fallback featurizer if ST is unavailable
            if (
                self.enable_fallback
                and self._fallback_featurizer
                and self._sentence_transformer is None
            ):
                self._fallback_featurizer.fit(sample_texts)
                logger.info("Fallback TF-IDF featurizer fitted with sample texts")

            warmup_task = {
                "id": "warmup_task",
                "type": "general_query",
                "description": sample_texts[0],
                "priority": 5,
                "complexity": 0.5,
                "latency_ms": 100.0,
                "memory_usage": 0.5,
                "cpu_usage": 0.5,
                "history_ids": [],
            }

            await self.compute_drift_score(warmup_task, sample_texts[0])
            self._warmed_up = True
            logger.info("✅ DriftDetector warmup completed successfully")

        except Exception as e:
            logger.warning(f"DriftDetector warmup failed: {e}")

    # ------------------------------------------------------------------
    # Feature extraction
    # ------------------------------------------------------------------

    def _extract_text_features(
        self, text: str
    ) -> Tuple[np.ndarray, str, Optional[str]]:
        """
        Extract text embeddings using SentenceTransformer or fallback featurizer.

        Returns:
            (features, drift_mode, accuracy_warning)
        """
        text = (text or "").strip()
        if not text:
            text = "empty description"

        if len(text) > self.max_text_length:
            text = text[: self.max_text_length]

        logger.debug(
            f"Extracting text features for: '{text[:50]}...' (len={len(text)}) "
            f"ST_available={self._sentence_transformer is not None}, "
            f"fallback_available={self._fallback_featurizer is not None}"
        )

        # Preferred: SentenceTransformer
        if self._sentence_transformer is not None:
            embeddings = self._sentence_transformer.encode(
                [text],
                convert_to_tensor=True,
                show_progress_bar=False,
            )
            feats = embeddings.cpu().numpy().flatten()
            return feats, "sentence_transformer", None

        # Fallback: TF-IDF
        if self.enable_fallback and self._fallback_featurizer is not None:
            feats = self._fallback_featurizer.transform(text)
            warning = (
                "Using TF-IDF fallback mode - may under-escalate compared to "
                "SentenceTransformer embeddings. Monitor drift_mode='tfidf' "
                "and GPU availability."
            )
            return feats, "tfidf", warning

        raise RuntimeError("No text featurizer available (neither ST nor TF-IDF)")

    def _extract_runtime_features(self, task: Dict[str, Any]) -> np.ndarray:
        """Extract runtime metrics and simple metadata from task."""
        features: List[float] = []

        # Task metadata
        features.append(float(task.get("priority", 5)) / 10.0)  # [0,1]
        features.append(float(task.get("complexity", 0.5)))  # assume [0,1]

        # Runtime metrics
        features.append(float(task.get("latency_ms", 0.0)) / 1000.0)  # seconds
        features.append(float(task.get("memory_usage", 0.5)))  # [0,1]
        features.append(float(task.get("cpu_usage", 0.5)))  # [0,1]

        # Task type encoding (simple one-hot)
        task_type = str(task.get("type", "unknown")).lower()
        type_features = [0.0] * 5
        type_mapping = {
            "general_query": 0,
            "anomaly_triage": 1,
            "execute": 2,
            "health_check": 3,
            "unknown": 4,
        }
        idx = type_mapping.get(task_type, 4)
        type_features[idx] = 1.0
        features.extend(type_features)

        # History features
        history_ids = task.get("history_ids", [])
        features.append(min(len(history_ids) / 10.0, 1.0))

        return np.array(features, dtype=np.float32)

    def _combine_features(
        self, text_features: np.ndarray, runtime_features: np.ndarray
    ) -> np.ndarray:
        """Combine text and runtime features into a single feature vector."""
        if (
            self._text_dim is None
            or self._runtime_dim is None
            or self._combined_dim is None
        ):
            raise RuntimeError(
                "Model dimensions not initialized; did you call _load_models()?"
            )

        # Normalize text feature length to self._text_dim
        if len(text_features) > self._text_dim:
            text_features = text_features[: self._text_dim]
        elif len(text_features) < self._text_dim:
            padding = np.zeros(self._text_dim - len(text_features), dtype=np.float32)
            text_features = np.concatenate([text_features, padding])

        # Ensure runtime features length is as expected (pad/truncate defensively)
        if len(runtime_features) > self._runtime_dim:
            runtime_features = runtime_features[: self._runtime_dim]
        elif len(runtime_features) < self._runtime_dim:
            padding = np.zeros(
                self._runtime_dim - len(runtime_features), dtype=np.float32
            )
            runtime_features = np.concatenate([runtime_features, padding])

        combined = np.concatenate([text_features, runtime_features])
        assert combined.shape[0] == self._combined_dim, (
            f"Combined feature dim mismatch: got {combined.shape[0]}, "
            f"expected {self._combined_dim}"
        )

        return combined.astype(np.float32)

    # ------------------------------------------------------------------
    # Neural-CUSUM scoring
    # ------------------------------------------------------------------

    def _update_cusum(self, inst_drift: float) -> float:
        """
        Update CUSUM-like state.

        inst_drift: instantaneous drift score in [0, 1]
        """
        residual = inst_drift - self._cusum_baseline
        self._cusum_state = max(0.0, self._cusum_decay * self._cusum_state + residual)
        self._cusum_updates += 1
        return self._cusum_state

    def _neural_cusum_score(
        self, features: np.ndarray
    ) -> Tuple[float, float, float, float]:
        """
        Run MLP and compute:
            - log_likelihood: log p_in
            - inst_drift: instantaneous drift in [0, 1]
            - final_score: combined instantaneous + CUSUM drift in [0, 1]
            - p_in: in-distribution probability
        """
        if not self._mlp:
            raise RuntimeError("MLP not loaded")

        # To tensor
        features_tensor = torch.from_numpy(features).unsqueeze(0).to(self.device)

        with torch.no_grad():
            logits = self._mlp(features_tensor)  # shape [1, 1]
            p_in = torch.sigmoid(logits)[0, 0].item()

        # Numerical stability
        eps = 1e-8
        p_in_clamped = min(max(p_in, eps), 1.0 - eps)
        log_likelihood = math.log(p_in_clamped)

        # Instantaneous drift: high when p_in is low
        inst_drift = 1.0 - p_in_clamped  # in [0, 1]

        # CUSUM update
        cusum_val = self._update_cusum(inst_drift)

        # Combine instantaneous and CUSUM for final score
        cusum_scaled = math.tanh(cusum_val)  # squashes [0, +∞) → [0, 1)
        final_score = 0.5 * inst_drift + 0.5 * cusum_scaled
        final_score = float(min(max(final_score, 0.0), 1.0))

        return log_likelihood, inst_drift, final_score, p_in_clamped

    def _compute_confidence(
        self,
        p_in: float,
        text: str,
        drift_mode: str,
    ) -> float:
        """
        Compute a confidence score based on:
        - distance of p_in from 0.5 (more extreme → more confident)
        - amount of history seen (CUSUM updates)
        - featurizer mode (ST vs TF-IDF)
        - text length (very short text → lower confidence)
        """
        # Base: how far from decision boundary (0.5)
        base = 2.0 * abs(p_in - 0.5)  # [0, 1]

        # History factor: more updates → more stable
        history_factor = min(1.0, 0.5 + 0.05 * self._cusum_updates)

        conf = base * history_factor

        # Penalize short text
        if len((text or "").strip()) < 20:
            conf *= 0.7

        # Penalize fallback mode
        if drift_mode == "tfidf":
            conf *= 0.8

        # Clamp to [0.1, 0.99]
        conf = max(0.1, min(conf, 0.99))
        return float(conf)

    # ------------------------------------------------------------------
    # Public API: compute_drift_score
    # ------------------------------------------------------------------

    async def compute_drift_score(
        self,
        task: Dict[str, Any],
        text: Optional[str] = None,
    ) -> DriftScore:
        """
        Compute drift score for a task.

        Args:
            task: Task dictionary with metadata and runtime metrics
            text: Optional text description to embed. If None, falls back to
                  task['description'] or task['type'].

        Returns:
            DriftScore object with:
                - score         ∈ [0, 1] (higher = more drift)
                - log_likelihood = log p_in
                - confidence    ∈ [0.1, 0.99]
        """
        start_time = time.time()

        logger.info(f"[DriftDetector] Received task: {task}")
        logger.info(f"[DriftDetector] Received text override: {text}")

        try:
            await self._load_models()

            # Choose text
            if text is None:
                text = task.get("description") or str(task.get("type", "unknown"))

            # Text features
            text_features, drift_mode, accuracy_warning = self._extract_text_features(
                text
            )
            logger.debug(
                f"[DriftDetector] Text features shape: {text_features.shape}, mode: {drift_mode}"
            )

            # Runtime features
            runtime_features = self._extract_runtime_features(task)
            logger.debug(
                f"[DriftDetector] Runtime features shape: {runtime_features.shape}"
            )

            # Combine
            combined_features = self._combine_features(text_features, runtime_features)
            logger.debug(
                f"[DriftDetector] Combined features shape: {combined_features.shape}"
            )

            # Neural-CUSUM scoring
            log_likelihood, inst_drift, final_score, p_in = self._neural_cusum_score(
                combined_features
            )

            # Confidence
            confidence = self._compute_confidence(p_in, text, drift_mode)

            processing_time = (time.time() - start_time) * 1000.0
            self._total_requests += 1
            self._total_time_ms += processing_time

            return DriftScore(
                score=final_score,
                log_likelihood=log_likelihood,
                confidence=confidence,
                feature_vector=combined_features,
                processing_time_ms=processing_time,
                model_version=self._model_version or "1.0.0",
                model_checksum=self._model_checksum or "",
                drift_mode=drift_mode,
                accuracy_warning=accuracy_warning,
            )

        except Exception as e:
            import traceback

            logger.error(f"[DriftDetector] Exception in compute_drift_score: {e}")
            logger.error(f"[DriftDetector] Full traceback:\n{traceback.format_exc()}")

            processing_time = (time.time() - start_time) * 1000.0

            return DriftScore(
                score=0.5,  # Neutral drift score
                log_likelihood=-0.5,
                confidence=0.1,
                feature_vector=None,
                processing_time_ms=processing_time,
                model_version=self._model_version or "1.0.0",
                model_checksum=self._model_checksum or "",
                drift_mode="fallback",
                accuracy_warning=(
                    "Drift detection failed - using neutral fallback score"
                ),
            )

    # ------------------------------------------------------------------
    # Misc
    # ------------------------------------------------------------------

    def get_performance_stats(self) -> Dict[str, Any]:
        """Get performance statistics."""
        avg_time = self._total_time_ms / max(1, self._total_requests)
        return {
            "total_requests": self._total_requests,
            "total_time_ms": self._total_time_ms,
            "average_time_ms": avg_time,
            "model_loaded": self._model_loaded,
            "model_name": self.model_name,
            "device": self.device,
        }

    async def close(self):
        """Clean up resources."""
        if self._thread_pool:
            self._thread_pool.shutdown(wait=True)


# ---------------------------------------------------------------------------
# Global instance + convenience function
# ---------------------------------------------------------------------------

_drift_detector: Optional[DriftDetector] = None


def get_drift_detector() -> DriftDetector:
    """Get the global drift detector instance."""
    global _drift_detector
    if _drift_detector is None:
        device = "cuda" if torch.cuda.is_available() else "cpu"
        _drift_detector = DriftDetector(device=device)
    return _drift_detector


async def compute_drift_score(
    task: Dict[str, Any],
    text: Optional[str] = None,
) -> DriftScore:
    """
    Convenience wrapper around DriftDetector.compute_drift_score.

    This is the function used by the ML API endpoint and by higher-level
    routing logic (e.g., OCPSValve integration).
    """
    detector = get_drift_detector()
    return await detector.compute_drift_score(task, text)
