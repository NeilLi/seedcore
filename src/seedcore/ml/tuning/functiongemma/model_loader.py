import os
from huggingface_hub import snapshot_download  # pyright: ignore[reportMissingImports]
from .path_config import (
    BASE_MODEL_ID as BASE_MODEL,
    CHECKPOINT_DIR,
    HF_CACHE_DIR,
    ensure_dirs,
)

# -----------------------------
# Paths (local Docker friendly)
# -----------------------------
ensure_dirs()

print(f"📦 Checkpoints will be saved to: {CHECKPOINT_DIR}")
print(f"📥 HF cache dir: {HF_CACHE_DIR}")

# -----------------------------
# Auth
# -----------------------------
hf_token = os.environ.get("HF_TOKEN")
if not hf_token:
    raise RuntimeError("HF_TOKEN not set")

# -----------------------------
# Pre-cache model (Colab equivalent)
# -----------------------------
model_path = snapshot_download(
    repo_id=BASE_MODEL,
    token=hf_token,
    cache_dir=str(HF_CACHE_DIR),
)

print(f"✅ Base model cached at: {model_path}")

# -----------------------------
# Training config (mirrors Google example)
# -----------------------------
training_config = {
    "base_model": BASE_MODEL,
    "learning_rate": 5e-5,
    "output_dir": str(CHECKPOINT_DIR),
}

print("🧠 Training config:")
for k, v in training_config.items():
    print(f"  {k}: {v}")
