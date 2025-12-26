import json
from typing import Dict, Any

from seedcore.ml.intent.intent_compiler import get_intent_compiler
from seedcore.ml.intent.schema_registry import get_schema_registry
from seedcore.tools.tuya.tuya_tools import (
    TuyaGetStatusTool,
    TuyaSendCommandTool,
)
from .path_config import (
    INTENT_TOOL_DATASET_JSONL as INPUT_JSONL,
    INTENT_TOOL_SFT_DATASET_JSONL as OUTPUT_JSONL,
)

# ------------------------------------------------------------------
# Config
# ------------------------------------------------------------------

SYSTEM_MSG = (
    "You are an intent compiler. "
    "Translate user requests into Tuya function calls. "
    "Return ONLY a function call."
)

ALLOWED_TOOLS = {
    TuyaGetStatusTool.name,
    TuyaSendCommandTool.name,
}

compiler = get_intent_compiler()
schema_registry = get_schema_registry()

# Tool schemas exposed to the model
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": TuyaGetStatusTool.name,
            "description": TuyaGetStatusTool.description,
            "parameters": TuyaGetStatusTool().schema(),
        },
    },
    {
        "type": "function",
        "function": {
            "name": TuyaSendCommandTool.name,
            "description": TuyaSendCommandTool.description,
            "parameters": TuyaSendCommandTool().schema(),
        },
    },
]


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------
def load_jsonl(path):
    with path.open() as f:
        for line in f:
            if line.strip():
                yield json.loads(line)


def validate_tool_call(name: str, args: Dict[str, Any]) -> bool:
    """
    Validate a tool call. Returns True if valid, False if disallowed.
    Raises ValueError for invalid arguments (schema violations).
    """
    if name not in ALLOWED_TOOLS:
        return False

    if name == "tuya.get_status":
        if "device_id" not in args:
            raise ValueError("tuya.get_status requires device_id")

    if name == "tuya.send_command":
        if "device_id" not in args or "commands" not in args:
            raise ValueError("tuya.send_command requires device_id + commands")
        if not isinstance(args["commands"], list):
            raise ValueError("commands must be a list")

    return True


def build_sft_sample(user_text: str, tool_name: str, tool_arguments: Dict[str, Any]):
    """
    Build an SFT sample. Assumes tool_name is already validated.
    """
    return {
        "messages": [
            {"role": "system", "content": SYSTEM_MSG},
            {"role": "user", "content": user_text},
            {
                "role": "assistant",
                "tool_call": {
                    "name": tool_name,
                    "arguments": tool_arguments,
                },
            },
        ],
        "tools": TOOLS,
    }


# ------------------------------------------------------------------
# Build dataset
# ------------------------------------------------------------------
dataset = []
skipped = 0

for row in load_jsonl(INPUT_JSONL):
    user_text = row["user_content"]
    context = row.get("context", {})

    res = compiler._fallback_compile(
        user_text,
        context,
        schema_registry,
    )

    # Only include samples that compile to allowed Tuya tools
    try:
        if not validate_tool_call(res.function, res.arguments):
            skipped += 1
            continue

        sample = build_sft_sample(
            user_text=user_text,
            tool_name=res.function,
            tool_arguments=res.arguments,
        )
        dataset.append(sample)
    except ValueError as e:
        # Skip samples with invalid arguments (schema violations)
        skipped += 1
        print(f"⚠️  Skipping sample (validation error): {user_text[:50]}... → {e}")

# ------------------------------------------------------------------
# Write output
# ------------------------------------------------------------------
with OUTPUT_JSONL.open("w") as f:
    for sample in dataset:
        f.write(json.dumps(sample, ensure_ascii=False) + "\n")

print(f"✅ Wrote {len(dataset)} Tuya tool samples → {OUTPUT_JSONL}")
if skipped > 0:
    print(f"   (Skipped {skipped} samples that didn't compile to Tuya tools)")
