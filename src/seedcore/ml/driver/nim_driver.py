"""
seedcore/ml/driver/nim_driver.py
Low-level NIM mode connection and driver layer for SeedCore agents.

Author: Neil
Purpose: Provide a unified minimal I/O layer for interacting with local or remote OpenAI-compatible APIs.
"""

import os
import json
import httpx
from typing import List, Dict, Optional, Union


class NimClient:
    """
    A low-level OpenAI-compatible client for SeedCore components and agents.
    """

    def __init__(
        self,
        base_url: str,
        api_key: Optional[str] = None,
        model: str = "meta/llama-3.1-8b-base",
        timeout: int = 60,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key or os.getenv("OPENAI_API_KEY", "none")
        self.model = model
        self.timeout = timeout
        self.session = httpx.Client(timeout=timeout)
        self.headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }

    def _post(self, endpoint: str, payload: dict) -> dict:
        """Send POST request and handle response."""
        url = f"{self.base_url}{endpoint}"
        response = self.session.post(url, headers=self.headers, json=payload)

        if response.status_code != 200:
            raise RuntimeError(f"NIM request failed: {response.status_code} {response.text}")

        return response.json()

    def chat(self, messages: List[Dict[str, str]], **kwargs) -> str:
        """
        Perform a chat completion request.
        """
        payload = {
            "model": kwargs.get("model", self.model),
            "messages": messages,
            "max_tokens": kwargs.get("max_tokens", 100),
            "temperature": kwargs.get("temperature", 0.7),
        }

        data = self._post("/chat/completions", payload)

        try:
            text = data["choices"][0]["message"]["content"]
        except KeyError:
            raise ValueError(f"Unexpected response format: {json.dumps(data, indent=2)}")

        clean_text = self._clean_text(text)
        return clean_text

    @staticmethod
    def _clean_text(text: str) -> str:
        """Strip control and formatting tokens."""
        return (
            text.replace("<|im_start|>", "")
            .replace("<|im_end|>", "")
            .replace("\\begin{code}", "")
            .replace("\\end{code}", "")
            .strip()
        )

    def debug_chat(self, messages: List[Dict[str, str]], **kwargs):
        """Debug mode: prints both clean and raw outputs."""
        result = self.chat(messages, **kwargs)
        print("=== NIM Conversation ===")
        print("user:")
        print(f"1) {messages[0]['content']}")
        print("\nassistant:")
        print(f"1) {result}")
        print("\n=== End Conversation ===")
        print("\n--- Raw Response ---")
        print(json.dumps(result, indent=2))
        return result


# Example usage
if __name__ == "__main__":
    client = NimClient(
        base_url="http://a3055aa0ec20d4fefab34716edbe28ad-419314233.us-east-1.elb.amazonaws.com:8000/v1",
        api_key="none",
        model="meta/llama-3.1-8b-base",
    )

    messages = [{"role": "user", "content": "Hello from NIM Llama!"}]
    response = client.chat(messages)
    print(response)

