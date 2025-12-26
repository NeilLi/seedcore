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
    from transformers import AutoProcessor, AutoModelForCausalLM, BitsAndBytesConfig  # pyright: ignore[reportMissingImports]
    from peft import PeftModel  # pyright: ignore[reportMissingImports]

    FUNCTIONGEMMA_AVAILABLE = True
except ImportError:
    FUNCTIONGEMMA_AVAILABLE = False
    torch = None  # type: ignore


# ----------------------------
# Helpers
# ----------------------------

_HEX_DEVICE_RE = re.compile(r"\b[a-fA-F0-9]{16,64}\b")


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

                # 1. Load Processor (Offline-First Strategy)
                # Try local cache first to avoid network/DNS issues in Kind clusters
                try:
                    self.processor = AutoProcessor.from_pretrained(
                        self.model_path,
                        local_files_only=True,  # Try local cache first
                        trust_remote_code=True,
                    )
                    self._load_mode = "offline_cache"
                    logger.info("✅ Processor loaded from local cache")
                except Exception:
                    # Fallback to network download with token
                    logger.info("Local cache miss, attempting Hub download...")
                    self.processor = AutoProcessor.from_pretrained(
                        self.model_path,
                        token=hf_token,
                        trust_remote_code=True,
                    )
                    self._load_mode = "hub_download"
                    logger.info("✅ Processor downloaded from Hugging Face Hub")

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

    async def _run_model_inference(
        self,
        prompt: str,
        schema_registry=None,
    ) -> tuple[str, Dict[str, Any], float, Optional[str], float]:
        """
        Core model inference logic (extracted from compile to avoid recursion).

        Returns:
            (function_name, arguments, confidence, error_msg, inference_elapsed_ms)
        """
        inference_start = _now_ms()

        # Process prompt
        inputs = self.processor(prompt, return_tensors="pt")
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

            outputs = self.model.generate(
                **inputs,
                max_new_tokens=self.max_new_tokens,
                do_sample=False,  # Pure determinism
                temperature=0.0,
                pad_token_id=pad_token_id,
            )

        # Decode safely (processor may be the tokenizer itself for Gemma)
        if hasattr(self.processor, "tokenizer") and hasattr(
            self.processor.tokenizer, "decode"
        ):
            decoded = self.processor.tokenizer.decode(
                outputs[0], skip_special_tokens=True
            )
        elif hasattr(self.processor, "decode"):
            decoded = self.processor.decode(outputs[0], skip_special_tokens=True)
        else:
            raise ValueError("Processor does not have decode method")

        data = _extract_first_json_obj(decoded)
        if not data:
            raise ValueError("Model output did not contain a valid JSON object")

        fn = str(data.get("function") or "unknown").strip()
        args = data.get("arguments") or {}
        if not isinstance(args, dict):
            args = {}

        # Confidence shaping based on execution path
        confidence = self.BASE_CONFIDENCE[
            "model_unknown_fn"
        ]  # Default for model output
        error_msg = None

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
            and self.processor is not None
            and not self._using_fallback
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
            # 1) Context & Schema preparation
            schema_data: Dict[str, Any] = {}
            if schema_registry:
                try:
                    schemas = schema_registry.list_all()
                    schema_data = {s.function_name: s.to_dict() for s in schemas}
                except Exception as e:
                    logger.warning("Schema registry list_all failed: %s", e)
                    schema_data = {}

            schema_str = _safe_dumps(schema_data, self.max_schema_chars)
            context_str = _safe_dumps(context or {}, self.max_context_chars)

            # 2) Prompt Engineering (Strict for FunctionGemma IT)
            prompt = self._format_prompt(text, schema_str, context_str)

            # 3) Inference (using extracted core method)
            (
                fn,
                args,
                confidence,
                error_msg,
                inference_elapsed_ms,
            ) = await self._run_model_inference(prompt, schema_registry)

            # Check latency guard (hard inference budget)
            # Hard budget: 8 seconds for CPU inference (p95 is ~8-9s, this prevents p99 timeouts)
            hard_budget_ms = 8000
            if inference_elapsed_ms > hard_budget_ms:
                logger.warning(
                    "[IntentCompiler] Inference exceeded hard budget (%dms > %dms), falling back to heuristics",
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

    def _format_prompt(self, text: str, schema_json: str, context_json: str) -> str:
        """
        Gemma-2 IT specific prompt format to force JSON output.
        Uses <start_of_turn>/<end_of_turn> tags for proper instruction formatting.

        Hardened prompt to prevent hallucinated function names.
        """
        # Extract function names from schema for explicit whitelist
        function_names = []
        try:
            schema_data = json.loads(schema_json)
            function_names = list(schema_data.keys())
        except Exception:
            pass

        function_list = ", ".join(function_names) if function_names else "none"

        return (
            f"<start_of_turn>user\n"
            f"Convert query to JSON. Rules:\n"
            f"- Output MUST be a single JSON object\n"
            f'- "function" MUST be one of: {function_list}, OR "unknown"\n'
            f"- Do NOT invent function names\n"
            f"- Do NOT include explanations\n"
            f"\nAvailable functions:\n{schema_json}\n"
            f"Context:\n{context_json}\n"
            f"Query: {text}<end_of_turn>\n"
            f"<start_of_turn>model\n"
            f"Output:"
        )

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
            if self.model is not None and self.processor is not None:
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
                    "[IntentCompiler] ⚠️ Light warmup incomplete (model=%s, processor=%s)",
                    self.model is not None,
                    self.processor is not None,
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
                and self.processor is not None
                and not self._using_fallback
            ):
                sample_texts = sample_texts or [
                    "turn on the bedroom light",
                ]

                try:
                    # Prepare a simple prompt for warmup (avoid full compile() to prevent recursion)
                    schema_str = "{}"  # Empty schema for warmup
                    context_str = '{"domain":"device","vendor":"tuya"}'
                    warmup_text = sample_texts[0]
                    self._format_prompt(warmup_text, schema_str, context_str)

                    # Run inference directly (not via compile to avoid recursion)
                    logger.info(
                        "[IntentCompiler] Running heavy warmup inference (%d samples)...",
                        len(sample_texts),
                    )
                    for i, t in enumerate(sample_texts, 1):
                        warmup_prompt = self._format_prompt(t, schema_str, context_str)
                        fn, args, conf, err, elapsed = await self._run_model_inference(
                            warmup_prompt, schema_registry=None
                        )
                        logger.debug(
                            "[IntentCompiler] Heavy warmup sample %d/%d: function=%s, confidence=%.2f, latency=%.1fms",
                            i,
                            len(sample_texts),
                            fn,
                            conf,
                            elapsed,
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
