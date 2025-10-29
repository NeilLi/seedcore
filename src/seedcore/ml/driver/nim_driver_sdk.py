"""
seedcore/ml/driver/nim_driver_sdk.py
OpenAI SDK–based implementation of the NIM mode driver.
"""

from openai import OpenAI
from typing import List, Dict, Optional


class NimDriverSDK:
    """
    OpenAI SDK–based driver for SeedCore NIM connections.
    Designed to integrate cleanly with SeedCore agents and components.
    """

    def __init__(
        self,
        base_url: str,
        api_key: Optional[str] = None,
        model: str = "meta/llama-3.1-8b-base",
        timeout: int = 60,
    ):
        self.client = OpenAI(
            base_url=base_url.rstrip("/"),
            api_key=api_key or "none",
            timeout=timeout,
        )
        self.model = model

    def chat(self, messages: List[Dict[str, str]], **kwargs) -> str:
        """
        Perform a chat completion via the OpenAI SDK.
        """
        response = self.client.chat.completions.create(
            model=kwargs.get("model", self.model),
            messages=messages,
            max_tokens=kwargs.get("max_tokens", 100),
            temperature=kwargs.get("temperature", 0.7),
        )

        text = response.choices[0].message.content
        return self._clean_text(text)

    @staticmethod
    def _clean_text(text: str) -> str:
        """Strip formatting and control tokens."""
        return (
            text.replace("<|im_start|>", "")
            .replace("<|im_end|>", "")
            .replace("\\begin{code}", "")
            .replace("\\end{code}", "")
            .strip()
        )


# Example usage
if __name__ == "__main__":
    client = NimDriverSDK(
        base_url="http://a3055aa0ec20d4fefab34716edbe28ad-419314233.us-east-1.elb.amazonaws.com:8000/v1",
        api_key="none",
        model="meta/llama-3.1-8b-base",
    )

    messages = [{"role": "user", "content": "Hello from NIM Llama (SDK)!"}]
    response = client.chat(messages)
    print(response)

