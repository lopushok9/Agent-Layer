from __future__ import annotations

import httpx

from .constants import model_system_prompt
from .models import ParsedIntent
from .parsing import extract_json_payload, intent_from_payload


class OpenRouterClient:
    def __init__(self, api_key: str, model: str) -> None:
        self._api_key = api_key
        self._model = model
        self._base_url = "https://openrouter.ai/api/v1"

    async def parse_intent(self, user_message: str, context_note: str | None = None) -> ParsedIntent:
        content = user_message
        if context_note:
            content = f"{context_note}\n\nUser message:\n{user_message}"

        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": model_system_prompt()},
                {"role": "user", "content": content},
            ],
            "temperature": 0,
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{self._base_url}/chat/completions",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            data = response.json()

        content_text = (
            data.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
        )
        parsed = extract_json_payload(content_text)
        return intent_from_payload(parsed)
