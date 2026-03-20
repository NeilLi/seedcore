from __future__ import annotations

import os
from pathlib import Path

from seedcore.config.paths import DATA_DIR as DEFAULT_DATA_DIR
from seedcore.config.paths import OPT_DIR as DEFAULT_OPT_DIR


DATA_DIR = Path(os.getenv("SEEDCORE_ML_DATA_DIR", str(DEFAULT_DATA_DIR)))
OPT_DIR = Path(os.getenv("SEEDCORE_ML_OPT_DIR", str(DEFAULT_OPT_DIR)))
FUNCTIONGEMMA_DIR = Path(
    os.getenv("SEEDCORE_FUNCTIONGEMMA_DIR", str(OPT_DIR / "functiongemma"))
)

BASE_MODEL_ID = "google/functiongemma-270m-it"
LORA_ADAPTER_HF_ID = "Neilhybridbrain/functiongemma-intent-lora"

HF_CACHE_DIR = DATA_DIR / "hf_cache"
LORA_ADAPTER_CACHE_DIR = DATA_DIR / "checkpoints" / "functiongemma-intent-lora-cache"

INTENT_TOOL_DATASET_JSONL = FUNCTIONGEMMA_DIR / "intent-tool-dataset.jsonl"
INTENT_TOOL_SFT_DATASET_JSONL = FUNCTIONGEMMA_DIR / "intent-tool-sft-dataset.jsonl"
FUNCTION_CALL_DATASET_DIR = DATA_DIR / "function_call_dataset"

LORA_ADAPTER_DIR = DATA_DIR / "checkpoints" / "functiongemma-intent-lora"
CHECKPOINT_DIR = DATA_DIR / "checkpoints" / "functiongemma-270m-it-simple-tool-calling"


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    OPT_DIR.mkdir(parents=True, exist_ok=True)
    FUNCTIONGEMMA_DIR.mkdir(parents=True, exist_ok=True)
    HF_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    FUNCTION_CALL_DATASET_DIR.mkdir(parents=True, exist_ok=True)
    LORA_ADAPTER_DIR.mkdir(parents=True, exist_ok=True)
    LORA_ADAPTER_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)
