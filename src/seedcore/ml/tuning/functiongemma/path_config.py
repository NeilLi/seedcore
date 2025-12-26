"""
Centralized path configuration for FunctionGemma tuning pipeline.

All paths are configured here for easy maintenance and environment-specific overrides.
"""
from pathlib import Path

# ---------------------------------------------------------------------
# Base directories
# ---------------------------------------------------------------------
# Data directory (for datasets, checkpoints, cache)
DATA_DIR = Path("/app/data")

# Opt directory (for input datasets)
OPT_DIR = Path("/app/opt")

# ---------------------------------------------------------------------
# Model configuration
# ---------------------------------------------------------------------
BASE_MODEL_ID = "google/functiongemma-270m-it"

# LoRA adapter HuggingFace repository (private)
LORA_ADAPTER_HF_ID = "Neilhybridbrain/functiongemma-intent-lora"

# HuggingFace cache directory
HF_CACHE_DIR = DATA_DIR / "hf_cache"

# Local cache directory for LoRA adapter (downloaded from HF)
LORA_ADAPTER_CACHE_DIR = DATA_DIR / "checkpoints" / "functiongemma-intent-lora-cache"

# ---------------------------------------------------------------------
# Dataset paths
# ---------------------------------------------------------------------
# Input: Raw intent tool dataset (from build_intent_dataset.py)
INTENT_TOOL_DATASET_JSONL = OPT_DIR / "functiongemma" / "intent_tool_dataset_2025-12-26.jsonl"

# Intermediate: SFT-formatted dataset (output of build_intent_dataset.py)
INTENT_TOOL_SFT_DATASET_JSONL = OPT_DIR / "functiongemma" / "intent_tool_sft_dataset.jsonl"

# Output: Processed function call dataset (output of prepare_function_call_data.py)
FUNCTION_CALL_DATASET_DIR = DATA_DIR / "function_call_dataset"

# ---------------------------------------------------------------------
# Checkpoint paths
# ---------------------------------------------------------------------
# LoRA adapter output directory
LORA_ADAPTER_DIR = DATA_DIR / "checkpoints" / "functiongemma-intent-lora"

# Alternative checkpoint directory (from model_loader.py)
CHECKPOINT_DIR = DATA_DIR / "checkpoints" / "functiongemma-270m-it-simple-tool-calling"

# ---------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------
def ensure_dirs():
    """Create all necessary directories if they don't exist."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    OPT_DIR.mkdir(parents=True, exist_ok=True)
    HF_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    FUNCTION_CALL_DATASET_DIR.mkdir(parents=True, exist_ok=True)
    LORA_ADAPTER_DIR.mkdir(parents=True, exist_ok=True)
    LORA_ADAPTER_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)
    (OPT_DIR / "functiongemma").mkdir(parents=True, exist_ok=True)

