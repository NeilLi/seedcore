# verify_nim_retrieval.py
from openai import OpenAI

client = OpenAI(
    base_url="http://af3a6a34f659a409584db07209d82853-1298671438.us-east-1.elb.amazonaws.com/v1",
    api_key="not-needed"  # NIM doesn't require this
)

# List models
models = client.models.list()
print("Available models:")
for m in models.data:
    print("-", m.id)

# --- Example Inputs ---
query_text = "What is NVIDIA NIM Retrieval?"
doc_text = "NVIDIA NIM Retrieval is powering next-generation multimodal search."

# --- Query Embedding ---
query_emb = client.embeddings.create(
    model="nvidia/nv-embedqa-e5-v5",
    input=query_text,
    extra_body={"input_type": "query"}  # ✅ Required for asymmetric models
)

# --- Document Embedding ---
doc_emb = client.embeddings.create(
    model="nvidia/nv-embedqa-e5-v5",
    input=doc_text,
    extra_body={"input_type": "passage"}  # ✅ Required for asymmetric models
)

print("\nQuery Embedding Length:", len(query_emb.data[0].embedding))
print("Document Embedding Length:", len(doc_emb.data[0].embedding))

# --- Simple cosine similarity test ---
import numpy as np

q = np.array(query_emb.data[0].embedding)
d = np.array(doc_emb.data[0].embedding)
similarity = np.dot(q, d) / (np.linalg.norm(q) * np.linalg.norm(d))

print("\nCosine Similarity:", round(similarity, 4))
