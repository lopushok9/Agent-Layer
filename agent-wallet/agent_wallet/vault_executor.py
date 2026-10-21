"""Private card use through a fixed HTTPS executor and durable approved operations.

No shell, arbitrary callback, raw provider result or secret value is exposed to
an agent. A prepared request is immutable. Approval covers its exact template;
continuations reuse that authorization without asking the owner to unlock.
"""
from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import json
import re
import socket
import time
import uuid
from typing import Any, Callable
from urllib.parse import urlsplit

import httpx

from agent_wallet.card_catalog import CardCatalog, TERMINAL
from agent_wallet.card_runtime_secrets import CardRuntimeSecrets, RuntimeVaultStorage
from agent_wallet.card_vault import CardVault
from agent_wallet.laso_card_vault import refresh_saved_card
from agent_wallet.wallet_layer.base import WalletBackendError

TOOL_NAME = "use_saved_card"
EXECUTOR = "https_request"
OPERATION_TTL = 48 * 3600
FIELDS = frozenset({"card.number", "card.cvv", "card.exp_month", "card.exp_year", *(
    "card.billing." + key for key in ("name", "line_1", "line_2", "city", "state", "zip", "country")
)})
PLACEHOLDER = re.compile(r"\{\{(card\.[a-z_0-9.]+)\}\}")
FINAL_STATES = frozenset({"request_succeeded", "request_rejected", "outcome_unknown", "expired", "card_unavailable", "issuance_unknown", "cancelled", "checkout_submitted", "checkout_unavailable"})
BLOCKED_HEADERS = frozenset({"host", "content-length", "transfer-encoding", "connection", "upgrade", "te", "trailer", "expect", "proxy-authorization", "proxy-connection", "idempotency-key", "content-type"})


def _encoded(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _url(value: Any) -> httpx.URL:
    if not isinstance(value, str) or not 1 <= len(value) <= 4096 or any(ord(c) <= 32 or ord(c) >= 127 for c in value) or "\\" in value:
        raise WalletBackendError("Executor URL must be an ASCII HTTPS URL.")
    try:
        parsed = urlsplit(value)
        url = httpx.URL(value)
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username is not None
                or parsed.password is not None or parsed.fragment or parsed.port not in {None, 443}
                or url.host.endswith(".") or "{" in value or "}" in value):
            raise ValueError()
    except (ValueError, httpx.InvalidURL):
        raise WalletBackendError("Executor requires an exact public HTTPS destination on port 443 without credentials or fragments.") from None
    return url


def validate_request(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) - {"url", "method", "headers", "json", "form"}:
        raise WalletBackendError("request must contain only url, method, headers and json or form.")
    url = _url(value.get("url"))
    method = value.get("method", "POST")
    if method not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
        raise WalletBackendError("Unsupported HTTPS request method.")
    if ("json" in value) == ("form" in value):
        raise WalletBackendError("Provide exactly one of request.json or request.form.")
    headers = value.get("headers", {})
    if not isinstance(headers, dict) or len(headers) > 32:
        raise WalletBackendError("Invalid request headers.")
    clean_headers: dict[str, str] = {}
    for key, content in headers.items():
        if (not isinstance(key, str) or not re.fullmatch(r"[A-Za-z0-9-]{1,80}", key)
                or key.lower() in BLOCKED_HEADERS or key.lower() in clean_headers
                or not isinstance(content, str) or len(content) > 4096
                or any(ord(c) < 32 or ord(c) > 126 for c in content) or "{{" in content or "}}" in content):
            raise WalletBackendError("Unsafe request header. Card secrets are allowed only in the request body.")
        clean_headers[key.lower()] = content
    kind = "json" if "json" in value else "form"
    body = value[kind]
    if not isinstance(body, dict):
        raise WalletBackendError("The request body must be an object.")
    used: set[str] = set()

    def visit(item: Any, depth: int = 0) -> None:
        if depth > 8:
            raise WalletBackendError("Request template nesting exceeds limit.")
        if isinstance(item, dict):
            if len(item) > 128:
                raise WalletBackendError("Request template exceeds field limit.")
            for key, child in item.items():
                if not isinstance(key, str) or len(key) > 256 or "{{" in key or "}}" in key:
                    raise WalletBackendError("Invalid template field name.")
                visit(child, depth + 1)
        elif isinstance(item, list):
            if len(item) > 128:
                raise WalletBackendError("Request template exceeds field limit.")
            for child in item:
                visit(child, depth + 1)
        elif isinstance(item, str):
            found = PLACEHOLDER.findall(item)
            if set(found) - FIELDS or "{{" in PLACEHOLDER.sub("", item) or "}}" in PLACEHOLDER.sub("", item):
                raise WalletBackendError("Unknown vault placeholder in request template.")
            used.update(found)
        elif item is not None and type(item) not in {int, float, bool}:
            raise WalletBackendError("Invalid request template value.")

    visit(body)
    if kind == "form" and not all(isinstance(v, str) for v in body.values()):
        raise WalletBackendError("Form template values must be strings.")
    if not used:
        raise WalletBackendError("Request template must reference a saved card field such as {{card.number}}.")
    request = {"url": str(url), "method": method, "headers": clean_headers, kind: body}
    try:
        if len(_encoded(request)) > 24 * 1024:
            raise ValueError()
    except (ValueError, TypeError):
        raise WalletBackendError("Request template exceeds size limit or contains invalid numbers.") from None
    return request


def _render(value: Any, fields: dict[str, str]) -> Any:
    if isinstance(value, dict):
        return {key: _render(child, fields) for key, child in value.items()}
    if isinstance(value, list):
        return [_render(child, fields) for child in value]
    if isinstance(value, str):
        def replace(match):
            if match[1] not in fields:
                raise WalletBackendError("The saved card is missing a requested executor field.")
            return fields[match[1]]
        return PLACEHOLDER.sub(replace, value)
    return value


async def resolve_public_destination(url: httpx.URL) -> str:
    """Validate every DNS answer, then connect to a selected IP without re-resolving."""
    try:
        answers = await asyncio.wait_for(asyncio.get_running_loop().getaddrinfo(
            url.host, 443, type=socket.SOCK_STREAM,
        ), timeout=10)
        addresses = sorted({answer[4][0] for answer in answers})
        def public(address: str) -> bool:
            ip = ipaddress.ip_address(address)
            return (ip.is_global and not ip.is_multicast
                    and not (isinstance(ip, ipaddress.IPv6Address)
                             and (ip.ipv4_mapped is not None or ip.sixtofour is not None or ip.teredo is not None)))
        if not addresses or not all(public(address) for address in addresses):
            raise ValueError()
        # Prefer IPv4 on dual-stack hosts; string ordering can otherwise pick
        # IPv6 even when this machine has no usable IPv6 route.
        return min(addresses, key=lambda address: (ipaddress.ip_address(address).version,
                                                   int(ipaddress.ip_address(address))))
    except (ValueError, OSError, asyncio.TimeoutError):
        raise WalletBackendError("HTTPS executor destination must resolve only to public internet addresses.") from None


async def send_private_request(request: dict[str, Any], fields: dict[str, str], *, address: str, operation_id: str) -> int:
    """Only the fixed executor receives plaintext. Return no remote content."""
    url = _url(request["url"])
    pinned = url.copy_with(host=address)
    headers = {**request["headers"], "Host": url.host, "Idempotency-Key": operation_id}
    kind = "json" if "json" in request else "form"
    body = _render(request[kind], fields)
    kwargs = {"json" if kind == "json" else "data": body}
    # Separate pool per operation. TLS verifies the original hostname while the
    # connection is pinned to the validated IP (no second DNS lookup / rebinding).
    async with httpx.AsyncClient(timeout=30, trust_env=False, follow_redirects=False,
                                 transport=httpx.AsyncHTTPTransport(retries=0, trust_env=False)) as client:
        async with client.stream(request["method"], pinned, headers=headers,
                                 extensions={"sni_hostname": url.host}, **kwargs) as response:
            # Do not read a body, cookies, Location or exception text into a tool
            # result. A server may echo credentials even in an error response.
            return response.status_code


class VaultExecutor:
    def __init__(self, vault: CardVault):
        self.vault = vault
        self.storage = RuntimeVaultStorage(vault, "operation")

    def _summary(self, reference: str, state: dict[str, Any]) -> dict[str, Any]:
        checkout = state.get("checkout")
        payload = checkout or state["request"]
        return {
            "operation": "Private Kernel checkout" if checkout else "Private saved card HTTPS request", "operation_id": reference,
            "user_scope": self.vault.scope, "network": state["network"], "owner": state["owner"],
            "vault_reference": state["vault_reference"], "executor": "kernel_checkout" if checkout else EXECUTOR,
            "card_issuance": (state.get("issuance") or {}).get("payment_summary"),
            "purpose": state["purpose"], "destination": checkout["page_url"] if checkout else state["request"]["url"],
            "request": payload,
            "request_sha256": hashlib.sha256(_encoded(payload)).hexdigest(),
            "valid_until_epoch_seconds": state["valid_until"],
            "spend_policy": "exact-request-template; no automatic payment retry",
        }

    def prepare(self, *, vault_reference: Any, request: Any, purpose: Any, network: str, owner: str, mode: str, issuance: dict[str, Any] | None = None, checkout: Any = None) -> dict[str, Any]:
        self.vault._config()
        self.vault._path(vault_reference)
        if issuance is None:
            CardCatalog(self.vault).get(vault_reference)
        if not isinstance(purpose, str) or not 1 <= len(purpose.strip()) <= 512:
            raise WalletBackendError("A clear purpose of up to 512 characters is required.")
        if (checkout is None) == (request is None):
            raise WalletBackendError("Choose exactly one request or checkout plan.")
        if checkout is not None:
            from agent_wallet.kernel_browser import validate_checkout
            checkout = validate_checkout(checkout)
        state = {
            "status": "prepared", "vault_reference": vault_reference,
            "request": validate_request(request) if request is not None else None, "purpose": purpose.strip(),
            "network": network, "owner": owner,
            "valid_until": int(time.time()) + OPERATION_TTL,
            "created_at": int(time.time()), "issuance": issuance,
        }
        if checkout is not None:
            state["checkout"] = checkout
        reference = uuid.uuid4().hex
        state["confirmation_summary"] = self._summary(reference, state)
        self.storage.save(reference, state)
        return {
            **self.safe(reference, state), "mode": mode,
            "confirmation_summary": state["confirmation_summary"],
            "confirmation_requirements": {"execute_requires_approval_token": True},
            "note": "Approve this exact destination and plan through the normal wallet confirmation flow. Real card data goes to the trusted executor and merchant. Status is not independent proof of payment. No owner unlock is needed.",
        }

    def _load(self, reference: str) -> dict[str, Any]:
        state = self.storage.load(reference)
        # Authenticate not only the envelope but the relationship of the saved
        # approval summary to its immutable request, card and runtime identity.
        if state.get("confirmation_summary") != self._summary(reference, state):
            raise WalletBackendError("Saved vault operation does not match its approved request.")
        return state

    @staticmethod
    def safe(reference: str, state: dict[str, Any]) -> dict[str, Any]:
        status = state.get("status")
        if status not in FINAL_STATES and status not in {"dispatching", "issuing"} and time.time() >= state["valid_until"]:
            status = "expired"
        return {
            "operation_id": reference, "vault_reference": state.get("vault_reference"),
            "executor": "kernel_checkout" if state.get("checkout") else EXECUTOR, "status": status,
            "card_issuance_requested": state.get("issuance") is not None,
            "authorization_required": status == "prepared",
            "can_continue": status in {"prepared", "authorized", "awaiting_card", "issuing"},
            "http_status": state.get("http_status"),
            "valid_until_epoch_seconds": state.get("valid_until"),
            "retry_after_seconds": state.get("retry_after_seconds"),
            "last_attempt_not_sent": state.get("last_attempt_not_sent", False),
            "secrets_returned": False, "payment_confirmed": False,
            "merchant_confirmation_observed": state.get("merchant_confirmation_observed", False),
        }

    def get(self, reference: str) -> dict[str, Any]:
        return self.safe(reference, self._load(reference))

    async def _cleanup_browser(self, reference: str, state: dict[str, Any]) -> None:
        if state.get("checkout"):
            from agent_wallet.kernel_browser import KernelBrowser
            try:
                await KernelBrowser(self.vault).cleanup(state["checkout"], reference)
            except Exception:
                pass  # Session stays inaccessible; close can retry remote cleanup.

    async def cancel(self, reference: str) -> dict[str, Any]:
        async with self.vault.async_record_lock(reference):
            state = self._load(reference)
            if state["status"] == "dispatching":
                # A request may already have left the previous process.
                state["status"] = "outcome_unknown"
            elif state["status"] == "issuing":
                state["status"] = "issuance_unknown"
            elif state["status"] not in FINAL_STATES:
                state["status"] = "cancelled"
                state.pop("authorized_at", None)
            self.storage.save(reference, state)
            await self._cleanup_browser(reference, state)
            return self.safe(reference, state)

    async def execute(self, reference: str, *, network: str, owner: str, authorize: Callable[[dict[str, Any]], None], issue_card: Any | None = None) -> dict[str, Any]:
        async with self.vault.async_record_lock(reference):
            state = self._load(reference)
            if state["status"] in FINAL_STATES:
                await self._cleanup_browser(reference, state)
                return self.safe(reference, state)
            if state["status"] == "dispatching":
                # A previous process may have sent the request before it died.
                # Never resend an uncertain payment even with an idempotency key.
                state["status"] = "outcome_unknown"
                self.storage.save(reference, state)
                await self._cleanup_browser(reference, state)
                return self.safe(reference, state)
            if state["network"] != network or state["owner"] != owner:
                raise WalletBackendError("Use the same wallet and network that prepared this vault operation.")
            if time.time() >= state["valid_until"]:
                state["status"] = "expired"
                self.storage.save(reference, state)
                await self._cleanup_browser(reference, state)
                return self.safe(reference, state)
            if state["status"] == "prepared":
                authorize(state["confirmation_summary"])
                state["status"] = "authorized"
                state["authorized_at"] = int(time.time())
                # Durable authorization is bound to this exact request only.
                self.storage.save(reference, state)
            elif state["status"] not in {"authorized", "awaiting_card", "issuing"} or not state.get("authorized_at"):
                raise WalletBackendError("Invalid saved vault operation authorization state.")

            if state.get("checkout"):
                from agent_wallet.kernel_browser import KernelBrowser
                try:
                    await KernelBrowser(self.vault).preflight(state["checkout"], operation_id=reference)
                except Exception:
                    # Do not buy a card when the prepared browser/page is gone.
                    state["status"] = "checkout_unavailable"
                    self.storage.save(reference, state)
                    await self._cleanup_browser(reference, state)
                    return self.safe(reference, state)

            card_ref = state["vault_reference"]
            if state.get("issuance") and not state.get("issuance_completed"):
                if state["status"] == "issuing":
                    # A crash may leave a captured issuer receipt. Never pay twice.
                    try:
                        card = CardCatalog(self.vault).get(card_ref)
                        recovered = card.get("details_stored") or card.get("refresh_available")
                    except WalletBackendError:
                        recovered = False
                    if not recovered:
                        state["status"] = "issuance_unknown"
                        self.storage.save(reference, state)
                        await self._cleanup_browser(reference, state)
                        return self.safe(reference, state)
                else:
                    if issue_card is None:
                        raise WalletBackendError("This operation requires its original card issuance executor.")
                    state["status"] = "issuing"
                    self.storage.save(reference, state)
                    try:
                        await issue_card(state["issuance"], card_ref)
                    except Exception:
                        # Saved issuer receipts can be inspected; no automatic re-purchase.
                        state["status"] = "issuance_unknown"
                        self.storage.save(reference, state)
                        await self._cleanup_browser(reference, state)
                        return self.safe(reference, state)
                state["issuance_completed"] = True
                state["status"] = "authorized"
                self.storage.save(reference, state)
            capsule = CardRuntimeSecrets(self.vault)
            if not capsule.available(card_ref):
                card = await refresh_saved_card(self.vault, card_ref)
                if not capsule.available(card_ref):
                    if card.get("status") in TERMINAL or not card.get("refresh_available"):
                        state["status"] = "card_unavailable"
                    else:
                        state["status"] = "awaiting_card"
                    state["retry_after_seconds"] = card.get("retry_after_seconds")
                    self.storage.save(reference, state)
                    if state["status"] in FINAL_STATES:
                        await self._cleanup_browser(reference, state)
                    return self.safe(reference, state)
            # Card removal and private use serialize on the card's own lock.
            async with self.vault.async_record_lock(card_ref):
                card = CardCatalog(self.vault).get(card_ref)
                if card.get("status") in TERMINAL:
                    state["status"] = "card_unavailable"
                    self.storage.save(reference, state)
                    await self._cleanup_browser(reference, state)
                    return self.safe(reference, state)
                if state.get("checkout"):
                    return await self._execute_checkout(reference, state, capsule)
                url = _url(state["request"]["url"])
                address = await resolve_public_destination(url)
                if time.time() >= state["valid_until"]:
                    state["status"] = "expired"
                    self.storage.save(reference, state)
                    return self.safe(reference, state)
                fields = capsule.load_for_executor(card_ref)
                _render(state["request"].get("json", state["request"].get("form")), fields)
                # Before any request bytes can leave, record the attempt durably.
                state["status"] = "dispatching"
                state.pop("retry_after_seconds", None)
                state.pop("last_attempt_not_sent", None)
                self.storage.save(reference, state)
                try:
                    code = await asyncio.wait_for(send_private_request(
                        state["request"], fields, address=address, operation_id=reference,
                    ), timeout=40)
                    state["http_status"] = code
                    state["status"] = "request_succeeded" if 200 <= code < 300 else "request_rejected"
                except (httpx.ConnectError, httpx.ConnectTimeout):
                    # Fresh client, no proxy, redirects or transport retries:
                    # connection establishment failed before HTTP bytes were sent.
                    # Keep the exact durable authorization for a later explicit
                    # continuation, without retrying inside this invocation.
                    state["status"] = "authorized"
                    state["last_attempt_not_sent"] = True
                    state["retry_after_seconds"] = 5
                except asyncio.CancelledError:
                    state["status"] = "outcome_unknown"
                    self.storage.save(reference, state)
                    raise
                except Exception:
                    # Cancellation/transport failures are uncertain outcomes.
                    # No remote exception text is stored or returned.
                    state["status"] = "outcome_unknown"
                    self.storage.save(reference, state)
                finally:
                    fields.clear()  # Best effort only; Python cannot promise zeroization.
                state["last_attempt_at"] = int(time.time())
                if state["status"] in FINAL_STATES:
                    state["finished_at"] = state["last_attempt_at"]
                self.storage.save(reference, state)
                return self.safe(reference, state)

    async def _execute_checkout(self, reference: str, state: dict[str, Any], capsule: CardRuntimeSecrets) -> dict[str, Any]:
        from agent_wallet.kernel_browser import KernelBrowser

        browser = KernelBrowser(self.vault)
        fields = capsule.load_for_executor(state["vault_reference"])
        selected: list[str] = []
        try:
            selected = browser.select_fields(state["checkout"], fields)
            await browser.preflight(state["checkout"], operation_id=reference)
            if time.time() >= state["valid_until"]:
                state["status"] = "expired"
            else:
                # Persist BEFORE any remote fill: input handlers can cause site effects.
                state["status"] = "dispatching"
                state.pop("retry_after_seconds", None)
                self.storage.save(reference, state)
                result = await browser.checkout(state["checkout"], selected, reference)
                state.update(result)
        except asyncio.CancelledError:
            state["status"] = "outcome_unknown" if state["status"] == "dispatching" else "checkout_unavailable"
            self.storage.save(reference, state)
            raise
        except Exception:
            state["status"] = "outcome_unknown" if state["status"] == "dispatching" else "checkout_unavailable"
        finally:
            selected.clear()
            fields.clear()
            await self._cleanup_browser(reference, state)
        state["finished_at"] = int(time.time())
        self.storage.save(reference, state)
        return self.safe(reference, state)
