# Run on Head Node
from huggingface_hub import snapshot_download
import os

tok = os.environ["HF_TOKEN"]
path = snapshot_download(
    repo_id="google/functiongemma-270m-it",
    token=tok,
    cache_dir="/tmp/hf_cache" # Or a persistent volume path
)
print(f"✅ Model pre-cached at: {path}")
