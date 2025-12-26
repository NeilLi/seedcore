#!/usr/bin/env python3
"""
Verification script for MLServiceClient intent compilation endpoints.

Verifies:
  - get_intent_schema: retrieving schemas (all, by domain, by function name)
  - compile_intent: compiling text into structured function calls

Usage:
    python scripts/verify_intent_compilation.py
Options:
    --base-url http://127.0.0.1:8000/ml
    --timeout 20
    --strict
    --parallel 4
    --runs 2
"""

from __future__ import annotations

import os
import sys
import json
import time
import argparse
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import anyio  # pyright: ignore[reportMissingImports]
import logging


# -----------------------------
# Path + logging
# -----------------------------
src_path = Path(__file__).parent.parent / "src"
sys.path.insert(0, str(src_path))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
    force=True,
)
logger = logging.getLogger(__name__)


# -----------------------------
# Helpers
# -----------------------------
def _pretty(obj: Any) -> str:
    try:
        return json.dumps(obj, indent=2, ensure_ascii=False)
    except Exception:
        return str(obj)


def _print_header(title: str) -> None:
    print("\n" + "=" * 20 + f" {title} " + "=" * 20)


def _infer_execution_path(result: dict) -> str:
    diag = result.get("diagnostics") or {}
    return "MODEL_INFERENCE" if diag.get("used_model") is True else "FALLBACK_HEURISTIC"


def _get_server_latency_ms(result: dict) -> Optional[float]:
    v = result.get("processing_time_ms")
    try:
        return float(v) if v is not None else None
    except Exception:
        return None


def _get_confidence(result: dict) -> Optional[float]:
    v = result.get("confidence")
    try:
        return float(v) if v is not None else None
    except Exception:
        return None


def _ok_result_shape(result: Any) -> bool:
    return isinstance(result, dict) and ("ok" in result or "function" in result)


async def _call_timed(awaitable) -> Tuple[Any, float]:
    t0 = time.perf_counter()
    try:
        out = await awaitable
        return out, time.perf_counter() - t0
    except Exception as e:
        return e, time.perf_counter() - t0


def _soft_assert(condition: bool, msg: str, failures: List[str], strict: bool) -> None:
    if condition:
        return
    if strict:
        failures.append(msg)
        logger.error("❌ %s", msg)
    else:
        logger.warning("⚠️  %s", msg)


def _pick_example_function(schemas: List[dict], domain: Optional[str] = None) -> Optional[Tuple[str, Optional[str]]]:
    """
    Pick a function_name (and its domain) from schemas list.
    Prefer a given domain if provided.
    """
    if not schemas:
        return None

    if domain:
        for s in schemas:
            if (s.get("domain") or "").lower() == domain.lower() and s.get("function_name"):
                return s["function_name"], s.get("domain")
    # fallback: first with function_name
    for s in schemas:
        if s.get("function_name"):
            return s["function_name"], s.get("domain")
    return None


def _schema_index(schemas: List[dict]) -> Dict[str, dict]:
    out: Dict[str, dict] = {}
    for s in schemas:
        fn = s.get("function_name")
        if isinstance(fn, str) and fn:
            out[fn] = s
    return out


def _extract_diag_flags(result: dict) -> List[str]:
    """
    Useful for your current logs / new pipeline:
    - args_normalized flag (if you add it)
    - slow_inference flag (if you add it)
    """
    flags = []
    err = (result.get("error") or "")
    if isinstance(err, str):
        if "args_normalized" in err:
            flags.append("args_normalized")
        if "slow_inference" in err or "inference_budget_exceeded" in err:
            flags.append("slow_or_budget")
    return flags


# -----------------------------
# Verifiers
# -----------------------------
async def verify_service_health(client) -> bool:
    _print_header("SERVICE HEALTH CHECK")
    try:
        health, dt = await _call_timed(client.health())
        if isinstance(health, Exception):
            logger.error("❌ Health check failed in %.2fs: %s", dt, health)
            logger.error(traceback.format_exc())
            return False
        logger.info("Health status: %s (%.2fs)", health.get("status", "unknown"), dt)
        if health.get("status") == "healthy":
            logger.info("✅ Service is healthy")
            return True
        logger.warning("⚠️  Service health is not 'healthy'")
        return False
    except Exception as e:
        logger.error("❌ Health check exception: %s", e)
        logger.error(traceback.format_exc())
        return False


async def fetch_all_schemas(client) -> Tuple[Optional[List[dict]], List[str]]:
    failures: List[str] = []
    _print_header("FETCH SCHEMAS (ONCE)")

    result, dt = await _call_timed(client.get_intent_schema())
    if isinstance(result, Exception):
        logger.error("❌ get_intent_schema failed in %.2fs: %s", dt, result)
        failures.append("get_intent_schema (all) failed")
        return None, failures

    if not isinstance(result, dict):
        logger.error("❌ get_intent_schema returned non-dict: %r", type(result))
        failures.append("get_intent_schema (all) returned non-dict")
        return None, failures

    schemas = result.get("schemas")
    if not isinstance(schemas, list):
        logger.error("❌ get_intent_schema missing 'schemas' list. keys=%s", list(result.keys()))
        failures.append("get_intent_schema missing schemas")
        return None, failures

    logger.info("✅ get_intent_schema success in %.2fs; schemas=%d", dt, len(schemas))
    return schemas, failures


async def verify_get_intent_schema(client, schemas: List[dict], strict: bool) -> List[str]:
    failures: List[str] = []
    _print_header("GET_INTENT_SCHEMA TESTS")

    # Test 1: Basic sanity on cached schemas
    logger.info("Test 1: Cached schemas sanity")
    _soft_assert(len(schemas) > 0, "No schemas returned (schemas list is empty)", failures, strict)

    fn_pick = _pick_example_function(schemas, domain="device") or _pick_example_function(schemas)
    _soft_assert(fn_pick is not None, "Could not find any function_name in schemas", failures, strict)

    # Test 2: Filter by domain
    logger.info("Test 2: Get schemas filtered by domain='device'")
    result, dt = await _call_timed(client.get_intent_schema(domain="device"))
    if isinstance(result, Exception):
        logger.error("❌ Failed in %.2fs: %s", dt, result)
        failures.append("get_intent_schema (domain=device) failed")
    else:
        n = len(result.get("schemas", [])) if isinstance(result, dict) else -1
        logger.info("✅ Success in %.2fs; schemas=%s", dt, n)

    # Test 3: Filter by function_name
    if fn_pick:
        fn, dom = fn_pick
        logger.info("Test 3: Get schema for function_name=%s", fn)
        result, dt = await _call_timed(client.get_intent_schema(function_name=fn))
        if isinstance(result, Exception):
            logger.error("❌ Failed in %.2fs: %s", dt, result)
            failures.append("get_intent_schema (by function_name) failed")
        else:
            logger.info("✅ Success in %.2fs", dt)

        # Test 4: Combined filters (domain + function_name)
        if dom:
            logger.info("Test 4: Get schema with domain=%s and function_name=%s", dom, fn)
            result, dt = await _call_timed(client.get_intent_schema(domain=dom, function_name=fn))
            if isinstance(result, Exception):
                logger.error("❌ Failed in %.2fs: %s", dt, result)
                failures.append("get_intent_schema (combined) failed")
            else:
                logger.info("✅ Success in %.2fs", dt)

    return failures


async def _run_compile_case(
    client,
    case: dict,
    strict: bool,
    schema_by_fn: Dict[str, dict],
) -> Tuple[List[str], Dict[str, Any]]:
    """
    Runs one compile test case once and returns:
      - failures
      - metrics for summary
    """
    failures: List[str] = []
    text = case["text"]
    context = case.get("context")
    expect_model = case.get("expect_model")
    expect_fn_prefix = case.get("expect_fn_prefix")

    result, dt = await _call_timed(client.compile_intent(text=text, context=context))
    metrics: Dict[str, Any] = {
        "name": case.get("name"),
        "client_rtt_s": dt,
        "server_ms": None,
        "path": None,
        "function": None,
        "confidence": None,
        "flags": [],
        "ok": False,
    }

    if isinstance(result, Exception):
        logger.error("❌ compile_intent failed in %.2fs: %s", dt, result)
        failures.append(f"compile_intent ({case['name']}) failed")
        return failures, metrics

    if not isinstance(result, dict):
        failures.append(f"compile_intent ({case['name']}) returned non-dict")
        return failures, metrics

    metrics["ok"] = True
    metrics["server_ms"] = _get_server_latency_ms(result)
    metrics["confidence"] = _get_confidence(result)
    metrics["path"] = _infer_execution_path(result)
    metrics["flags"] = _extract_diag_flags(result)

    fn = result.get("function")
    metrics["function"] = fn

    diagnostics = result.get("diagnostics", {}) if isinstance(result.get("diagnostics"), dict) else {}
    used_model = diagnostics.get("used_model", False)

    logger.info("✅ %s in %.2fs (server=%sms) path=%s used_model=%s conf=%s fn=%s flags=%s",
                case["name"],
                dt,
                metrics["server_ms"],
                metrics["path"],
                used_model,
                metrics["confidence"],
                fn,
                ",".join(metrics["flags"]) if metrics["flags"] else "-",
    )

    # Expectation checks (soft by default unless --strict)
    if expect_model is not None:
        _soft_assert(
            bool(used_model) == bool(expect_model),
            f"{case['name']}: expected used_model={expect_model} got {used_model}",
            failures,
            strict,
        )

    if expect_fn_prefix and isinstance(fn, str):
        _soft_assert(
            fn.startswith(expect_fn_prefix),
            f"{case['name']}: expected function prefix '{expect_fn_prefix}' got '{fn}'",
            failures,
            strict,
        )

    # If function exists in schema, optionally validate required keys presence (very light check)
    if isinstance(fn, str) and fn in schema_by_fn:
        args = result.get("arguments", {})
        if isinstance(args, dict):
            required = schema_by_fn[fn].get("required") or []
            if isinstance(required, list) and required:
                missing = [k for k in required if k not in args]
                _soft_assert(
                    not missing,
                    f"{case['name']}: missing required args for {fn}: {missing}",
                    failures,
                    strict,
                )

    return failures, metrics


async def verify_compile_intent(
    client,
    schemas: List[dict],
    strict: bool,
    runs: int,
    parallel: int,
) -> List[str]:
    failures: List[str] = []
    _print_header("COMPILE_INTENT TESTS")

    schema_by_fn = _schema_index(schemas)

    # Warmup (helps stabilize latency)
    logger.info("Warmup: running one compile_intent to prime model/caches...")
    _ = await _call_timed(client.compile_intent(text="turn on the bedroom light", context={"domain": "device"}))

    test_cases = [
        {
            "name": "Simple device control",
            "text": "turn on the bedroom light",
            "context": {"domain": "device", "room": "bedroom", "device_id": "eisp7pij1tkyzhiw"},
            "expect_model": True,
        },
        {
            "name": "Temperature adjustment (expected early-exit if no schema)",
            "text": "set the temperature to 72 degrees",
            "context": {"domain": "device", "room": "living_room", "device_id": "eisp7pij1tkyzhiw"},
            "expect_model": False,
        },
        {
            "name": "Energy query (expected early-exit if no schema)",
            "text": "what is the current energy consumption",
            "context": {"domain": "energy"},
            "expect_model": False,
        },
        {
            "name": "Multiple devices phrasing",
            "text": "turn off all lights in the kitchen",
            "context": {"domain": "device", "room": "kitchen", "device_id": "eisp7pij1tkyzhiw"},
            "expect_model": True,
        },
        {
            "name": "No context",
            "text": "turn on the lights",
            "context": None,
            "expect_model": True,
        },
    ]

    # Run cases N times to catch cold vs warm + tail latency
    all_metrics: List[Dict[str, Any]] = []

    async def run_one(case: dict) -> None:
        nonlocal failures, all_metrics
        for r in range(1, runs + 1):
            case_name = f"{case['name']} [run {r}/{runs}]"
            case_run = dict(case)
            case_run["name"] = case_name
            f, m = await _run_compile_case(client, case_run, strict, schema_by_fn)
            failures.extend(f)
            all_metrics.append(m)

    if parallel and parallel > 1:
        logger.info("Running compile cases with parallel=%d", parallel)
        # simple bounded concurrency
        sem = anyio.Semaphore(parallel)

        async def run_one_bounded(case: dict) -> None:
            async with sem:
                await run_one(case)

        async with anyio.create_task_group() as tg:
            for c in test_cases:
                tg.start_soon(run_one_bounded, c)
    else:
        for c in test_cases:
            await run_one(c)

    # Summary metrics
    _print_header("COMPILE SUMMARY")
    ok_metrics = [m for m in all_metrics if m.get("ok")]
    if ok_metrics:
        rtts = sorted([m["client_rtt_s"] for m in ok_metrics if isinstance(m.get("client_rtt_s"), (int, float))])
        srv = sorted([m["server_ms"] for m in ok_metrics if isinstance(m.get("server_ms"), (int, float))])

        def pct(xs, p):
            if not xs:
                return None
            idx = int(round((p / 100.0) * (len(xs) - 1)))
            return xs[max(0, min(len(xs) - 1, idx))]

        logger.info("Client RTT: p50=%.2fs p95=%.2fs max=%.2fs",
                    pct(rtts, 50) or 0.0, pct(rtts, 95) or 0.0, (rtts[-1] if rtts else 0.0))
        if srv:
            logger.info("Server time: p50=%.0fms p95=%.0fms max=%.0fms",
                        pct(srv, 50) or 0.0, pct(srv, 95) or 0.0, (srv[-1] if srv else 0.0))

        path_counts: Dict[str, int] = {}
        for m in ok_metrics:
            path_counts[m.get("path") or "UNKNOWN"] = path_counts.get(m.get("path") or "UNKNOWN", 0) + 1
        logger.info("Execution paths: %s", path_counts)

        flagged = [m for m in ok_metrics if m.get("flags")]
        if flagged:
            logger.warning("Flagged responses (%d):", len(flagged))
            for m in flagged[:10]:
                logger.warning("  - %s flags=%s fn=%s rtt=%.2fs server=%sms",
                               m.get("name"), ",".join(m.get("flags", [])), m.get("function"),
                               m.get("client_rtt_s", 0.0), m.get("server_ms"))
    else:
        logger.warning("No successful compile responses to summarize.")

    return failures


# -----------------------------
# Orchestration
# -----------------------------
async def run_verification(args) -> int:
    logger.info("🚀 Starting intent compilation verification...")

    _print_header("CLIENT INITIALIZATION")
    try:
        from seedcore.serve.ml_client import MLServiceClient

        base_url = args.base_url
        if not base_url:
            try:
                from seedcore.utils.ray_utils import ML
                base_url = ML
                logger.info("Using ML service URL from ray_utils: %s", base_url)
            except Exception:
                base_url = os.getenv("MLS_BASE_URL", "http://127.0.0.1:8000/ml")
                logger.info("Using ML service URL: %s", base_url)

        client = MLServiceClient(base_url=base_url, timeout=float(args.timeout))
        logger.info("✅ MLServiceClient initialized (base_url=%s, timeout=%ss)", base_url, args.timeout)
    except Exception as e:
        logger.error("❌ Failed to initialize MLServiceClient: %s", e)
        logger.error(traceback.format_exc())
        return 1

    await verify_service_health(client)

    schemas, schema_fetch_failures = await fetch_all_schemas(client)
    failures: List[str] = []
    failures.extend(schema_fetch_failures)

    if schemas is None:
        _print_header("SUMMARY")
        logger.error("❌ Cannot continue: schema fetch failed.")
        for f in failures:
            logger.error("  - %s", f)
        return 1

    failures.extend(await verify_get_intent_schema(client, schemas, strict=args.strict))
    failures.extend(await verify_compile_intent(
        client,
        schemas,
        strict=args.strict,
        runs=int(args.runs),
        parallel=int(args.parallel),
    ))

    _print_header("SUMMARY")
    if failures:
        logger.error("❌ %d issue(s):", len(failures))
        for f in failures:
            logger.error("  - %s", f)
        return 1

    logger.info("✅ All verification tests passed!")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default=os.getenv("MLS_BASE_URL", ""), help="ML service base URL")
    parser.add_argument("--timeout", default=float(os.getenv("MLS_TIMEOUT", "20")), type=float, help="Client timeout seconds")
    parser.add_argument("--strict", action="store_true", help="Fail on expectation mismatches (otherwise warn)")
    parser.add_argument("--parallel", default=int(os.getenv("VERIFY_PARALLEL", "1")), type=int, help="Parallel compile test concurrency")
    parser.add_argument("--runs", default=int(os.getenv("VERIFY_RUNS", "1")), type=int, help="Run each compile case N times")
    args = parser.parse_args()

    try:
        code = anyio.run(run_verification, args)
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        code = 130
    except Exception:
        logger.error("Unhandled exception:")
        logger.error(traceback.format_exc())
        code = 1

    sys.exit(code)


if __name__ == "__main__":
    main()
