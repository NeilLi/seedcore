from openai import OpenAI

client = OpenAI(
    base_url="http://a3055aa0ec20d4fefab34716edbe28ad-419314233.us-east-1.elb.amazonaws.com:8000/v1",
    api_key="none"
)

response = client.chat.completions.create(
    model="meta/llama-3.1-8b-base",
    messages=[{"role": "user", "content": "Hello from NIM Llama!"}],
    max_tokens=50
)

text = response.choices[0].message.content
clean_text = text.replace("<|im_start|>", "").replace("<|im_end|>", "").strip()
print(clean_text)
