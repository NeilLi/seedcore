# seedcore/ml/distillation/sample_store.py

from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Tuple

import numpy as np

logger = logging.getLogger(__name__)

# Base directory for storing distillation samples
# You can mount a PVC here in Kubernetes, or override via env var.
DISTILLATION_DIR = Path(os.getenv("XGB_STORAGE_PATH", "/app/data"))
SAMPLES_FILE = DISTILLATION_DIR / "distillation_samples.jsonl"


def _ensure_dir() -> None:
    """Ensure the distillation directory exists."""
    try:
        DISTILLATION_DIR.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        logger.error(f"[sample_store] Failed to create distillation dir {DISTILLATION_DIR}: {e}")
        raise


def _sanitize_sample(sample: Dict[str, Any]) -> Dict[str, Any]:
    """
    Light JSON-serialization safety for samples.
    Assumes features are already primitive types; just ensures non-serializable values are stringified.
    """
    def _sanitize(v: Any) -> Any:
        if isinstance(v, (str, int, float, bool)) or v is None:
            return v
        if isinstance(v, dict):
            return {k: _sanitize(x) for k, x in v.items()}
        if isinstance(v, (list, tuple)):
            return [_sanitize(x) for x in v]
        # Fallback: stringify anything else
        return str(v)

    return _sanitize(sample)  # type: ignore[return-value]


async def append_sample(sample: Dict[str, Any]) -> None:
    """
    Append a single distillation sample to the JSONL file.

    Expected sample structure (flexible, but recommended):
    {
        "episode_id": "...",
        "features": {"cap_mean": 0.7, "lat_mean": 350.0, ...},
        "regime_label": "ANALYSIS_BOTTLENECK",
        "action_label": "SHIFT_ANALYSIS_TO_CLUSTER_C",
        "confidence": 0.87,
        "start_ts": ...,
        "end_ts": ...
    }
    """
    _ensure_dir()
    sanitized = _sanitize_sample(sample)

    # Use a thread to avoid blocking the event loop on disk I/O
    def _write():
        try:
            with SAMPLES_FILE.open("a", encoding="utf-8") as f:
                f.write(json.dumps(sanitized) + "\n")
        except Exception as e:
            logger.error(f"[sample_store] Failed to append sample: {e}")
            raise

    await asyncio.to_thread(_write)
    logger.debug(f"[sample_store] Appended distillation sample: episode_id={sample.get('episode_id')}")


def _read_all_samples() -> List[Dict[str, Any]]:
    """Read all samples from the JSONL file into memory."""
    if not SAMPLES_FILE.exists():
        logger.warning(f"[sample_store] Samples file not found: {SAMPLES_FILE}")
        return []

    samples: List[Dict[str, Any]] = []
    try:
        with SAMPLES_FILE.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    if isinstance(obj, dict):
                        samples.append(obj)
                except json.JSONDecodeError as e:
                    logger.warning(f"[sample_store] Skipping invalid JSON line: {e}")
    except Exception as e:
        logger.error(f"[sample_store] Failed to read samples file: {e}")
        raise

    logger.info(f"[sample_store] Loaded {len(samples)} distillation samples from {SAMPLES_FILE}")
    return samples


def load_distillation_dataset(
    label_type: str = "regime_label",
    min_confidence: float = 0.0,
) -> Tuple[np.ndarray, np.ndarray, List[str]]:
    """
    Load distillation samples into (X, y, feature_names) for XGBoost training.

    Args:
        label_type: Which label field to use, e.g. "regime_label" or "action_label".
        min_confidence: Optional threshold to filter out low-confidence LLM labels.

    Returns:
        X: np.ndarray of shape (N, D) with feature values.
        y: np.ndarray of shape (N,) with labels (string or numeric).
        feature_names: list of feature keys in the order used for X.
    """
    samples = _read_all_samples()
    if not samples:
        raise RuntimeError("[sample_store] No distillation samples available")

    # Collect all feature keys across samples to define a consistent feature space
    all_feature_keys: set[str] = set()
    for s in samples:
        feats = s.get("features") or {}
        if isinstance(feats, dict):
            all_feature_keys.update(feats.keys())

    if not all_feature_keys:
        raise RuntimeError("[sample_store] No feature keys found in samples")

    feature_names: List[str] = sorted(all_feature_keys)

    X_list: List[List[float]] = []
    y_list: List[Any] = []

    for s in samples:
        confidence = float(s.get("confidence", 1.0))
        if confidence < min_confidence:
            continue

        feats = s.get("features") or {}
        if not isinstance(feats, dict):
            continue

        # Build feature vector in fixed order
        row: List[float] = []
        for key in feature_names:
            v = feats.get(key, 0.0)
            try:
                row.append(float(v))
            except Exception:
                row.append(0.0)

        label = s.get(label_type)
        if label is None:
            continue

        X_list.append(row)
        y_list.append(label)

    if not X_list:
        raise RuntimeError("[sample_store] No usable samples after filtering")

    X = np.array(X_list, dtype=np.float32)
    y = np.array(y_list)

    logger.info(
        f"[sample_store] Built dataset for label_type='{label_type}': "
        f"N={X.shape[0]}, D={X.shape[1]}, features={feature_names}"
    )
    return X, y, feature_names
