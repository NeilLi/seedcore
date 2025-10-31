from openai import OpenAI

import time

start_time = time.time()

client = OpenAI(
    base_url="http://a3055aa0ec20d4fefab34716edbe28ad-419314233.us-east-1.elb.amazonaws.com:8000/v1",
    api_key="none"
)

# Define the conversation
messages = [{"role": "user", "content": "Hello from NIM Llama!"}]

response = client.chat.completions.create(
    model="meta/llama-3.1-8b-base",
    messages=messages,
    max_tokens=50,
    temperature=0.7
)

# Get and clean the response
assistant_text = response.choices[0].message.content
clean_text = assistant_text.replace("<|im_start|>", "").replace("<|im_end|>", "").strip()

# Remove LaTeX-like formatting
clean_text = clean_text.replace("\\end{code}", "").replace("\\begin{code}", "").strip()

end_time = time.time()
print(f"\nTotal conversation time: {end_time - start_time:.3f} seconds")

# Format the conversation nicely
print("=== NIM LLaMA Conversation ===")
print()
print("user:")
print(f"1) {messages[0]['content']}")
print()
print("assistant:")
print(f"1) {clean_text}")
print()
print("=== End Conversation ===")

# Also print raw response for debugging
print("\n--- Raw Response (for debugging) ---")
print(f"Raw: '{assistant_text}'")
