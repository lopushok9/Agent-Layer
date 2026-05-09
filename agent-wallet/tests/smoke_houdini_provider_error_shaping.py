"""Smoke test for Houdini provider error shaping on empty/invalid JSON bodies."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent_wallet.config import settings
from agent_wallet.exceptions import ProviderError
from agent_wallet.providers import houdini


class FakeResponse:
    def __init__(self, status_code: int, text: str):
        self.status_code = status_code
        self.text = text
        self.content = text.encode("utf-8")

    def json(self):
        import json

        return json.loads(self.text)


class FakeClient:
    async def post(self, url: str, *, json=None, headers=None):
        return FakeResponse(200, "")


async def main() -> None:
    original_values = {
        "houdini_api_key": settings.houdini_api_key,
        "houdini_api_secret": settings.houdini_api_secret,
        "houdini_user_ip": settings.houdini_user_ip,
        "provider_gateway_url": settings.provider_gateway_url,
    }
    original_get_client = houdini.get_client
    try:
        settings.houdini_api_key = "key"
        settings.houdini_api_secret = "secret"
        settings.houdini_user_ip = "127.0.0.1"
        settings.provider_gateway_url = ""
        houdini.get_client = lambda: FakeClient()

        try:
            await houdini.create_exchange(
                quote_id="private-quote-1",
                destination_address="GkcdCet7HRRCS3PypzwZHgd5uzVT4A9uoKrUvXXj31Rf",
            )
        except ProviderError as exc:
            message = str(exc)
            assert "empty response body" in message.lower()
        else:
            raise AssertionError("Expected empty Houdini response to raise ProviderError.")
    finally:
        for key, value in original_values.items():
            setattr(settings, key, value)
        houdini.get_client = original_get_client

    print("smoke_houdini_provider_error_shaping: ok")


if __name__ == "__main__":
    asyncio.run(main())
