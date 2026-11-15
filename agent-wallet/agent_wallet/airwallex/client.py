"""Minimal async Airwallex REST client (sandbox by default).

Credentials come from the environment (AIRWALLEX_CLIENT_ID / AIRWALLEX_API_KEY)
or from ``<OPENCLAW_HOME>/agent-treasury/airwallex.json`` (mode 0600) written by
``treasury connect``. Access tokens are cached until shortly before expiry.
Error messages never include credentials, tokens or raw response bodies beyond
Airwallex's own ``code``/``message`` fields.
"""
from __future__ import annotations

import json
import os
import stat
import time
import uuid
from pathlib import Path
from typing import Any

import httpx

from agent_wallet.config import resolve_openclaw_home
from agent_wallet.file_ops import atomic_write_text
from agent_wallet.wallet_layer.base import WalletBackendError

SANDBOX_URL = "https://api.sandbox.airwallex.com"
PRODUCTION_URL = "https://api.airwallex.com"
API_VERSION = "2026-08-21"


class AirwallexError(WalletBackendError):
    def __init__(self, message: str, *, status: int | None = None, code: str | None = None):
        super().__init__(message)
        self.status = status
        self.code = code


def treasury_home() -> Path:
    path = resolve_openclaw_home() / "agent-treasury"
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    return path


def _credentials_path() -> Path:
    return treasury_home() / "airwallex.json"


def save_credentials(client_id: str, api_key: str, *, environment: str = "sandbox") -> Path:
    if environment not in {"sandbox", "production"}:
        raise AirwallexError("environment must be sandbox or production.")
    path = _credentials_path()
    atomic_write_text(path, json.dumps({"client_id": client_id, "api_key": api_key, "environment": environment}))
    os.chmod(path, 0o600)
    return path


def load_credentials() -> dict[str, str]:
    client_id = os.getenv("AIRWALLEX_CLIENT_ID") or os.getenv("clientid_aw")
    api_key = os.getenv("AIRWALLEX_API_KEY") or os.getenv("airwallex")
    environment = os.getenv("AIRWALLEX_ENV", "sandbox")
    if not (client_id and api_key):
        path = _credentials_path()
        if path.is_file():
            mode = stat.S_IMODE(path.stat().st_mode)
            if mode & 0o077:
                raise AirwallexError("Airwallex credentials file must be mode 0600.")
            data = json.loads(path.read_text())
            client_id, api_key = data.get("client_id"), data.get("api_key")
            environment = data.get("environment", "sandbox")
    if not (client_id and api_key):
        raise AirwallexError("Airwallex is not connected. Run `treasury connect` or set AIRWALLEX_CLIENT_ID and AIRWALLEX_API_KEY.")
    return {"client_id": client_id, "api_key": api_key, "environment": environment}


class AirwallexClient:
    _token_cache: dict[str, tuple[str, float]] = {}

    def __init__(self, credentials: dict[str, str] | None = None, *, timeout: float = 30.0):
        self.credentials = credentials or load_credentials()
        self.environment = self.credentials.get("environment", "sandbox")
        if self.environment == "production" and os.getenv("AIRWALLEX_ALLOW_PRODUCTION") != "1":
            raise AirwallexError("Production Airwallex is disabled for this prototype. Set AIRWALLEX_ALLOW_PRODUCTION=1 deliberately.")
        self.base_url = PRODUCTION_URL if self.environment == "production" else SANDBOX_URL
        self.timeout = timeout

    @property
    def is_sandbox(self) -> bool:
        return self.environment == "sandbox"

    async def _token(self, client: httpx.AsyncClient, *, force: bool = False) -> str:
        key = self.base_url + "|" + self.credentials["client_id"]
        cached = self._token_cache.get(key)
        if cached and not force and cached[1] - time.time() > 60:
            return cached[0]
        response = await client.post(
            self.base_url + "/api/v1/authentication/login",
            headers={"x-client-id": self.credentials["client_id"], "x-api-key": self.credentials["api_key"],
                     "Content-Type": "application/json"},
        )
        if response.status_code not in (200, 201):
            raise AirwallexError("Airwallex authentication failed (HTTP %d). Check the client ID and API key." % response.status_code,
                                 status=response.status_code)
        token = response.json().get("token")
        if not token:
            raise AirwallexError("Airwallex authentication returned no token.")
        # Tokens last 30 minutes; refresh after 25.
        self._token_cache[key] = (token, time.time() + 25 * 60)
        return token

    async def request(self, method: str, path: str, *, json_body: dict[str, Any] | None = None,
                      params: dict[str, Any] | None = None, api_version: str | None = API_VERSION) -> Any:
        async with httpx.AsyncClient(timeout=self.timeout, trust_env=False) as client:
            for attempt in range(2):
                headers = {"Authorization": "Bearer " + await self._token(client, force=attempt > 0),
                           "Content-Type": "application/json"}
                if api_version:
                    headers["x-api-version"] = api_version
                response = await client.request(method, self.base_url + path, headers=headers, json=json_body, params=params)
                if response.status_code == 401 and attempt == 0:
                    continue
                break
        if response.status_code >= 400:
            code = message = None
            try:
                body = response.json()
                code, message = body.get("code"), body.get("message")
            except Exception:
                pass
            raise AirwallexError(
                "Airwallex %s %s failed (HTTP %d%s%s)." % (method, path.split("?")[0], response.status_code,
                                                         ", " + str(code) if code else "", ": " + str(message)[:200] if message else ""),
                status=response.status_code, code=code)
        if not response.content:
            return {}
        return response.json()

    @staticmethod
    def request_id() -> str:
        return str(uuid.uuid4())
