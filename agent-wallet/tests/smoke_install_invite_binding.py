"""Smoke tests for welcome-invite binding in the wallet installer."""

from __future__ import annotations

import importlib.util
import json
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location(
    "install_agent_wallet_invite",
    ROOT / "scripts" / "install_agent_wallet.py",
)
installer = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(installer)  # type: ignore[union-attr]

INVITE = "alw_" + ("A" * 43)
ADDRESS = "0x1111111111111111111111111111111111111111"


class _Response:
    def __init__(self, payload: dict[str, object], status: int = 200) -> None:
        self.payload = payload
        self.status = status

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self, _limit: int) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


def main() -> None:
    parsed = installer.build_parser().parse_args(["--invite", INVITE])
    assert parsed.invite == INVITE

    captured: dict[str, object] = {}

    def successful_opener(request: object, *, timeout: float) -> _Response:
        captured["request"] = request
        captured["timeout"] = timeout
        return _Response(
            {
                "ok": True,
                "status": "bound",
                "network": "base",
                "address": ADDRESS,
            }
        )

    result = installer._bind_welcome_invite(
        INVITE,
        ADDRESS,
        api_url="https://onboarding.example/api/onboarding/bind-wallet",
        opener=successful_opener,
    )
    assert result == {
        "ok": True,
        "status": "bound",
        "network": "base",
        "address": ADDRESS,
    }
    assert INVITE not in json.dumps(result)
    request = captured["request"]
    assert request.full_url == "https://onboarding.example/api/onboarding/bind-wallet"
    assert request.get_method() == "POST"
    assert request.get_header("Authorization") == f"Bearer {INVITE}"
    assert json.loads(request.data) == {"address": ADDRESS}
    assert captured["timeout"] == installer.ONBOARDING_HTTP_TIMEOUT_SECONDS

    calls = 0

    def retrying_opener(request: object, *, timeout: float) -> _Response:
        nonlocal calls
        del request, timeout
        calls += 1
        if calls == 1:
            raise urllib.error.URLError("temporary network failure")
        return _Response(
            {
                "ok": True,
                "status": "already_bound",
                "network": "base",
                "address": ADDRESS,
            }
        )

    retried = installer._bind_welcome_invite(
        INVITE,
        ADDRESS,
        opener=retrying_opener,
    )
    assert calls == 2
    assert retried["ok"] is True
    assert retried["status"] == "already_bound"

    invalid = installer._bind_welcome_invite(
        "alw_short",
        ADDRESS,
        opener=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("invalid invites must not reach the network")
        ),
    )
    assert invalid == {
        "ok": False,
        "status": "invalid_invite",
        "retryable": False,
    }

    pending = installer._bind_invite_after_evm_onboard(
        INVITE,
        {"ok": False, "error": "wallet unavailable"},
    )
    assert pending == {
        "ok": False,
        "status": "pending_evm_wallet",
        "retryable": True,
    }
    assert INVITE not in json.dumps(pending)

    print("smoke_install_invite_binding: ok")


if __name__ == "__main__":
    main()
