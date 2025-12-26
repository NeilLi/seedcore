# prepare_function_call_data.py
import json
from typing import Dict, Any

from datasets import Dataset, Features, Value  # pyright: ignore[reportMissingImports]
from tools import TOOLS
from .path_config import (
    INTENT_TOOL_DATASET_JSONL as INPUT_JSONL,
    FUNCTION_CALL_DATASET_DIR as OUTPUT_DIR,
)

# ---------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------

DEFAULT_SYSTEM_MSG = (
    "You are an intent compiler. "
    "Convert user requests into function calls using the provided tools. "
    "Return ONLY a function call."
)

# Optional: fail fast if tools are misconfigured
TOOL_NAMES = {tool["function"]["name"] for tool in TOOLS}


# ---------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------
def validate_row(row: Dict[str, Any]) -> bool:
    required = {"user_content", "tool_name", "tool_arguments"}
    if not required.issubset(row):
        return False

    if row["tool_name"] not in TOOL_NAMES:
        raise ValueError(f"Unknown tool: {row['tool_name']}")

    try:
        json.loads(row["tool_arguments"])
    except Exception as e:
        raise ValueError(f"Invalid tool_arguments JSON: {e}")

    return True


# ---------------------------------------------------------------------
# Conversation builder
# ---------------------------------------------------------------------
def create_conversation(sample: Dict[str, Any]):
    """
    Convert a single intent sample into a FunctionGemma-compatible
    function-calling conversation.
    
    Note: We store nested structures as JSON strings to avoid PyArrow
    schema inference issues with mixed types (bool, int, string, etc.)
    """
    tool_arguments = json.loads(sample["tool_arguments"])
    
    conversation = {
        "messages": [
            {
                "role": "developer",
                "content": DEFAULT_SYSTEM_MSG,
            },
            {
                "role": "user",
                "content": sample["user_content"],
            },
            {
                "role": "assistant",
                "tool_calls": [
                    {
                        "type": "function",
                        "function": {
                            "name": sample["tool_name"],
                            "arguments": tool_arguments,
                        },
                    }
                ],
            },
        ],
        "tools": TOOLS,
    }
    
    # Convert to JSON strings to avoid PyArrow type inference issues
    return {
        "messages": json.dumps(conversation["messages"], ensure_ascii=False),
        "tools": json.dumps(conversation["tools"], ensure_ascii=False),
    }


# ---------------------------------------------------------------------
# Load + build dataset
# ---------------------------------------------------------------------
rows = []
with INPUT_JSONL.open() as f:
    for line_no, line in enumerate(f, start=1):
        if not line.strip():
            continue

        row = json.loads(line)

        if validate_row(row):
            rows.append(row)

print(f"✅ Loaded {len(rows)} valid intent samples")

if len(rows) == 0:
    print("❌ Error: No valid samples found. Cannot create empty dataset.")
    print(f"   Check that {INPUT_JSONL} exists and contains valid rows with:")
    print("   - user_content")
    print("   - tool_name")
    print("   - tool_arguments")
    exit(1)

dataset = Dataset.from_list(rows)

# Define explicit features to avoid PyArrow schema inference issues
features = Features({
    "messages": Value("string"),  # JSON string
    "tools": Value("string"),     # JSON string
})

dataset = dataset.map(
    create_conversation,
    remove_columns=dataset.column_names,
    desc="Building function-call conversations",
    features=features,
)

# Deterministic split (important for reproducibility)
dataset = dataset.train_test_split(
    test_size=0.2,
    seed=42,
)

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
dataset.save_to_disk(OUTPUT_DIR)

print(f"✅ Dataset saved to {OUTPUT_DIR.resolve()}")
print(f"   Train: {len(dataset['train'])} examples")
print(f"   Test: {len(dataset['test'])} examples")
