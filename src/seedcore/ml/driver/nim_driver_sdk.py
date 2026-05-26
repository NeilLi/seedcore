"""
seedcore/ml/driver/nim_driver_sdk.py
OpenAI SDK–based implementation of the NIM mode driver.
"""

from typing import List, Dict, Optional
from types import SimpleNamespace

try:
    from openai import OpenAI
except Exception:  # pragma: no cover - exercised in environments without openai
    OpenAI = None  # type: ignore[assignment]


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
        if OpenAI is None:
            self.client = SimpleNamespace()
        else:
            self.client = OpenAI(
                base_url=base_url.rstrip("/"),
                api_key=api_key or "none",
                timeout=timeout,
            )
        self._ensure_chat_completions_interface()
        self.model = model

    def _ensure_chat_completions_interface(self) -> None:
        """Provide a patchable chat-completions surface for minimal OpenAI stubs."""
        chat = getattr(self.client, "chat", None)
        completions = getattr(chat, "completions", None) if chat is not None else None
        create = getattr(completions, "create", None) if completions is not None else None
        if callable(create):
            return

        def _missing_create(*_args, **_kwargs):
            raise RuntimeError("OpenAI client does not expose chat.completions.create")

        self.client.chat = SimpleNamespace(  # type: ignore[attr-defined]
            completions=SimpleNamespace(create=_missing_create)
        )

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
