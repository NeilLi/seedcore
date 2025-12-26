"""
Intent Compiler Module for SeedCore

Provides deterministic natural-language → structured function call translation
using FunctionGemma as a low-latency intent compiler.

This is NOT a conversational LLM or tool executor. It's a pure inference service
that converts user text into validated function calls.
"""

from __future__ import annotations

import os
import time
import asyncio
import json
import re
from typing import Dict, Any, Optional, List
from dataclasses import dataclass

from seedcore.logging_setup import setup_logging, ensure_serve_logger
from seedcore.ml.warmup_policy import get_warmup_mode, WarmupMode

setup_logging(app_name="seedcore.intent.intent_compiler.driver")
logger = ensure_serve_logger("seedcore.intent.intent_compiler", level="DEBUG")

# ----------------------------
# Hugging Face Cache Control
# ----------------------------

HF_CACHE_ROOT = (
    os.getenv("HF_HOME") or os.getenv("TRANSFORMERS_CACHE") or "/app/data/hf_cache"
)

os.environ.setdefault("HF_HOME", HF_CACHE_ROOT)
os.environ.setdefault("TRANSFORMERS_CACHE", HF_CACHE_ROOT)
os.environ.setdefault("HF_HUB_CACHE", HF_CACHE_ROOT)

logger.info("[IntentCompiler] HF cache root: %s", HF_CACHE_ROOT)

# FunctionGemma/Transformers imports
try:
    import torch  # pyright: ignore[reportMissingImports]
    from transformers import (
        AutoProcessor,
        AutoModelForCausalLM,
        AutoTokenizer,
        BitsAndBytesConfig,
        StoppingCriteria,
        StoppingCriteriaList,
    )  # pyright: ignore[reportMissingImports]
    from transformers.utils import get_json_schema  # pyright: ignore[reportMissingImports]
    from peft import PeftModel  # pyright: ignore[reportMissingImports]

    FUNCTIONGEMMA_AVAILABLE = True
except ImportError:
    FUNCTIONGEMMA_AVAILABLE = False
    torch = None  # type: ignore
    StoppingCriteria = None  # type: ignore
    StoppingCriteriaList = None  # type: ignore
    get_json_schema = None  # type: ignore


# ----------------------------
# Helpers
# ----------------------------

_HEX_DEVICE_RE = re.compile(r"\b[a-fA-F0-9]{16,64}\b")
_FUNCTION_CALL_PATTERN = re.compile(
    r"<start_function_call>\s*call:([\w\.]+)\s*(\{.*?\})\s*<end_function_call>",
    re.DOTALL,
)


def _find_first_json_object(text: str) -> Optional[tuple[int, int]]:
    """
    Find the first JSON object in text by matching braces.
    Returns (start_index, end_index) or None if not found.

    This is more robust than regex for nested structures since Python's
    re module doesn't support recursive patterns like (?R).
    """
    if not text:
        return None

    start = -1
    brace_count = 0

    for i, char in enumerate(text):
        if char == "{":
            if start == -1:
                start = i
            brace_count += 1
        elif char == "}":
            if start != -1:
                brace_count -= 1
                if brace_count == 0:
                    return (start, i + 1)

    return None


def _now_ms() -> float:
    return time.time() * 1000.0


def _safe_dumps(obj: Any, max_chars: int) -> str:
    """
    Dump JSON with compact separators and hard cap size.
    Prevents giant schema/context prompts from blowing latency/memory.
    """
    try:
        s = json.dumps(obj, separators=(",", ":"), ensure_ascii=False)
    except Exception:
        s = "{}"
    if len(s) > max_chars:
        # Keep head + tail to preserve some function names and structure.
        head = s[: max_chars // 2]
        tail = s[-(max_chars // 2) :]
        s = head + "…TRUNCATED…" + tail
    return s


def _extract_first_json_obj(text: str) -> Optional[dict]:
    """
    Robustly extract first JSON object from a model response.
    We avoid assuming it cleanly ends after Output:.
    """
    if not text:
        return None

    # Prefer anything after a marker first
    candidates: List[str] = []
    if "Output:" in text:
        candidates.append(text.split("Output:", 1)[-1])
    candidates.append(text)

    for cand in candidates:
        match_pos = _find_first_json_object(cand)
        if not match_pos:
            continue
        start, end = match_pos
        blob = cand[start:end]
        try:
            data = json.loads(blob)
            if isinstance(data, dict):
                return data
        except Exception:
            continue
    return None


def _coerce_confidence(base: float) -> float:
    try:
        x = float(base)
    except Exception:
        return 0.0
    return max(0.0, min(1.0, x))


def _strip_escape_tokens(s: str) -> str:
    """Remove <escape> tokens from Gemma output."""
    return s.replace("<escape>", "").strip()


def _gemma_args_to_jsonish(s: str) -> str:
    """
    Convert Gemma-style args like:
      {commands:{device_id:bedroom_light_id},device_id:living_room_light_id}
    into JSON-ish:
      {"commands":{"device_id":"bedroom_light_id"},"device_id":"living_room_light_id"}
    This is heuristic but works well for common cases.
    
    Also handles <escape> tokens that Gemma inserts around values.
    """
    # Strip escape tokens first (they can appear anywhere)
    s = _strip_escape_tokens(s)

    # Ensure outer braces
    s = s.strip()
    if not (s.startswith("{") and s.endswith("}")):
        return s

    # Quote keys: {a:... , b:...} -> {"a":... , "b":...}
    s = re.sub(r"([{,]\s*)([A-Za-z_][\w\-]*)\s*:", r'\1"\2":', s)

    # Now process values: find all colons and quote bareword values
    result = []
    i = 0
    brace_depth = 0

    while i < len(s):
        char = s[i]

        if char == "{":
            brace_depth += 1
            result.append(char)
            i += 1
        elif char == "}":
            brace_depth -= 1
            result.append(char)
            i += 1
        elif char == ":" and i + 1 < len(s):
            result.append(char)
            i += 1
            # Skip whitespace after colon
            while i < len(s) and s[i] in " \t\n":
                result.append(s[i])
                i += 1

            if i >= len(s):
                break

            val_start = i
            val_brace_depth = brace_depth

            # Check what follows the colon
            if s[i] == "{":
                # Nested object - find its end and process recursively
                nested_start = i
                nested_depth = 1
                brace_depth += 1  # Track the opening brace
                i += 1
                while i < len(s) and nested_depth > 0:
                    if s[i] == "{":
                        nested_depth += 1
                        brace_depth += 1
                    elif s[i] == "}":
                        nested_depth -= 1
                        brace_depth -= 1
                    i += 1
                nested_str = s[nested_start:i]
                nested_processed = _gemma_args_to_jsonish(nested_str)
                result.append(nested_processed)
            elif s[i] == "[":
                # Array - find its end and process contents
                array_start = i
                array_depth = 1
                i += 1
                while i < len(s) and array_depth > 0:
                    if s[i] == "[":
                        array_depth += 1
                    elif s[i] == "]":
                        array_depth -= 1
                    i += 1
                array_str = s[array_start:i]
                # Process array contents: strip escape tokens and quote string values
                array_content = array_str[1:-1].strip()  # Remove [ and ]
                if array_content:
                    # Split by comma, but be careful with nested structures
                    items = []
                    current_item = ""
                    depth = 0
                    for char in array_content:
                        if char in "[{":
                            depth += 1
                            current_item += char
                        elif char in "]}":
                            depth -= 1
                            current_item += char
                        elif char == "," and depth == 0:
                            # Top-level comma - process this item
                            item = _strip_escape_tokens(current_item.strip())
                            if item and not item.startswith('"'):
                                if not (
                                    re.fullmatch(r"-?\d+(\.\d+)?", item)
                                    or item in ("true", "false", "null")
                                ):
                                    item = '"' + item + '"'
                            items.append(item)
                            current_item = ""
                        else:
                            current_item += char
                    # Process last item
                    if current_item.strip():
                        item = _strip_escape_tokens(current_item.strip())
                        if item and not item.startswith('"'):
                            if not (
                                re.fullmatch(r"-?\d+(\.\d+)?", item)
                                or item in ("true", "false", "null")
                            ):
                                item = '"' + item + '"'
                        items.append(item)
                    result.append("[" + ",".join(items) + "]")
                else:
                    result.append("[]")
            elif s[i] == '"':
                # Already quoted string - find its end
                result.append(s[i])
                i += 1
                while i < len(s):
                    if s[i] == "\\" and i + 1 < len(s):
                        result.append(s[i : i + 2])
                        i += 2
                    elif s[i] == '"':
                        result.append(s[i])
                        i += 1
                        break
                    else:
                        result.append(s[i])
                        i += 1
            else:
                # Find the end of this value (comma or closing brace at same depth)
                while i < len(s):
                    if s[i] == "{":
                        brace_depth += 1
                        i += 1
                    elif s[i] == "}":
                        if brace_depth == val_brace_depth:
                            # This closes the object containing our value
                            break
                        brace_depth -= 1
                        i += 1
                    elif s[i] == "," and brace_depth == val_brace_depth:
                        # Top-level comma, value ends here
                        break
                    else:
                        i += 1

                value = s[val_start:i].strip()

                # Check if it's a number, boolean, or null
                if (
                    re.fullmatch(r"-?\d+(\.\d+)?", value)
                    or value in ("true", "false", "null")
                ):
                    result.append(value)
                else:
                    # Bareword string - quote it
                    result.append('"' + value + '"')
        else:
            result.append(char)
            i += 1

    return "".join(result)


@dataclass
class IntentResult:
    """
    Deterministic output from intent compilation.

    This is the ONLY output format. No reasoning text, no explanations,
    no fallback logic. Pure structured data for orchestration.
    """

    function: str
    arguments: Dict[str, Any]
    confidence: float  # [0.0, 1.0]
    model_version: str = "1.0.0"
    processing_time_ms: float = 0.0
    is_fallback: bool = False  # True if fallback heuristics were used
    error: Optional[str] = None  # optional internal error message for debugging

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "ok": True,
            "function": self.function,
            "arguments": self.arguments,
            "confidence": _coerce_confidence(self.confidence),
            "model_version": self.model_version,
            "processing_time_ms": self.processing_time_ms,
            "is_fallback": self.is_fallback,
            "error": self.error,
            # Add diagnostic info to help debug model usage
            "diagnostics": {
                "used_model": not self.is_fallback,
                "model_version": self.model_version if not self.is_fallback else None,
            },
        }


if StoppingCriteria is not None:

    class StopOnAnySubsequence(StoppingCriteria):
        """Stop generation when any of the stop sequences is found."""

        def __init__(self, tokenizer, stop_strings: List[str]):
            super().__init__()
            self.stop_seqs = [
                tokenizer.encode(s, add_special_tokens=False) for s in stop_strings
            ]

        def __call__(self, input_ids, scores, **kwargs):
            ids = input_ids[0].tolist()
            # Search in recent window (last 512 tokens) instead of just suffix
            window = ids[-512:] if len(ids) > 512 else ids
            for seq in self.stop_seqs:
                # Naive subsequence scan in window
                for i in range(0, len(window) - len(seq) + 1):
                    if window[i : i + len(seq)] == seq:
                        return True
            return False

else:
    # Dummy class if StoppingCriteria not available
    class StopOnAnySubsequence:  # type: ignore
        def __init__(self, tokenizer, stop_strings: List[str]):
            pass

        def __call__(self, input_ids, scores, **kwargs):
            return False


class IntentCompiler:
    """
    Intent Compilation Service (FunctionGemma-backed)

    Converts natural language into structured function calls.
    No side effects. No tool execution. Pure inference.
    """

    # Confidence values that encode execution path (not just accuracy)
    BASE_CONFIDENCE = {
        "model_schema_valid": 0.97,
        "model_schema_invalid": 0.75,
        "model_unknown_fn": 0.35,  # Model produced unknown function (not in schema)
        "fallback_schema": 0.55,  # Fallback with schema match
        "fallback_guess": 0.45,  # Fallback without schema match
        "unsupported": 0.15,  # Unsupported intent (early exit)
    }

    def __init__(
        self, model_path: Optional[str] = None, lora_path: Optional[str] = None
    ):
        self.model_path = model_path or os.getenv(
            "FUNCTIONGEMMA_MODEL_PATH", "google/functiongemma-270m-it"
        )
        self.lora_path = lora_path or os.getenv(
            "FUNCTIONGEMMA_LORA_PATH", "Neilhybridbrain/functiongemma-intent-lora"
        )

        self.model = None
        self.processor = None
        self.tokenizer = None  # Separate tokenizer for apply_chat_template

        # Warmup state tracking (separate from legacy _warmed_up for backward compatibility)
        self._model_loaded = False  # True when model weights are loaded
        self._heavy_warmed = False  # True when heavy warmup (inference) is complete
        self._warmed_up = False  # Legacy flag (kept for backward compatibility)
        self._warmup_lock: Optional[asyncio.Lock] = None  # Concurrency guard for warmup

        self.model_version = os.getenv("FUNCTIONGEMMA_VERSION", "1.0.0")

        # Load mode tracking for observability
        self._load_mode: Optional[str] = None  # offline_cache | hub_download | fallback
        self._load_error: Optional[str] = None

        # Hugging Face token for gated models (e.g., FunctionGemma)
        # Can be set via HF_TOKEN environment variable or explicitly passed
        self.hf_token = os.getenv("HF_TOKEN") or os.getenv("HUGGINGFACE_HUB_TOKEN")
        if self.hf_token:
            # Log that token is available (but don't expose the actual token)
            logger.info(
                "[IntentCompiler] HF_TOKEN detected (gated model access enabled)"
            )
        else:
            logger.warning(
                "[IntentCompiler] No HF_TOKEN found. If model is gated, you may need to set HF_TOKEN environment variable."
            )

        # Prompt controls
        self.max_schema_chars = int(os.getenv("INTENT_MAX_SCHEMA_CHARS", "8000"))
        self.max_context_chars = int(os.getenv("INTENT_MAX_CONTEXT_CHARS", "2000"))
        self.max_input_chars = int(os.getenv("INTENT_MAX_INPUT_CHARS", "512"))

        # Generation controls (keep deterministic)
        self.max_new_tokens = int(os.getenv("INTENT_MAX_NEW_TOKENS", "128"))

        # Latency guard: fallback if inference exceeds threshold (ms)
        # Set to 0 to disable (default: 0 = disabled, based on p95 latency ~8-9s on CPU)
        # Can be set to 10000 (10s) or higher if you want to enforce a hard SLO
        self.max_inference_ms = int(os.getenv("INTENT_MAX_INFERENCE_MS", "0"))

        # Lazy init + concurrency guard
        self._loading_lock: Optional[asyncio.Lock] = None
        self._using_fallback = not FUNCTIONGEMMA_AVAILABLE

        # Configuration: prefer model over fallback when model is loaded
        self.prefer_model_over_fallback = os.getenv(
            "INTENT_PREFER_MODEL", "true"
        ).lower() in ("true", "1", "yes")

        if not FUNCTIONGEMMA_AVAILABLE:
            logger.warning(
                "FunctionGemma deps not available. Intent compiler will use fallback mode."
            )

    async def _load_model(self) -> None:
        """
        Load FunctionGemma model/processor (lazy, lock-protected).

        Uses 4-bit quantization via BitsAndBytesConfig for 8GB Mac compatibility.
        Falls back to auto dtype if quantization unavailable.
        """
        if self.model is not None or self._using_fallback:
            return

        if self._loading_lock is None:
            self._loading_lock = asyncio.Lock()

        async with self._loading_lock:
            if self.model is not None or self._using_fallback:
                return

            if not FUNCTIONGEMMA_AVAILABLE:
                self._using_fallback = True
                return

            if not self.model_path:
                logger.warning(
                    "No model path configured (FUNCTIONGEMMA_MODEL_PATH). Using fallback."
                )
                self._using_fallback = True
                return

            # Explicit Token Check (Fetched at runtime to ensure Ray worker isolation doesn't drop it)
            hf_token = os.getenv("HF_TOKEN") or os.getenv("HUGGINGFACE_HUB_TOKEN")

            try:
                # Runtime version check for debugging architecture mismatches
                try:
                    import transformers  # pyright: ignore[reportMissingImports]
                    import peft  # pyright: ignore[reportMissingImports]

                    logger.info(
                        "[IntentCompiler] Runtime Check: transformers==%s, peft==%s, torch==%s",
                        transformers.__version__,
                        peft.__version__,
                        torch.__version__ if torch else "N/A",
                    )
                except Exception:
                    pass

                logger.info("🚀 Loading FunctionGemma [%s]...", self.model_path)
                logger.debug("HF_TOKEN presence: %s", bool(hf_token))

                # 1. Load Processor and Tokenizer (Offline-First Strategy)
                # Try local cache first to avoid network/DNS issues in Kind clusters
                try:
                    self.processor = AutoProcessor.from_pretrained(
                        self.model_path,
                        local_files_only=True,  # Try local cache first
                        trust_remote_code=True,
                    )
                    # Also load tokenizer separately for apply_chat_template
                    self.tokenizer = AutoTokenizer.from_pretrained(
                        self.model_path,
                        local_files_only=True,
                        trust_remote_code=True,
                    )
                    self._load_mode = "offline_cache"
                    logger.info("✅ Processor and tokenizer loaded from local cache")
                except Exception:
                    # Fallback to network download with token
                    logger.info("Local cache miss, attempting Hub download...")
                    self.processor = AutoProcessor.from_pretrained(
                        self.model_path,
                        token=hf_token,
                        trust_remote_code=True,
                    )
                    self.tokenizer = AutoTokenizer.from_pretrained(
                        self.model_path,
                        token=hf_token,
                        trust_remote_code=True,
                    )
                    self._load_mode = "hub_download"
                    logger.info("✅ Processor and tokenizer downloaded from Hugging Face Hub")

                # 2. Hardware/Quantization Setup
                use_cuda = torch and torch.cuda.is_available()
                q_config = None
                if use_cuda:
                    try:
                        q_config = BitsAndBytesConfig(
                            load_in_4bit=True,
                            bnb_4bit_quant_type="nf4",
                            bnb_4bit_compute_dtype=torch.float16,
                            bnb_4bit_use_double_quant=True,
                        )
                        logger.info("✅ Using 4-bit NF4 quantization (CUDA available)")
                    except Exception as e:
                        logger.warning(
                            "BitsAndBytesConfig unavailable; will attempt fallback loading: %s",
                            e,
                        )
                else:
                    logger.info(
                        "No CUDA - will load in CPU mode (may be slow for large models)"
                    )

                # 3. Load Base Model (Offline-First Strategy)
                # Explicitly setting low_cpu_mem_usage is vital for your 8GB Mac environment
                try:
                    self.model = AutoModelForCausalLM.from_pretrained(
                        self.model_path,
                        quantization_config=q_config,
                        device_map="auto" if use_cuda else None,
                        local_files_only=True,  # Try local cache first
                        trust_remote_code=True,
                        low_cpu_mem_usage=True,
                    )
                    if (
                        self._load_mode != "hub_download"
                    ):  # Preserve hub_download if processor was from hub
                        self._load_mode = "offline_cache"
                    logger.info("✅ Base model loaded from local cache")
                except Exception:
                    # Fallback to network download with token
                    logger.info("Local cache miss, attempting Hub download...")
                    self.model = AutoModelForCausalLM.from_pretrained(
                        self.model_path,
                        quantization_config=q_config,
                        device_map="auto" if use_cuda else None,
                        token=hf_token,
                        trust_remote_code=True,
                        low_cpu_mem_usage=True,
                    )
                    self._load_mode = "hub_download"
                    logger.info("✅ Base model downloaded from Hugging Face Hub")

                # 4. Apply LoRA Adapter
                # Support both local paths and HuggingFace Hub repo IDs
                # Remove os.path.exists() check to allow Hub-only usage
                if self.lora_path:
                    logger.info("Applying LoRA adapter from %s", self.lora_path)
                    try:
                        # LoRA adapters can ALSO be gated, so we pass the token here too
                        # Try local first (LoRA is usually local path, but handle both cases)
                        try:
                            self.model = PeftModel.from_pretrained(
                                self.model,
                                self.lora_path,
                                local_files_only=True,  # Try local first
                            )
                            logger.info("✅ LoRA adapter loaded from local cache")
                        except Exception:
                            # Fallback to network if LoRA is a Hub path
                            self.model = PeftModel.from_pretrained(
                                self.model,
                                self.lora_path,
                                token=hf_token,
                            )
                            logger.info(
                                "✅ LoRA adapter loaded from Hugging Face Hub"
                            )
                    except Exception as e:
                        logger.warning(
                            "Failed to load LoRA adapter: %s (continuing without LoRA)",
                            e,
                        )

                self.model.eval()
                device = getattr(self.model, "device", "cpu")
                logger.info("✅ FunctionGemma ready. Device: %s", device)
                self._model_loaded = (
                    True  # Mark as loaded after successful initialization
                )

            except Exception as e:
                error_str = str(e).lower()
                self._load_error = str(e)

                # Fail fast on authorization errors - do NOT retry endlessly
                if any(
                    k in error_str
                    for k in ("401", "403", "gated", "unauthorized", "forbidden")
                ):
                    logger.critical(
                        "❌ AUTHORIZATION FAILURE loading %s. "
                        "Token is present but lacks permission OR terms not accepted. "
                        "1. Go to HF model page and click 'Accept Terms'. "
                        "2. Ensure HF_TOKEN is correctly set in Ray workers.",
                        self.model_path,
                    )
                    self._using_fallback = True
                    self._load_mode = "fallback"
                    # Clean up partial loads to free Mac RAM
                    self.model = None
                    self.processor = None
                    if torch and torch.cuda.is_available():
                        torch.cuda.empty_cache()
                    return

                # Non-auth errors: log and fallback
                logger.error("❌ Model load failed (non-auth): %s", e, exc_info=True)
                self._using_fallback = True
                self._load_mode = "fallback"
                # Clean up partial loads to free Mac RAM
                self.model = None
                self.processor = None
                if torch and torch.cuda.is_available():
                    torch.cuda.empty_cache()

    async def _run_warmup_inference(self, prompt: str) -> float:
        """
        Simplified inference for warmup purposes.
        Only runs forward pass to prime the model - doesn't require valid JSON.
        
        Returns:
            inference_elapsed_ms (latency measurement)
        """
        inference_start = _now_ms()

        # Use tokenizer if available, otherwise fall back to processor
        tokenizer_to_use = self.tokenizer if self.tokenizer else self.processor
        if not tokenizer_to_use:
            raise ValueError("Neither tokenizer nor processor available")

        # Process prompt
        inputs = tokenizer_to_use(prompt, return_tensors="pt")
        # Move tensors to model device
        device = getattr(self.model, "device", None)
        if device:
            inputs = {
                k: v.to(device) if hasattr(v, "to") else v for k, v in inputs.items()
            }

        with torch.inference_mode():
            # Get pad_token_id safely (processor may be the tokenizer itself for Gemma)
            pad_token_id = None
            if hasattr(self.processor, "tokenizer") and hasattr(
                self.processor.tokenizer, "pad_token_id"
            ):
                pad_token_id = self.processor.tokenizer.pad_token_id
            elif hasattr(self.processor, "pad_token_id"):
                pad_token_id = self.processor.pad_token_id

            # Run generation (this primes the model's inference path)
            outputs = self.model.generate(
                **inputs,
                max_new_tokens=self.max_new_tokens,
                do_sample=False,  # Pure determinism
                temperature=0.0,
                pad_token_id=pad_token_id,
            )

        # Decode to verify output (but don't require valid JSON for warmup)
        try:
            # Decode only generated tokens
            input_length = inputs["input_ids"].shape[1]
            gen_ids = outputs[0, input_length:]
            decoded = tokenizer_to_use.decode(gen_ids, skip_special_tokens=False)
            
            # Log decoded output for debugging (but don't fail if it's not JSON)
            logger.debug("[IntentCompiler] Warmup inference output: %s", decoded[:200])
        except Exception as e:
            logger.debug("[IntentCompiler] Warmup inference decode warning: %s", e)

        inference_elapsed_ms = _now_ms() - inference_start
        return inference_elapsed_ms

    def _post_validate_semantics(
        self, fn: str, args: Dict[str, Any], text: str
    ) -> tuple[Dict[str, Any], Optional[str]]:
        """
        Post-validate and repair semantic errors in function arguments.
        
        Returns:
            (repaired_args, error_msg) where error_msg is None if valid,
            "repaired_*" if repaired, or "invalid_*" if invalid and not repairable
        """
        text_lower = (text or "").lower().strip()
        
        # Example: for power.set_energy_policy, validate/repair mode parameter
        if fn == "power.set_energy_policy":
            mode = args.get("mode")
            if isinstance(mode, str):
                m = mode.lower().strip()
                if m not in {"on", "off", "eco", "balanced", "performance"}:
                    # Attempt repair from user text
                    if "turn on" in text_lower or text_lower.strip() == "on":
                        args["mode"] = "on"
                        return args, "repaired_mode_from_text"
                    if "turn off" in text_lower or text_lower.strip() == "off":
                        args["mode"] = "off"
                        return args, "repaired_mode_from_text"
                    # Check for other valid modes
                    if "eco" in text_lower:
                        args["mode"] = "eco"
                        return args, "repaired_mode_from_text"
                    if "balanced" in text_lower:
                        args["mode"] = "balanced"
                        return args, "repaired_mode_from_text"
                    if "performance" in text_lower:
                        args["mode"] = "performance"
                        return args, "repaired_mode_from_text"
                    return args, "invalid_mode"
        
        return args, None

    async def _run_model_inference(
        self,
        prompt: str,
        schema_registry=None,
        text: Optional[str] = None,
    ) -> tuple[str, Dict[str, Any], float, Optional[str], float]:
        """
        Core model inference logic (extracted from compile to avoid recursion).
        Uses FunctionGemma chat template format with proper stopping criteria.

        Returns:
            (function_name, arguments, confidence, error_msg, inference_elapsed_ms)
        """
        inference_start = _now_ms()

        # Use tokenizer if available, otherwise fall back to processor
        tokenizer_to_use = self.tokenizer if self.tokenizer else self.processor
        if not tokenizer_to_use:
            raise ValueError("Neither tokenizer nor processor available")

        # Tokenize prompt
        inputs = tokenizer_to_use(prompt, return_tensors="pt")
        # Move tensors to model device
        device = getattr(self.model, "device", None)
        if device:
            inputs = {
                k: v.to(device) if hasattr(v, "to") else v for k, v in inputs.items()
            }

        # Get pad_token_id and eos_token_id
        pad_token_id = None
        eos_token_id = None
        if hasattr(tokenizer_to_use, "pad_token_id"):
            pad_token_id = tokenizer_to_use.pad_token_id
        if hasattr(tokenizer_to_use, "eos_token_id"):
            eos_token_id = tokenizer_to_use.eos_token_id
        if pad_token_id is None:
            pad_token_id = eos_token_id

        # Set up stopping criteria for FunctionGemma function calls
        stopping_criteria = None
        if StoppingCriteriaList and self.tokenizer:
            stopping = StopOnAnySubsequence(
                self.tokenizer, ["<end_function_call>", "<start_function_response>"]
            )
            stopping_criteria = StoppingCriteriaList([stopping])

        with torch.inference_mode():
            outputs = self.model.generate(
                **inputs,
                max_new_tokens=self.max_new_tokens,
                do_sample=False,  # Pure determinism
                temperature=0.0,
                use_cache=True,  # Enable KV cache for faster generation
                pad_token_id=pad_token_id,
                eos_token_id=eos_token_id,
                stopping_criteria=stopping_criteria,
            )

        # Decode ONLY the newly generated tokens (prevents echo of tool declarations)
        input_length = inputs["input_ids"].shape[1]
        gen_ids = outputs[0, input_length:]
        generated = tokenizer_to_use.decode(gen_ids, skip_special_tokens=False)

        # Debug: Log raw model output (truncated for safety)
        logger.debug(
            "[IntentCompiler] Raw model output (first 500 chars): %s",
            generated[:500],
        )

        # Parse FunctionGemma-style function call: <start_function_call>call:function_name{...}<end_function_call>
        fn = "unknown"
        args = {}
        args_normalized = False  # Track if normalization was used

        match = _FUNCTION_CALL_PATTERN.search(generated)
        if match:
            logger.debug(
                "[IntentCompiler] Function call pattern matched: function=%s, args_text=%s",
                match.group(1),
                match.group(2)[:200],
            )
            fn = match.group(1).strip()
            args_text = match.group(2).strip()

            # Parse arguments: try strict JSON first, then normalize (Gemma often emits non-JSON)
            try:
                args = json.loads(args_text)
                logger.debug(
                    "[IntentCompiler] Successfully parsed arguments as strict JSON: %s",
                    args,
                )
            except json.JSONDecodeError:
                # Normalize Gemma-style output (primary path for tool-calls)
                try:
                    jsonish = _gemma_args_to_jsonish(args_text)
                    args = json.loads(jsonish)
                    args_normalized = True
                    logger.debug(
                        "[IntentCompiler] Successfully parsed arguments after Gemma normalization: %s",
                        args,
                    )
                except json.JSONDecodeError as e2:
                    logger.warning(
                        "[IntentCompiler] Failed to parse function arguments (both strict and normalized): %s. Raw args_text: %s",
                        e2,
                        args_text[:200],
                    )
                    args = {}
        else:
            # Fallback: try to extract JSON from output
            data = _extract_first_json_obj(generated)
            if data:
                fn = str(data.get("function") or "unknown").strip()
                args = data.get("arguments") or {}
                if not isinstance(args, dict):
                    args = {}
            else:
                logger.warning(
                    "No function call pattern found in generated output: %s",
                    generated[:200],
                )

        # Confidence shaping based on execution path
        confidence = self.BASE_CONFIDENCE[
            "model_unknown_fn"
        ]  # Default for model output
        error_msg = None

        # Track normalization for observability
        if args_normalized:
            error_msg = "args_normalized"

        # Semantic validation: repair common semantic errors
        if fn and args:
            args, sem_err = self._post_validate_semantics(fn, args, text)
            if sem_err:
                if sem_err.startswith("repaired_"):
                    # Repair succeeded - append to error_msg
                    error_msg = (error_msg or "") + f"|{sem_err}"
                else:
                    # Semantic validation failed
                    confidence = self.BASE_CONFIDENCE["model_schema_invalid"]
                    error_msg = (error_msg or "") + f"|semantic_invalid:{sem_err}"

        if schema_registry:
            schema = None
            try:
                schema = schema_registry.get(fn)
            except Exception:
                schema = None

            if schema:
                try:
                    ok, msg = schema.validate_arguments(args)
                    if ok:
                        confidence = self.BASE_CONFIDENCE["model_schema_valid"]
                    else:
                        confidence = self.BASE_CONFIDENCE["model_schema_invalid"]
                        error_msg = f"schema_validation_failed: {msg}"
                        logger.warning("Schema validation failed for %s: %s", fn, msg)
                except Exception as e:
                    confidence = self.BASE_CONFIDENCE["model_schema_invalid"]
                    error_msg = f"schema_validation_exception: {e}"
            else:
                # Function not in schema
                if fn == "unknown":
                    confidence = self.BASE_CONFIDENCE["unsupported"]
                else:
                    confidence = self.BASE_CONFIDENCE["model_unknown_fn"]
                error_msg = "function_not_in_schema"
        else:
            # No schema registry - use lower confidence
            if fn == "unknown":
                confidence = self.BASE_CONFIDENCE["unsupported"]
            else:
                confidence = self.BASE_CONFIDENCE["model_unknown_fn"]
            error_msg = "no_schema_registry"

        inference_elapsed_ms = _now_ms() - inference_start
        return fn, args, confidence, error_msg, inference_elapsed_ms

    async def compile(
        self,
        text: str,
        context: Optional[Dict[str, Any]] = None,
        schema_registry=None,
    ) -> IntentResult:
        """
        Compile natural language text into a structured function call.
        """
        start = _now_ms()

        # Bound input length
        text = (text or "").strip()
        if len(text) > self.max_input_chars:
            text = text[: self.max_input_chars]

        # Ensure model is loaded (light warmup)
        if not self._model_loaded:
            await self.warmup_light()

        # Lazy heavy warmup (non-blocking, fire-and-forget)
        # This ensures first request returns immediately, but subsequent requests are fast
        if not self._heavy_warmed:
            # Create task but don't await - let it run in background
            asyncio.create_task(self.warmup_heavy())

        # Decide: use model or fallback
        # Check if model is actually loaded and ready
        model_available = (
            self.model is not None
            and (self.processor is not None or self.tokenizer is not None)
            and not self._using_fallback
        )

        # Debug: Log model availability details
        logger.debug(
            "[IntentCompiler] Model availability check: model=%s, processor=%s, tokenizer=%s, _using_fallback=%s, _model_loaded=%s",
            self.model is not None,
            self.processor is not None,
            self.tokenizer is not None,
            self._using_fallback,
            self._model_loaded,
        )

        # Enforce prefer_model_over_fallback policy
        should_use_model = model_available and self.prefer_model_over_fallback

        if not should_use_model:
            # Determine fallback reason for observability
            if not model_available:
                fallback_reason = "model_not_available"
            elif not self.prefer_model_over_fallback:
                fallback_reason = "model_disabled_by_policy"
            else:
                fallback_reason = "unknown"

            logger.info(
                "[IntentCompiler] ⚠️ Using fallback heuristics (reason=%s, model_available=%s, prefer_model=%s, _using_fallback=%s)",
                fallback_reason,
                model_available,
                self.prefer_model_over_fallback,
                self._using_fallback,
            )
            res = self._fallback_compile(text, context, schema_registry)
            res.processing_time_ms = _now_ms() - start
            res.error = fallback_reason
            return res

        # Model is available and policy allows it - use it
        logger.info(
            "[IntentCompiler] 🚀 Using FunctionGemma model for compilation (model_path=%s, prefer_model_over_fallback=%s)",
            self.model_path,
            self.prefer_model_over_fallback,
        )

        # Early semantic guard: fast-fail for unsupported intents before expensive model inference
        text_lower = (text or "").lower()
        if schema_registry:
            # Check for common unsupported intents that would waste CPU time
            unsupported_patterns = {
                "temperature": [
                    "temperature",
                    "thermostat",
                    "heat",
                    "cool",
                    "ac",
                    "hvac",
                ],
                "energy": ["energy", "consumption", "power usage", "electricity"],
            }

            for intent_type, keywords in unsupported_patterns.items():
                if any(kw in text_lower for kw in keywords):
                    # Check if we have a matching schema
                    has_schema = False
                    if intent_type == "temperature":
                        has_schema = (
                            schema_registry.get("device.set_temperature") is not None
                            or schema_registry.get("hvac.set_temperature") is not None
                        )
                    elif intent_type == "energy":
                        has_schema = (
                            schema_registry.get("energy.query") is not None
                            or schema_registry.get("energy.get_consumption") is not None
                        )

                    if not has_schema:
                        logger.debug(
                            "[IntentCompiler] Early exit: unsupported intent '%s' (no matching schema), avoiding expensive inference",
                            intent_type,
                        )
                        # Use unsupported confidence (0.15) to encode execution path
                        return IntentResult(
                            function="unknown",
                            arguments={},
                            confidence=0.15,  # Unsupported intent (early exit)
                            model_version=self.model_version,
                            processing_time_ms=_now_ms() - start,
                            is_fallback=True,
                            error=f"unsupported_intent_{intent_type}",
                        )

        try:
            # 2) Prompt Engineering (FunctionGemma chat template with tools)
            prompt = self._format_prompt(text, schema_registry=schema_registry, context=context)

            # 3) Inference (using extracted core method)
            (
                fn,
                args,
                confidence,
                error_msg,
                inference_elapsed_ms,
            ) = await self._run_model_inference(prompt, schema_registry, text=text)

            # Check latency guard (hard inference budget)
            # Hard budget: configurable, default 12s for CPU inference (more realistic than 8s)
            hard_budget_ms = int(os.getenv("INTENT_HARD_BUDGET_MS", "12000"))
            if inference_elapsed_ms > hard_budget_ms:
                # Only fallback if output is not confidently valid
                if confidence >= self.BASE_CONFIDENCE["model_schema_valid"]:
                    # Keep model output but flag it as slow
                    error_msg = (error_msg or "") + f"|slow_inference:{inference_elapsed_ms}ms"
                    logger.warning(
                        "[IntentCompiler] Inference exceeded hard budget (%dms > %dms) but output is valid, keeping result",
                        inference_elapsed_ms,
                        hard_budget_ms,
                    )
                else:
                    # Invalid output - fallback
                    logger.warning(
                        "[IntentCompiler] Inference exceeded hard budget (%dms > %dms) with invalid output, falling back to heuristics",
                        inference_elapsed_ms,
                        hard_budget_ms,
                    )
                    res = self._fallback_compile(text, context, schema_registry)
                    res.processing_time_ms = _now_ms() - start
                    res.error = f"inference_budget_exceeded: {inference_elapsed_ms}ms > {hard_budget_ms}ms"
                    return res

            # Optional soft latency guard (configurable, disabled by default)
            if (
                self.max_inference_ms > 0
                and inference_elapsed_ms > self.max_inference_ms
            ):
                logger.warning(
                    "[IntentCompiler] Inference exceeded soft latency guard (%dms > %dms), falling back to heuristics",
                    inference_elapsed_ms,
                    self.max_inference_ms,
                )
                res = self._fallback_compile(text, context, schema_registry)
                res.processing_time_ms = _now_ms() - start
                res.error = f"inference_timeout: {inference_elapsed_ms}ms > {self.max_inference_ms}ms"
                return res

            res = IntentResult(
                function=fn,
                arguments=args,
                confidence=_coerce_confidence(confidence),
                model_version=self.model_version,
                processing_time_ms=_now_ms() - start,
                is_fallback=False,
                error=error_msg,
            )
            logger.info(
                "[IntentCompiler] ✅ Model inference complete: function=%s, confidence=%.2f, latency=%.1fms",
                fn,
                confidence,
                res.processing_time_ms,
            )
            return res

        except Exception as e:
            logger.warning("Inference failed, falling back: %s", e)
            res = self._fallback_compile(text, context, schema_registry)
            res.processing_time_ms = _now_ms() - start
            res.error = f"inference_error: {e}"
            return res

    def _fallback_compile(
        self,
        text: str,
        context: Optional[Dict[str, Any]] = None,
        schema_registry=None,
    ) -> IntentResult:
        """
        Fallback compilation using simple heuristics.

        Prefer producing a function that exists in the schema registry (if provided).
        """
        text_lower = (text or "").lower().strip()
        ctx = context or {}

        # Prefer schema-known target functions if possible
        def schema_has(fn: str) -> bool:
            if not schema_registry:
                return False
            try:
                return schema_registry.get(fn) is not None
            except Exception:
                return False

        # Extract an obvious device id if present
        device_id = self._extract_device_id(text, context)

        # Action detection
        is_on = (
            any(
                k in text_lower
                for k in ["turn on", "switch on", "enable", "activate", "on "]
            )
            or text_lower == "on"
        )
        is_off = (
            any(
                k in text_lower
                for k in ["turn off", "switch off", "disable", "deactivate", "off "]
            )
            or text_lower == "off"
        )

        vendor = (ctx.get("vendor") or "").lower()
        wants_tuya = ("tuya" in text_lower) or (vendor == "tuya")

        # If tuya schema exists, prefer it (fallback with schema match)
        if wants_tuya and schema_has("tuya.send_command"):
            if is_on:
                return IntentResult(
                    function="tuya.send_command",
                    arguments={
                        "device_id": device_id or "unknown",
                        "commands": [{"code": "switch_led", "value": True}],
                    },
                    confidence=self.BASE_CONFIDENCE["fallback_schema"],
                    is_fallback=True,
                )
            if is_off:
                return IntentResult(
                    function="tuya.send_command",
                    arguments={
                        "device_id": device_id or "unknown",
                        "commands": [{"code": "switch_led", "value": False}],
                    },
                    confidence=self.BASE_CONFIDENCE["fallback_schema"],
                    is_fallback=True,
                )

        # If you have a generic device control schema, use it (fallback with schema match)
        if schema_has("device.control"):
            if is_on:
                return IntentResult(
                    function="device.control",
                    arguments={"device_id": device_id or "unknown", "action": "on"},
                    confidence=self.BASE_CONFIDENCE["fallback_schema"],
                    is_fallback=True,
                )
            if is_off:
                return IntentResult(
                    function="device.control",
                    arguments={"device_id": device_id or "unknown", "action": "off"},
                    confidence=self.BASE_CONFIDENCE["fallback_schema"],
                    is_fallback=True,
                )

        # Otherwise, best-effort tuya guess if context says tuya (fallback without schema match)
        if wants_tuya:
            return IntentResult(
                function="tuya.send_command",
                arguments={
                    "device_id": device_id or "unknown",
                    "commands": [{"code": "switch_led", "value": True}],
                },
                confidence=self.BASE_CONFIDENCE["fallback_guess"],
                is_fallback=True,
            )

        # Unknown intent: return with unsupported confidence
        return IntentResult(
            function="unknown",
            arguments={},
            confidence=self.BASE_CONFIDENCE["unsupported"],
            is_fallback=True,
            error="intent_not_recognized",
        )

    def _schemas_to_tools(self, schema_registry) -> List[Dict[str, Any]]:
        """
        Convert schema registry to FunctionGemma tools format.
        Matches the format used in training (similar to get_json_schema output).
        """
        if not schema_registry:
            return []

        tools = []
        try:
            schemas = schema_registry.list_all()
            for schema in schemas:
                # Construct tool schema to match FunctionGemma training format
                tool_schema = {
                    "function": {
                        "name": schema.function_name,
                        "description": schema.description,
                        "parameters": {
                            "type": "object",
                            "properties": schema.parameters,
                            "required": schema.required or [],
                        },
                    }
                }
                tools.append(tool_schema)
        except Exception as e:
            logger.warning("Failed to convert schemas to tools format: %s", e)

        return tools

    def _format_prompt(
        self, text: str, schema_registry=None, context: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Format prompt using FunctionGemma chat template with tools.
        This matches the training format and ensures proper function call generation.
        """
        if not self.tokenizer:
            # Fallback to old format if tokenizer not available
            schema_json = "{}"
            context_json = "{}"
            if schema_registry:
                try:
                    schemas = schema_registry.list_all()
                    schema_data = {s.function_name: s.to_dict() for s in schemas}
                    schema_json = json.dumps(schema_data, separators=(",", ":"))
                except Exception:
                    pass
            if context:
                context_json = json.dumps(context, separators=(",", ":"))

            return (
                f"<start_of_turn>user\n"
                f"Convert query to JSON. Rules:\n"
                f"- Output MUST be a single JSON object\n"
                f'- "function" MUST be one of: {list(schema_data.keys()) if schema_registry else "none"}, OR "unknown"\n'
                f"- Do NOT invent function names\n"
                f"- Do NOT include explanations\n"
                f"\nAvailable functions:\n{schema_json}\n"
                f"Context:\n{context_json}\n"
                f"Query: {text}<end_of_turn>\n"
                f"<start_of_turn>model\n"
                f"Output:"
            )

        # Use FunctionGemma chat template with tools
        tools = self._schemas_to_tools(schema_registry) if schema_registry else []

        messages = [
            {
                "role": "developer",
                "content": (
                    "You are an intent compiler.\n"
                    "Convert the user request into exactly ONE function call.\n"
                    "Return ONLY the function call. No extra text.\n"
                    "Arguments MUST be valid JSON (double-quoted keys/strings)."
                ),
            },
            {"role": "user", "content": text},
        ]

        # Add context to user message if provided
        if context:
            context_str = json.dumps(context, separators=(",", ":"))
            messages[-1]["content"] += f"\n\nContext: {context_str}"

        prompt = self.tokenizer.apply_chat_template(
            messages,
            tools=tools,
            tokenize=False,
            add_generation_prompt=True,
        )

        return prompt

    def _extract_device_id(
        self, text: str, context: Optional[Dict[str, Any]]
    ) -> Optional[str]:
        """
        Extract device id from:
        - explicit hex-like token in text (common in your examples)
        - context.device_id
        - context.room_map match
        """
        # 1) Explicit device id token in text
        m = _HEX_DEVICE_RE.search(text or "")
        if m:
            return m.group(0)

        ctx = context or {}

        # 2) direct device_id
        if isinstance(ctx.get("device_id"), str) and ctx.get("device_id"):
            return ctx["device_id"]

        # 3) room_map matching
        room_map = ctx.get("room_map") or {}
        if isinstance(room_map, dict):
            text_lower = (text or "").lower()
            for room_name, dev_id in room_map.items():
                if not isinstance(room_name, str):
                    continue
                if (
                    room_name.lower() in text_lower
                    and isinstance(dev_id, str)
                    and dev_id
                ):
                    return dev_id

        return None

    async def warmup_light(self) -> None:
        """
        Cheap, safe warmup.
        - Loads tokenizer + model weights
        - NO inference
        - Thread-safe with lock protection
        """
        if self._model_loaded:
            return

        if self._warmup_lock is None:
            self._warmup_lock = asyncio.Lock()

        async with self._warmup_lock:
            if self._model_loaded:
                return

            logger.info("[IntentCompiler] 🔥 Starting light warmup (model loading)...")

            # Load model if not already loaded
            if self.model is None and not self._using_fallback:
                await self._load_model()

            # Mark as loaded if model is ready
            if self.model is not None and (self.processor is not None or self.tokenizer is not None):
                self._model_loaded = True
                logger.info(
                    "[IntentCompiler] ✅ Light warmup complete (model_path=%s, device=%s)",
                    self.model_path,
                    getattr(self.model, "device", "cpu"),
                )
            elif self._using_fallback:
                # Fallback mode is also considered "loaded" (no model to load)
                self._model_loaded = True
                logger.info("[IntentCompiler] ✅ Light warmup complete (fallback mode)")
            else:
                logger.warning(
                    "[IntentCompiler] ⚠️ Light warmup incomplete (model=%s, processor=%s, tokenizer=%s)",
                    self.model is not None,
                    self.processor is not None,
                    self.tokenizer is not None,
                )

    async def warmup_heavy(self, sample_texts: Optional[list] = None) -> None:
        """
        Expensive warmup.
        - Runs real inference
        - Triggers kernel compilation, cache, etc.
        - Thread-safe with lock protection
        - Respects warmup mode policy
        """
        # Check warmup mode policy
        mode = get_warmup_mode()
        if mode == WarmupMode.DISABLED:
            logger.debug("[IntentCompiler] Heavy warmup disabled by policy")
            self._heavy_warmed = True  # Mark as done to avoid retry attempts
            return

        if self._heavy_warmed:
            return

        if self._warmup_lock is None:
            self._warmup_lock = asyncio.Lock()

        # Check if model is loaded before acquiring lock (to avoid deadlock)
        # If not loaded, we need to call warmup_light() which has its own lock
        if not self._model_loaded:
            # warmup_light() has its own lock, so we can call it safely
            # It will handle concurrency internally
            await self.warmup_light()

        # Now acquire lock for heavy warmup
        async with self._warmup_lock:
            if self._heavy_warmed:
                return

            logger.info("[IntentCompiler] 🔥 Starting heavy warmup (inference)...")

            # Only run inference if model is actually available
            if (
                self.model is not None
                and (self.processor is not None or self.tokenizer is not None)
                and not self._using_fallback
            ):
                sample_texts = sample_texts or [
                    "turn on the bedroom light",
                ]

                try:
                    # Prepare a simple prompt for warmup (avoid full compile() to prevent recursion)
                    warmup_context = {"domain": "device", "vendor": "tuya"}

                    # Run simplified warmup inference (doesn't require valid JSON)
                    logger.info(
                        "[IntentCompiler] Running heavy warmup inference (%d samples)...",
                        len(sample_texts),
                    )
                    for i, t in enumerate(sample_texts, 1):
                        warmup_prompt = self._format_prompt(
                            t, schema_registry=None, context=warmup_context
                        )
                        try:
                            elapsed = await self._run_warmup_inference(warmup_prompt)
                            logger.debug(
                                "[IntentCompiler] Heavy warmup sample %d/%d: latency=%.1fms",
                                i,
                                len(sample_texts),
                                elapsed,
                            )
                        except Exception as e:
                            # Log but continue - warmup failures are non-fatal
                            logger.debug(
                                "[IntentCompiler] Warmup sample %d/%d failed (non-fatal): %s",
                                i,
                                len(sample_texts),
                                e,
                            )
                    self._heavy_warmed = True
                    logger.info(
                        "✅ Intent compiler heavy warmup complete (model inference ready)"
                    )
                except Exception as e:
                    logger.warning("Heavy warmup failed: %s", e, exc_info=True)
                    # Even if heavy warmup fails, mark as done to avoid retry loops
                    self._heavy_warmed = True
            else:
                # No model available - mark as warmed (nothing to warm)
                self._heavy_warmed = True
                logger.info(
                    "✅ Intent compiler heavy warmup complete (fallback mode, no inference needed)"
                )

    async def warmup(self, sample_texts: Optional[list] = None) -> None:
        """
        Convenience wrapper for backward compatibility.
        Performs full warmup (light + heavy).

        For new code, prefer:
        - warmup_light() for fast startup
        - warmup_heavy() for inference readiness
        """
        await self.warmup_light()
        await self.warmup_heavy(sample_texts=sample_texts)
        self._warmed_up = True  # Legacy flag

    def get_warmup_status(self) -> Dict[str, Any]:
        """
        Get warmup status for observability.

        Returns:
            Dict with model_loaded, heavy_warmed, using_fallback flags
        """
        return {
            "model_loaded": self._model_loaded,
            "heavy_warmed": self._heavy_warmed,
            "using_fallback": self._using_fallback,
            "warmup_mode": get_warmup_mode().value,
        }

    def get_performance_stats(self) -> Dict[str, Any]:
        """Get performance and diagnostic stats for observability."""
        warmup_status = self.get_warmup_status()
        return {
            "model_loaded": self.model is not None,
            "warmed_up": self._warmed_up,  # Legacy flag
            "warmup_status": warmup_status,  # New structured warmup status
            "using_fallback": self._using_fallback,
            "load_mode": self._load_mode,  # offline_cache | hub_download | fallback
            "load_error": self._load_error,
            "model_path": self.model_path,
            "model_version": self.model_version,
            "cache_root": HF_CACHE_ROOT,
            "max_new_tokens": self.max_new_tokens,
            "max_schema_chars": self.max_schema_chars,
            "max_context_chars": self.max_context_chars,
            "max_input_chars": self.max_input_chars,
        }

    def get_memory_usage_mb(self) -> Optional[float]:
        """
        Get memory usage in MB for health checks.
        - If CUDA: report torch.cuda.memory_allocated()
        - Else: try psutil RSS (optional)
        """
        if not FUNCTIONGEMMA_AVAILABLE or self.model is None or torch is None:
            return None

        try:
            if torch.cuda.is_available():
                return torch.cuda.memory_allocated() / (1024 * 1024)
        except Exception:
            pass

        try:
            import psutil  # optional dependency  # pyright: ignore[reportMissingModuleSource]

            process = psutil.Process()
            return process.memory_info().rss / (1024 * 1024)
        except Exception:
            return None

    @property
    def is_ready(self) -> bool:
        """Ready if model loaded OR fallback mode is available."""
        return self.model is not None or self._using_fallback


# Singleton instance
_intent_compiler: Optional[IntentCompiler] = None


def get_intent_compiler(
    model_path: Optional[str] = None, lora_path: Optional[str] = None
) -> IntentCompiler:
    global _intent_compiler
    if _intent_compiler is None:
        _intent_compiler = IntentCompiler(model_path=model_path, lora_path=lora_path)
    return _intent_compiler
