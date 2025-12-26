from datasets import load_from_disk  # pyright: ignore[reportMissingImports]
from transformers import (  # pyright: ignore[reportMissingImports]
    AutoModelForCausalLM,
    AutoTokenizer,
    TrainingArguments,
    Trainer,
    DataCollatorForLanguageModeling,
)
from peft import LoraConfig, get_peft_model  # pyright: ignore[reportMissingImports]
import torch  # pyright: ignore[reportMissingImports]
import json
import sys
from pathlib import Path

# Import tools module to reconstruct schemas with correct names
sys.path.insert(0, str(Path(__file__).parent))
from tools import tuya_send_command, tuya_get_status
from transformers.utils import get_json_schema  # pyright: ignore[reportMissingImports]
from .path_config import (
    BASE_MODEL_ID as MODEL_ID,
    FUNCTION_CALL_DATASET_DIR,
    LORA_ADAPTER_DIR,
    HF_CACHE_DIR,
)

# Reconstruct tool schemas with correct names (matching dataset)
_tuya_send_schema = get_json_schema(tuya_send_command)
_tuya_get_schema = get_json_schema(tuya_get_status)
_tuya_send_schema["function"]["name"] = "tuya.send_command"
_tuya_get_schema["function"]["name"] = "tuya.get_status"

# Strengthen schemas to match tools.py definitions
_tuya_send_schema["function"]["parameters"] = {
    "type": "object",
    "properties": {
        "device_id": {"type": "string", "description": "Tuya device ID"},
        "commands": {
            "type": "array",
            "description": "List of Tuya DP commands",
            "items": {
                "type": "object",
                "properties": {
                    "code": {"type": "string", "description": "Tuya DP code"},
                    "value": {"description": "DP value (bool, number, string, etc.)"},
                },
                "required": ["code", "value"],
            },
        },
    },
    "required": ["device_id", "commands"],
}

_tuya_get_schema["function"]["parameters"] = {
    "type": "object",
    "properties": {
        "device_id": {"type": "string", "description": "Tuya device ID"}
    },
    "required": ["device_id"],
}

TOOLS_FOR_TRAINING = [_tuya_send_schema, _tuya_get_schema]

DATASET_PATH = str(FUNCTION_CALL_DATASET_DIR)
OUTPUT_DIR = str(LORA_ADAPTER_DIR)

# --------------------------------------------------
# Load dataset
# --------------------------------------------------
dataset = load_from_disk(DATASET_PATH)

# --------------------------------------------------
# Load tokenizer & model
# --------------------------------------------------
tokenizer = AutoTokenizer.from_pretrained(
    MODEL_ID,
    cache_dir=str(HF_CACHE_DIR),
)

model = AutoModelForCausalLM.from_pretrained(
    MODEL_ID,
    cache_dir=str(HF_CACHE_DIR),
    torch_dtype=torch.float16 if torch.cuda.is_available() else torch.float32,
    device_map="auto" if torch.cuda.is_available() else None,
)

# --------------------------------------------------
# Apply LoRA
# --------------------------------------------------
lora_config = LoraConfig(
    r=8,
    lora_alpha=16,
    target_modules=["q_proj", "v_proj"],
    lora_dropout=0.05,
    task_type="CAUSAL_LM",
)

model = get_peft_model(model, lora_config)
model.print_trainable_parameters()

# --------------------------------------------------
# Formatting function (CRITICAL)
# --------------------------------------------------
def format_sample(example):
    """
    Convert {messages, tools} → tokenized input with labels
    
    Note: messages are stored as JSON strings in the dataset.
    We reconstruct tool schemas from function objects to ensure correct format
    and names that match the dataset.
    """
    # Parse JSON strings back to Python objects
    messages = json.loads(example["messages"])
    
    # Use reconstructed schemas (with correct names matching dataset)
    text = tokenizer.apply_chat_template(
        messages,
        tools=TOOLS_FOR_TRAINING,
        tokenize=False,
    )

    tokens = tokenizer(
        text,
        truncation=True,
        max_length=2048,
    )

    tokens["labels"] = tokens["input_ids"].copy()
    return tokens


dataset = dataset.map(
    format_sample,
    remove_columns=dataset["train"].column_names,
    desc="Tokenizing with chat template",
)

# --------------------------------------------------
# Training setup
# --------------------------------------------------
args = TrainingArguments(
    output_dir=OUTPUT_DIR,
    per_device_train_batch_size=1,
    gradient_accumulation_steps=8,
    learning_rate=5e-5,
    num_train_epochs=3,
    logging_steps=10,
    save_steps=200,
    fp16=torch.cuda.is_available(),
    report_to="none",
)

data_collator = DataCollatorForLanguageModeling(
    tokenizer=tokenizer,
    mlm=False,
)

trainer = Trainer(
    model=model,
    args=args,
    train_dataset=dataset["train"],
    eval_dataset=dataset["test"],
    data_collator=data_collator,
)

trainer.train()

# --------------------------------------------------
# Save LoRA adapter
# --------------------------------------------------
model.save_pretrained(OUTPUT_DIR)
tokenizer.save_pretrained(OUTPUT_DIR)

print("✅ LoRA adapter saved to:", OUTPUT_DIR)
