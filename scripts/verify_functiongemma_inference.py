#!/usr/bin/env python3
"""
Verify FunctionGemma LoRA inference for tool calling (HF Transformers).

Goals:
- Provide tools to the chat template (so model knows valid tool names)
- Generate deterministically
- Stop after the FIRST function call
- Decode only generated text (not prompt / tool declarations)
- Extract + parse the first function call
"""

import json
import re
import os
import torch  # pyright: ignore[reportMissingImports]
from transformers import (  # pyright: ignore[reportMissingImports]
    AutoModelForCausalLM,
    AutoTokenizer,
    StoppingCriteria,
    StoppingCriteriaList,
)
from peft import PeftModel  # pyright: ignore[reportMissingImports]
from transformers.utils import get_json_schema  # pyright: ignore[reportMissingImports]


# -------------------------------
# Paths
# -------------------------------
BASE_MODEL = "google/functiongemma-270m-it"
LORA_ADAPTER = "/app/data/checkpoints/functiongemma-intent-lora"
HF_CACHE = "/app/data/hf_cache"

# Prefer HF_HOME over TRANSFORMERS_CACHE
os.environ.setdefault("HF_HOME", HF_CACHE)


# -------------------------------
# Tool schema definitions (MUST match training names)
# NOTE: use get_json_schema() format (the model was trained on this style)
# -------------------------------
def tuya_send_command(device_id: str, commands: list):
    """
    Send one or more DP commands to a Tuya IoT device.

    Args:
        device_id: Tuya device ID
        commands: List of DP commands, each containing:
            - code: DP code (e.g. "switch_led")
            - value: DP value (bool/number/string)
    """
    pass


def tuya_get_status(device_id: str):
    """
    Get current status of a Tuya IoT device.

    Args:
        device_id: Tuya device ID
    """
    pass


send_schema = get_json_schema(tuya_send_command)
status_schema = get_json_schema(tuya_get_status)

# Ensure names match your dataset + registry
send_schema["function"]["name"] = "tuya.send_command"
status_schema["function"]["name"] = "tuya.get_status"

TOOLS = [send_schema, status_schema]
TOOL_NAMES = {t["function"]["name"] for t in TOOLS}


# -------------------------------
# Gemma-style argument normalization helpers
# FunctionGemma often emits non-standard JSON (unquoted keys, <escape> tokens, etc.)
# -------------------------------
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
    """
    s = _strip_escape_tokens(s)

    # Ensure outer braces
    s = s.strip()
    if not (s.startswith("{") and s.endswith("}")):
        return s

    # Quote keys: {a:... , b:...} -> {"a":... , "b":...}
    s = re.sub(r'([{,]\s*)([A-Za-z_][\w\-]*)\s*:', r'\1"\2":', s)

    # Now process values: find all colons and quote bareword values
    result = []
    i = 0
    brace_depth = 0
    
    while i < len(s):
        char = s[i]
        
        if char == '{':
            brace_depth += 1
            result.append(char)
            i += 1
        elif char == '}':
            brace_depth -= 1
            result.append(char)
            i += 1
        elif char == ':' and i + 1 < len(s):
            result.append(char)
            i += 1
            # Skip whitespace after colon
            while i < len(s) and s[i] in ' \t\n':
                result.append(s[i])
                i += 1
            
            if i >= len(s):
                break
            
            val_start = i
            val_brace_depth = brace_depth
            
            # Check what follows the colon
            if s[i] == '{':
                # Nested object - find its end and process recursively
                nested_start = i
                nested_depth = 1
                brace_depth += 1  # Track the opening brace
                i += 1
                while i < len(s) and nested_depth > 0:
                    if s[i] == '{':
                        nested_depth += 1
                        brace_depth += 1
                    elif s[i] == '}':
                        nested_depth -= 1
                        brace_depth -= 1
                    i += 1
                nested_str = s[nested_start:i]
                nested_processed = _gemma_args_to_jsonish(nested_str)
                result.append(nested_processed)
            elif s[i] == '[':
                # Array - find its end
                array_start = i
                array_depth = 1
                i += 1
                while i < len(s) and array_depth > 0:
                    if s[i] == '[':
                        array_depth += 1
                    elif s[i] == ']':
                        array_depth -= 1
                    i += 1
                result.append(s[array_start:i])
            elif s[i] == '"':
                # Already quoted string - find its end
                result.append(s[i])
                i += 1
                while i < len(s):
                    if s[i] == '\\' and i + 1 < len(s):
                        result.append(s[i:i+2])
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
                    if s[i] == '{':
                        brace_depth += 1
                        i += 1
                    elif s[i] == '}':
                        if brace_depth == val_brace_depth:
                            # This closes the object containing our value
                            break
                        brace_depth -= 1
                        i += 1
                    elif s[i] == ',' and brace_depth == val_brace_depth:
                        # Top-level comma, value ends here
                        break
                    else:
                        i += 1
                
                value = s[val_start:i].strip()
                
                # Check if it's a number, boolean, or null
                if re.fullmatch(r"-?\d+(\.\d+)?", value) or value in ("true", "false", "null"):
                    result.append(value)
                else:
                    # Bareword string - quote it
                    result.append('"' + value + '"')
        else:
            result.append(char)
            i += 1
    
    return ''.join(result)


def normalize_tuya_send_args(args: dict, user_text: str) -> tuple[dict, list[str]]:
    """
    Normalize/repair args into canonical Tuya schema:
      {"device_id": str, "commands": [{"code": str, "value": any}, ...]}
    Returns (normalized_args, warnings)
    """
    warnings = []
    norm = {}

    # device_id
    device_id = args.get("device_id")
    if not isinstance(device_id, str) or not device_id.strip():
        warnings.append("Missing/invalid device_id; set to 'unknown'.")
        device_id = "unknown"
    norm["device_id"] = device_id

    # commands
    commands = args.get("commands")

    # If commands is missing or malformed, repair from user intent
    repaired = False
    if not isinstance(commands, list):
        # Some model outputs put dict or string here
        repaired = True
        commands = []

    # If list items aren't proper dicts with code/value, repair
    good = []
    for c in commands:
        if isinstance(c, dict) and "code" in c and "value" in c:
            good.append({"code": c["code"], "value": c["value"]})

    if repaired or not good:
        # Basic heuristic: infer on/off from user text
        t = user_text.lower()
        if "off" in t or "turn off" in t or "switch off" in t:
            good = [{"code": "switch_led", "value": False}]
        else:
            good = [{"code": "switch_led", "value": True}]
        warnings.append("Repaired commands to canonical DP format (switch_led).")

    norm["commands"] = good
    return norm, warnings


# -------------------------------
# Stop criteria: stop as soon as we see end of first function call
# FunctionGemma often continues into <start_function_response> unless stopped.
# -------------------------------
class StopOnAnySubsequence(StoppingCriteria):
    def __init__(self, tokenizer: AutoTokenizer, stop_strings: list[str]):
        self.stop_seqs = [
            tokenizer.encode(s, add_special_tokens=False) for s in stop_strings
        ]

    def __call__(self, input_ids, scores, **kwargs):
        ids = input_ids[0].tolist()
        for seq in self.stop_seqs:
            if len(ids) >= len(seq) and ids[-len(seq):] == seq:
                return True
        return False


# -------------------------------
# Load model + adapter
# -------------------------------
tokenizer = AutoTokenizer.from_pretrained(LORA_ADAPTER)

dtype = torch.float16 if torch.cuda.is_available() else torch.float32
base = AutoModelForCausalLM.from_pretrained(
    BASE_MODEL,
    cache_dir=HF_CACHE,
    torch_dtype=dtype,
    device_map="auto" if torch.cuda.is_available() else None,
)

model = PeftModel.from_pretrained(base, LORA_ADAPTER)
model.eval()

device = next(model.parameters()).device


# -------------------------------
# Build prompt (WITH tools) — this is required for correct tool names
# Use role="developer" to match your training logs (FunctionGemma renders it as developer)
# -------------------------------
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
    {"role": "user", "content": "turn off the bedroom light with device_id eisp7pij1tkyzhiw"},
]

prompt = tokenizer.apply_chat_template(
    messages,
    tools=TOOLS,
    tokenize=False,
    add_generation_prompt=True,
)

print("\n===== MODEL INPUT (PROMPT) =====")
print(prompt)
print(f"\n(Prompt length: {len(prompt)} characters)")

inputs = tokenizer(prompt, return_tensors="pt").to(device)
print(f"(Tokenized length: {inputs['input_ids'].shape[1]} tokens)\n")

# stop on end-of-call OR start-of-response
stopping = StoppingCriteriaList(
    [StopOnAnySubsequence(tokenizer, ["<end_function_call>", "<start_function_response>"])]
)

# -------------------------------
# Generate
# -------------------------------
with torch.no_grad():
    out = model.generate(
        **inputs,
        max_new_tokens=128,
        do_sample=False,
        repetition_penalty=1.1,           # mild anti-loop; optional
        stopping_criteria=stopping,
        pad_token_id=tokenizer.eos_token_id,
        eos_token_id=tokenizer.eos_token_id,
    )

# Decode ONLY the newly generated tokens (prevents echo of tool declarations)
gen_ids = out[0, inputs["input_ids"].shape[1]:]
generated = tokenizer.decode(gen_ids, skip_special_tokens=False)

print("\n===== GENERATED (CONTINUATION ONLY) =====")
print(generated)


# -------------------------------
# Extract the FIRST function call
# Pattern matches: <start_function_call>call:tuya.send_command{...}<end_function_call>
# -------------------------------
pattern = re.compile(
    r"<start_function_call>\s*call:([\w\.]+)\s*(\{.*?\})\s*<end_function_call>",
    re.DOTALL,
)
m = pattern.search(generated)

if not m:
    raise RuntimeError("❌ No <start_function_call>...<end_function_call> block found in generated text.")

tool_name = m.group(1).strip()
args_text = m.group(2).strip()

if tool_name not in TOOL_NAMES:
    raise RuntimeError(f"❌ Model called unknown tool '{tool_name}'. Known tools: {sorted(TOOL_NAMES)}")

# 1) Try strict JSON first
try:
    arguments = json.loads(args_text)
except json.JSONDecodeError:
    # 2) Try Gemma-style -> JSON-ish normalization
    jsonish = _gemma_args_to_jsonish(args_text)
    try:
        arguments = json.loads(jsonish)
    except json.JSONDecodeError as e:
        raise RuntimeError(
            f"❌ Arguments are not valid JSON even after normalization: {e}\n"
            f"RAW ARGS:\n{args_text}\n\nJSONISH:\n{jsonish}"
        )

# 3) Tool-specific canonicalization
if tool_name == "tuya.send_command":
    arguments, warns = normalize_tuya_send_args(arguments, user_text=messages[-1]["content"])
    if warns:
        print("\n⚠️ NORMALIZATION WARNINGS:")
        for w in warns:
            print(" -", w)

print("\n✅ VERIFIED FUNCTION CALL:")
print(json.dumps({"name": tool_name, "arguments": arguments}, indent=2))
