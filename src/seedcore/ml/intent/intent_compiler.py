"""
Intent Compiler Module for SeedCore

Provides deterministic natural-language → structured function call translation
using FunctionGemma as a low-latency intent compiler.

This is NOT a conversational LLM or tool executor. It's a pure inference service
that converts user text into validated function calls.
"""

from __future__ import annotations

import os
import logging
import time
import asyncio
import json
import re
from typing import Dict, Any, Optional, List
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# FunctionGemma/Transformers imports
try:
    import torch  # pyright: ignore[reportMissingImports]
    from transformers import AutoTokenizer, AutoModelForCausalLM, BitsAndBytesConfig  # pyright: ignore[reportMissingImports]
    from peft import PeftModel  # pyright: ignore[reportMissingImports]
    FUNCTIONGEMMA_AVAILABLE = True
except ImportError:
    FUNCTIONGEMMA_AVAILABLE = False
    torch = None  # type: ignore


# ----------------------------
# Helpers
# ----------------------------

_JSON_OBJ_RE = re.compile(r"\{(?:[^{}]|(?R))*\}", re.DOTALL)  # recursive-ish JSON object match (best effort)
_HEX_DEVICE_RE = re.compile(r"\b[a-fA-F0-9]{16,64}\b")


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
        m = _JSON_OBJ_RE.search(cand)
        if not m:
            continue
        blob = m.group(0)
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
        }


class IntentCompiler:
    """
    Intent Compilation Service (FunctionGemma-backed)

    Converts natural language into structured function calls.
    No side effects. No tool execution. Pure inference.
    """

    def __init__(self, model_path: Optional[str] = None, lora_path: Optional[str] = None):
        self.model_path = model_path or os.getenv("SEEDCORE_FUNCTIONGEMMA_MODEL_PATH")
        self.lora_path = lora_path or os.getenv("SEEDCORE_FUNCTIONGEMMA_LORA_PATH")

        self.model = None
        self.tokenizer = None

        self._warmed_up = False
        self.model_version = os.getenv("SEEDCORE_FUNCTIONGEMMA_VERSION", "1.0.0")

        # Prompt controls
        self.max_schema_chars = int(os.getenv("SEEDCORE_INTENT_MAX_SCHEMA_CHARS", "8000"))
        self.max_context_chars = int(os.getenv("SEEDCORE_INTENT_MAX_CONTEXT_CHARS", "2000"))
        self.max_input_chars = int(os.getenv("SEEDCORE_INTENT_MAX_INPUT_CHARS", "512"))

        # Generation controls (keep deterministic)
        self.max_new_tokens = int(os.getenv("SEEDCORE_INTENT_MAX_NEW_TOKENS", "128"))

        # Lazy init + concurrency guard
        self._loading_lock: Optional[asyncio.Lock] = None
        self._using_fallback = not FUNCTIONGEMMA_AVAILABLE

        if not FUNCTIONGEMMA_AVAILABLE:
            logger.warning("FunctionGemma deps not available. Intent compiler will use fallback mode.")

    async def _load_model(self) -> None:
        """
        Load FunctionGemma model/tokenizer (lazy, lock-protected).

        Notes:
        - 4-bit NF4 typically requires bitsandbytes + CUDA. If CUDA is not available,
          we fall back to standard loading (fp16/bf16/float32).
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
                logger.warning("No model path configured (SEEDCORE_FUNCTIONGEMMA_MODEL_PATH). Using fallback.")
                self._using_fallback = True
                return

            try:
                logger.info("🚀 Loading FunctionGemma from %s ...", self.model_path)

                # Tokenizer first (fast + helpful error early)
                self.tokenizer = AutoTokenizer.from_pretrained(self.model_path, trust_remote_code=True)
                # Make sure padding works for generate()
                if self.tokenizer.pad_token is None:
                    self.tokenizer.pad_token = self.tokenizer.eos_token
                self.tokenizer.padding_side = "left"

                use_cuda = bool(torch and torch.cuda.is_available())
                dtype = torch.float16 if use_cuda else (torch.bfloat16 if hasattr(torch, "bfloat16") else torch.float32)

                # Prefer 4-bit only if CUDA is available (common practical constraint)
                quantization_config = None
                if use_cuda:
                    try:
                        quantization_config = BitsAndBytesConfig(
                            load_in_4bit=True,
                            bnb_4bit_quant_type="nf4",
                            bnb_4bit_compute_dtype=torch.float16,
                            bnb_4bit_use_double_quant=True,
                        )
                        logger.info("Using 4-bit NF4 quantization (CUDA).")
                    except Exception as e:
                        logger.warning("BitsAndBytesConfig unavailable; falling back to non-quantized load: %s", e)

                base_model = AutoModelForCausalLM.from_pretrained(
                    self.model_path,
                    quantization_config=quantization_config,
                    torch_dtype=None if quantization_config else dtype,
                    device_map="auto" if use_cuda else None,
                    low_cpu_mem_usage=True,
                    trust_remote_code=True,
                )

                # LoRA adapter (optional)
                if self.lora_path and os.path.exists(self.lora_path):
                    logger.info("Applying LoRA adapter from %s", self.lora_path)
                    self.model = PeftModel.from_pretrained(base_model, self.lora_path)
                else:
                    self.model = base_model

                self.model.eval()
                logger.info("✅ FunctionGemma loaded successfully. device=%s", getattr(self.model, "device", "unknown"))

            except Exception as e:
                logger.error("Failed to load FunctionGemma model: %s", e, exc_info=True)
                self.model = None
                self.tokenizer = None
                self._using_fallback = True

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

        # Lazy load
        if self.model is None and not self._using_fallback:
            await self._load_model()

        if self._using_fallback or self.model is None or self.tokenizer is None:
            res = self._fallback_compile(text, context, schema_registry)
            res.processing_time_ms = _now_ms() - start
            return res

        try:
            # 1) Schema snapshot (bounded)
            schema_data: Dict[str, Any] = {}
            if schema_registry:
                try:
                    schemas = schema_registry.list_all()
                    schema_data = {s.function_name: s.to_dict() for s in schemas}
                except Exception as e:
                    logger.warning("Schema registry list_all failed: %s", e)
                    schema_data = {}

            schema_str = _safe_dumps(schema_data, self.max_schema_chars)

            # 2) Context snapshot (bounded)
            ctx = context or {}
            context_str = _safe_dumps(ctx, self.max_context_chars)

            # 3) Prompt
            prompt = self._format_prompt(text=text, schema_json=schema_str, context_json=context_str)

            # 4) Tokenize
            inputs = self.tokenizer(prompt, return_tensors="pt", padding=True)
            # Move tensors to model device if possible
            if hasattr(self.model, "device"):
                try:
                    inputs = {k: v.to(self.model.device) for k, v in inputs.items()}
                except Exception:
                    pass

            # 5) Inference (deterministic)
            with torch.inference_mode():
                outputs = self.model.generate(
                    **inputs,
                    max_new_tokens=self.max_new_tokens,
                    do_sample=False,
                    temperature=0.0,
                    num_beams=1,
                    eos_token_id=self.tokenizer.eos_token_id,
                    pad_token_id=self.tokenizer.pad_token_id,
                )

            decoded = self.tokenizer.decode(outputs[0], skip_special_tokens=True)
            data = _extract_first_json_obj(decoded)

            if not data:
                raise ValueError("No JSON found in model output")

            fn = str(data.get("function") or "unknown").strip()
            args = data.get("arguments") or {}
            if not isinstance(args, dict):
                args = {}

            # 6) Validation + confidence shaping
            confidence = 0.92  # base for model path (no logprobs)
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
                            confidence = 0.97
                        else:
                            confidence = 0.70
                            error_msg = f"schema_validation_failed: {msg}"
                            logger.warning("Schema validation failed for %s: %s", fn, msg)
                    except Exception as e:
                        confidence = 0.75
                        error_msg = f"schema_validation_exception: {e}"
                else:
                    # function not in schema => lower confidence
                    confidence = 0.60
                    error_msg = "function_not_in_schema"

            res = IntentResult(
                function=fn,
                arguments=args,
                confidence=_coerce_confidence(confidence),
                model_version=self.model_version,
                processing_time_ms=_now_ms() - start,
                is_fallback=False,
                error=error_msg,
            )
            return res

        except Exception as e:
            logger.error("Intent inference error: %s", e, exc_info=True)
            res = self._fallback_compile(text, context, schema_registry)
            res.processing_time_ms = _now_ms() - start
            res.error = f"model_error: {e}"
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
        is_on = any(k in text_lower for k in ["turn on", "switch on", "enable", "activate", "on "]) or text_lower == "on"
        is_off = any(k in text_lower for k in ["turn off", "switch off", "disable", "deactivate", "off "]) or text_lower == "off"

        vendor = (ctx.get("vendor") or "").lower()
        wants_tuya = ("tuya" in text_lower) or (vendor == "tuya")

        # If tuya schema exists, prefer it
        if wants_tuya and schema_has("tuya.send_command"):
            if is_on:
                return IntentResult(
                    function="tuya.send_command",
                    arguments={"device_id": device_id or "unknown", "commands": [{"code": "switch_led", "value": True}]},
                    confidence=0.55,
                    is_fallback=True,
                )
            if is_off:
                return IntentResult(
                    function="tuya.send_command",
                    arguments={"device_id": device_id or "unknown", "commands": [{"code": "switch_led", "value": False}]},
                    confidence=0.55,
                    is_fallback=True,
                )

        # If you have a generic device control schema, use it
        if schema_has("device.control"):
            if is_on:
                return IntentResult(
                    function="device.control",
                    arguments={"device_id": device_id or "unknown", "action": "on"},
                    confidence=0.60,
                    is_fallback=True,
                )
            if is_off:
                return IntentResult(
                    function="device.control",
                    arguments={"device_id": device_id or "unknown", "action": "off"},
                    confidence=0.60,
                    is_fallback=True,
                )

        # Otherwise, best-effort tuya guess if context says tuya
        if wants_tuya:
            return IntentResult(
                function="tuya.send_command",
                arguments={"device_id": device_id or "unknown", "commands": [{"code": "switch_led", "value": True}]},
                confidence=0.45,
                is_fallback=True,
            )

        return IntentResult(function="unknown", arguments={}, confidence=0.0, is_fallback=True)

    def _format_prompt(self, text: str, schema_json: str, context_json: str) -> str:
        """
        Format prompt for "Compilation Mode".

        Key ideas:
        - strictly request JSON only
        - include bounded schema + bounded context
        - explicitly forbid explanations
        """
        return (
            "You are an intent compiler. Convert the user query into a single JSON object.\n"
            "Rules:\n"
            "1) Output ONLY valid JSON (no markdown, no commentary).\n"
            "2) JSON must have keys: function (string), arguments (object).\n"
            "3) Choose function from Available Functions when possible.\n"
            "4) Do NOT add extra keys.\n\n"
            f"Available Functions:\n{schema_json}\n\n"
            f"Context:\n{context_json}\n\n"
            f"User Query: {text}\n\n"
            "Output:"
        )

    def _extract_device_id(self, text: str, context: Optional[Dict[str, Any]]) -> Optional[str]:
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
                if room_name.lower() in text_lower and isinstance(dev_id, str) and dev_id:
                    return dev_id

        return None

    async def warmup(self, sample_texts: Optional[list] = None) -> None:
        """
        Warm up the model to avoid cold start latency.

        ✅ TODO completed:
        - if model isn’t loaded, load it first (lazy)
        - run a minimal deterministic compile for a few samples
        - mark warmed_up even in fallback mode (it’s still “ready”)
        """
        if self._warmed_up:
            return

        # Ensure model attempts to load (unless fallback)
        if self.model is None and not self._using_fallback:
            await self._load_model()

        sample_texts = sample_texts or [
            "turn on bf1234567890abcdef",
            "turn off bf1234567890abcdef",
            "turn on the bedroom light",
        ]

        try:
            # Run a few compiles; keep context minimal
            for t in sample_texts:
                _ = await self.compile(t, context={"domain": "device", "vendor": "tuya"})
            self._warmed_up = True
            logger.info("✅ Intent compiler warmed up (fallback=%s)", self._using_fallback)
        except Exception as e:
            logger.warning("Warmup failed: %s", e, exc_info=True)
            # Even if warmup fails, don’t block service readiness
            self._warmed_up = True

    def get_performance_stats(self) -> Dict[str, Any]:
        return {
            "model_loaded": self.model is not None,
            "warmed_up": self._warmed_up,
            "model_version": self.model_version,
            "using_fallback": self._using_fallback,
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
            import psutil  # optional dependency
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


def get_intent_compiler(model_path: Optional[str] = None, lora_path: Optional[str] = None) -> IntentCompiler:
    global _intent_compiler
    if _intent_compiler is None:
        _intent_compiler = IntentCompiler(model_path=model_path, lora_path=lora_path)
    return _intent_compiler
