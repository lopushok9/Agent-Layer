"""Capture Laso card responses before the host or model can observe them."""
from __future__ import annotations

import asyncio
import json
import posixpath
import time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import unquote, urlsplit

import httpx

from agent_wallet.card_vault import CardVault, MAX_BYTES
from agent_wallet.card_catalog import (
    CardCatalog, CARD_TYPES, MIN_REFRESH_INTERVAL, card_object, credentials, details_ready,
)
from agent_wallet.providers.x402 import LASO_PARTNER_HEADERS
from agent_wallet.wallet_layer.base import WalletBackendError

ORDER_PATHS = {"/get-card": "Non-Reloadable U.S.", "/order-intl-card": "Non-Reloadable International"}
STATUSES = {"pending", "queued", "ready", "failed", "cancelled", "expired", "depleted"}


def card_path(url: str) -> str | None:
    parsed = urlsplit(url)
    host = parsed.hostname or ""
    if host != "laso.finance" and not host.endswith(".laso.finance"):
        return None
    decoded = parsed.path
    for _ in range(3):
        decoded = unquote(decoded)
    path = posixpath.normpath(decoded).rstrip("/")
    if path not in {*ORDER_PATHS, "/get-card-data"}:
        return None
    if parsed.scheme != "https" or parsed.netloc != "laso.finance" or parsed.fragment or parsed.path != path:
        raise WalletBackendError("Card requests must use the exact HTTPS laso.finance host.")
    return path


def preflight(url: str, user_id: str | None) -> CardVault | None:
    path = card_path(url)
    if path is None:
        return None
    if path == "/get-card-data":
        raise WalletBackendError("Raw card retrieval is private. Use refresh_saved_card with a vault reference.")
    vault = CardVault(user_id)
    try:
        vault.ensure_system()
        vault.check_ready()
        CardCatalog(vault).preflight()
    except WalletBackendError:
        raise
    except Exception:
        raise WalletBackendError("System card vault could not be provisioned. Check macOS login Keychain access before ordering.") from None
    return vault


def summary(record: dict[str, Any], reference: str) -> dict[str, Any]:
    card = card_object(record.get("latest") or record.get("order") or {})
    details = card.get("card_details") or {}
    number = str(details.get("card_number") or "") if isinstance(details, dict) else ""
    status = card.get("status")
    return {
        "vault_reference": reference,
        "status": status if isinstance(status, str) and status in STATUSES else "retrieval_required",
        "last4": number[-4:] if number.isascii() and number.isdigit() and len(number) >= 12 else None,
        "stored_encrypted": True,
    }


async def _json_request(client: httpx.AsyncClient, method: str, url: str, **kwargs: Any) -> tuple[int, dict[str, Any]]:
    # Bound responses; never include remote error bodies, URLs, or auth headers in exceptions.
    async with client.stream(method, url, follow_redirects=False, **kwargs) as response:
        if response.status_code != 200:
            return response.status_code, {}
        content = bytearray()
        async for chunk in response.aiter_bytes():
            content.extend(chunk)
            if len(content) > MAX_BYTES // 2:
                raise WalletBackendError("Laso card response exceeds size limit.")
        body = json.loads(content)
        if not isinstance(body, dict):
            raise WalletBackendError("Laso returned an invalid card response.")
        return response.status_code, body


async def refresh_record(
    vault: CardVault, reference: str, record: dict[str, Any], *, attempts: int = 1,
    catalog_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Free retrieval. Caller holds the record lock; no owner key is needed to save."""
    catalog = CardCatalog(vault)
    state = catalog_state
    if state is None:
        path = catalog._path(reference)
        try:
            state = catalog.load(reference) if path.exists() or path.is_symlink() else catalog.track(reference, record)
        except WalletBackendError:
            # Owner-only callers already supplied a decrypted record and can rebuild metadata.
            state = catalog.track(reference, record)
    order = record.get("order") or {}
    card_id = card_object(order).get("card_id")
    auth = credentials(record)
    job = state.get("job")
    if isinstance(job, dict) and job.get("card_id") == card_id:
        # A prior process may have saved rotated tokens before writing the owner snapshot.
        auth = credentials({"order": {"auth": job.get("auth")}})
        record.setdefault("order", {})["auth"] = auth
    token = auth.get("id_token")
    if not isinstance(card_id, str) or not 0 < len(card_id) <= 128 or not token or record.get("card_type") not in CARD_TYPES:
        raise WalletBackendError("Saved order has no valid retrieval credentials. Do not purchase again; review the saved order.")
    try:
        async with httpx.AsyncClient(timeout=20, headers={"Accept": "application/json", **LASO_PARTNER_HEADERS}, trust_env=False) as client:
            for attempt in range(attempts):
                if attempt:
                    await asyncio.sleep(MIN_REFRESH_INTERVAL)
                if isinstance(state.get("job"), dict):
                    state["job"]["next_at"] = time.time() + (60 if record["card_type"] == "Non-Reloadable International" else MIN_REFRESH_INTERVAL)
                    count = state["job"].get("attempts", 0)
                    state["job"]["attempts"] = min(100000, max(0, count) + 1) if type(count) is int else 1
                    catalog.save(reference, state)
                code, body = await _json_request(client, "GET", "https://laso.finance/get-card-data", params={"card_id": card_id, "card_type": record["card_type"]}, headers={"Authorization": f"Bearer {token}"})
                if code == 401 and auth.get("refresh_token"):
                    code, fresh = await _json_request(client, "POST", "https://laso.finance/auth", json={"grant_type": "refresh_token", "refresh_token": auth["refresh_token"]})
                    fresh_auth = credentials({"order": {"auth": fresh}})
                    if code != 200 or not fresh_auth.get("id_token"):
                        if code in {400, 401, 403}:
                            state["job"] = None
                            state["refresh_state"] = "credentials_expired"
                            catalog.save(reference, state)
                        raise WalletBackendError("Laso credentials could not be renewed; the encrypted order is preserved.")
                    auth.update(fresh_auth)
                    record["order"]["auth"] = auth
                    if isinstance(state.get("job"), dict):
                        # Durable working credentials first, so a failed owner snapshot can be retried.
                        state["job"]["auth"] = dict(auth)
                        catalog.save(reference, state)
                    vault.store_update(reference, auth=auth)
                    token = auth["id_token"]
                    code, body = await _json_request(client, "GET", "https://laso.finance/get-card-data", params={"card_id": card_id, "card_type": record["card_type"]}, headers={"Authorization": f"Bearer {token}"})
                if code != 200:
                    if code in {401, 403}:
                        state["job"] = None
                        state["refresh_state"] = "credentials_expired"
                        catalog.save(reference, state)
                    raise WalletBackendError("Laso retrieval failed; the encrypted order is preserved. Retry card status later.")
                returned_id = card_object(body).get("card_id")
                if returned_id is not None and returned_id != card_id:
                    raise WalletBackendError("Laso returned a different card ID; the saved order is preserved.")
                record["latest"] = body
                # Seal complete details for the owner before retiring runtime credentials.
                vault.store_update(reference, latest=body, auth=auth)
                catalog.update(reference, state, record)
                if details_ready(record) or not state.get("job") or card_object(body).get("status") != "pending":
                    break
        return record
    except Exception as exc:
        if isinstance(state.get("job"), dict):
            count = state["job"].get("attempts", 1)
            count = min(7, max(1, count)) if type(count) is int else 1
            state["job"]["next_at"] = time.time() + min(300, MIN_REFRESH_INTERVAL * 2 ** count)
            state["refresh_state"] = "retry_later"
            catalog.save(reference, state)
        if isinstance(exc, WalletBackendError):
            raise
        raise WalletBackendError("Laso retrieval failed; the encrypted order is preserved. Retry card status later.") from None


async def refresh_saved_card(vault: CardVault, reference: str) -> dict[str, Any]:
    """Agent entrypoint: retrieve only an already purchased, scoped pending card."""
    catalog = CardCatalog(vault)
    if not catalog._path(reference).exists():
        return catalog.get(reference)
    async with vault.async_record_lock(reference):
        state = catalog.load(reference)
        job = state.get("job")
        if not isinstance(job, dict):
            return catalog.safe(reference, state)
        now = time.time()
        if type(job.get("expires_at")) not in {float, int} or not 946684800 <= job["expires_at"] <= 4133980800 or job["expires_at"] <= now:
            state["job"] = None
            state["refresh_state"] = "credentials_expired"
            catalog.save(reference, state)
            return catalog.safe(reference, state)
        if type(job.get("next_at")) not in {float, int} or not 946684800 <= job["next_at"] <= 4133980800:
            raise WalletBackendError("Invalid pending card schedule.")
        if now < job["next_at"]:
            return catalog.safe(reference, state)
        card_type, card_id = job.get("card_type"), job.get("card_id")
        if not isinstance(card_type, str) or card_type not in CARD_TYPES or not isinstance(card_id, str) or not 0 < len(card_id) <= 128:
            raise WalletBackendError("Invalid pending card retrieval record.")
        record = {"card_type": card_type, "order": {"card_id": card_id, "auth": job.get("auth")}}
        try:
            await refresh_record(vault, reference, record, catalog_state=state)
        except WalletBackendError:
            # Return a stable safe state and retry schedule, never a remote exception body.
            pass
        return catalog.safe(reference, state)


async def capture_request(*, call: Any, user_id: str | None, receipt_reference: str | None = None, **kwargs: Any) -> dict[str, Any]:
    url = kwargs["url"]
    vault = preflight(url, user_id)
    if vault is None:
        return await call(**kwargs)
    path = card_path(url)
    # A durable receipt exists even if settlement, transport, or persistence later fails.
    record = {"type": "laso-card", "card_type": ORDER_PATHS[path], "created_at": datetime.now(timezone.utc).isoformat(), "state": "request_started", "request": {"url": url, "query": kwargs.get("query"), "payment": kwargs.get("approved_preview")}}
    reference = vault.deposit(record, reference=receipt_reference)
    async with vault.async_record_lock(reference):
        try:
            result = await call(**kwargs)
            if result.get("status_code") != 200 or "response_preview" not in result:
                # Quotes and explicit HTTP failures are not card receipts. Preserve
                # the original status/error instead of replacing it with a fake card.
                vault.remove_record(reference)
                return result
            body = result.get("response_preview")
            record.update({"order": body if isinstance(body, dict) else {"unparsed_response": body}, "state": "response_saved", "http_status": result.get("status_code"), "payment_settlement": result.get("payment_settlement")})
            record["payment_result"] = {
                key: result[key] for key in ("paid", "broadcasted", "confirmed") if key in result
            }
            vault.deposit(record, reference=reference)
            catalog = CardCatalog(vault)
            state = catalog.track(reference, record)
            notice = None
            if result.get("status_code") == 200 and path == "/get-card" and not details_ready(record):
                try:
                    record = await refresh_record(vault, reference, record, attempts=5, catalog_state=state)
                except WalletBackendError:
                    notice = "Order saved. Use get_saved_card_status or refresh_saved_card later; do not purchase again."
            safe = {**summary(record, reference), **catalog.safe(reference, state)}
            if notice:
                safe["notice"] = notice
            # Allow no provider response fields into the model, including unexpected nested data.
            result["response_preview"] = safe
            return result
        except Exception as exc:
            record["failure"] = {"type": type(exc).__name__, "details": getattr(exc, "details", None)}
            try:
                vault.deposit(record, reference=reference)
                CardCatalog(vault).track(reference, record)
            except Exception:
                pass
            raise WalletBackendError(f"Laso request outcome needs review. Encrypted receipt: {reference}. Use wallet vault list; do not repeat payment automatically.") from None
