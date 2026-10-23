"""Shared browser provisioning only. Card values and browser code bypass this API."""
from __future__ import annotations

import hashlib
import json
import re
import time
import uuid
from urllib.parse import urlsplit

import httpx
from nacl.signing import SigningKey

from agent_wallet.card_runtime_secrets import RuntimeVaultStorage
from agent_wallet.config import resolve_kernel_gateway_url
from agent_wallet.wallet_layer.base import WalletBackendError

PROTOCOL = "agentlayer-kernel-v1"
CREATE_PATH = "/v1/kernel/browser-sessions"
IDENTITY_REFERENCE = "00000000000000000000000000000001"


class KernelGateway:
    def __init__(self, vault, url=None):
        self.vault = vault
        self.url = resolve_kernel_gateway_url()
        # Saved URLs cannot redirect signed requests to a different origin after
        # a config change. Keep the old lease inaccessible until config is restored;
        # server cleanup remains authoritative even after the client disappears.
        if url is not None and url != self.url:
            raise WalletBackendError("Restore the original provider gateway setting to close this shared browser. Server expiry still applies.")
        self.identity = RuntimeVaultStorage(vault, "browser_identity")

    async def _headers(self, method, path, body):
        async with self.vault.async_record_lock(IDENTITY_REFERENCE):
            target = self.identity.path(IDENTITY_REFERENCE)
            if target.exists() or target.is_symlink():
                state = self.identity.load(IDENTITY_REFERENCE)
                try:
                    key = SigningKey(bytes.fromhex(state["signing_key"]))
                except (ValueError, KeyError, TypeError):
                    raise WalletBackendError("Shared browser installation identity is invalid; it was not replaced.") from None
            else:
                key = SigningKey.generate()
                self.identity.save(IDENTITY_REFERENCE, {"signing_key": bytes(key).hex()})
        timestamp, nonce = str(int(time.time())), uuid.uuid4().hex
        signed_path = urlsplit(self.url).path.rstrip("/") + path
        message = "\n".join((PROTOCOL, method, signed_path, timestamp, nonce, hashlib.sha256(body).hexdigest())).encode()
        return {"X-AgentLayer-Client-Key": bytes(key.verify_key).hex(),
                "X-AgentLayer-Timestamp": timestamp, "X-AgentLayer-Nonce": nonce,
                "X-AgentLayer-Signature": key.sign(message).signature.hex(),
                "Content-Type": "application/json"}

    async def _request(self, method, path, data=None):
        body = json.dumps(data, separators=(",", ":")).encode() if data is not None else b""
        headers = await self._headers(method, path, body) if method == "POST" else {}
        try:
            async with httpx.AsyncClient(timeout=75, trust_env=False, follow_redirects=False) as client:
                async with client.stream(method, self.url + path, headers=headers, content=body) as response:
                    if response.status_code == 429:
                        raise WalletBackendError("Shared browser quota reached. Try again later; no checkout was started.")
                    if not 200 <= response.status_code < 300:
                        raise WalletBackendError("Shared browser service is unavailable. Your vault and saved payment operations are unchanged.")
                    raw = bytearray()
                    async for chunk in response.aiter_bytes():
                        raw.extend(chunk)
                        if len(raw) > 32 * 1024:
                            raise ValueError()
                    result = json.loads(raw)
                    if not isinstance(result, dict):
                        raise ValueError()
                    return result
        except WalletBackendError:
            raise
        except Exception:
            # Never surface a response/exception that may contain a scoped key.
            raise WalletBackendError("Shared browser request did not complete. Saved cleanup will use the same lease; no automatic allocation retry.") from None

    async def allocate(self, lease):
        capabilities = await self._request("GET", "/v1/kernel/capabilities")
        if capabilities.get("protocol") != PROTOCOL or capabilities.get("available") is not True:
            raise WalletBackendError("Shared browser service is not enabled yet. Existing personal Kernel connections remain available.")
        data = await self._request("POST", CREATE_PATH, {"lease_id": lease})
        session, key, expires = data.get("session_id"), data.get("session_key"), data.get("expires_at")
        if (data.get("protocol") != PROTOCOL or data.get("lease_id") != lease
                or not isinstance(session, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,256}", session)
                or not isinstance(key, str) or not 16 <= len(key) <= 8192
                or any(ord(c) < 33 or ord(c) > 126 for c in key)
                or type(expires) is not int or not time.time() < expires <= time.time() + 1830):
            raise WalletBackendError("Invalid shared browser allocation; the lease will be closed.")
        return {"session_id": session, "session_key": key, "lease_expires_at": expires}

    async def close(self, lease):
        result = await self._request("POST", CREATE_PATH + "/" + lease + "/close", {})
        return result.get("closed") is True and result.get("cleanup_pending") is False
