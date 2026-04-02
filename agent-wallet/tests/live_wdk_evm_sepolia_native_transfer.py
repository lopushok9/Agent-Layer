"""Live Sepolia smoke for the local EVM wallet prepare/execute flow.

This test is intentionally stateful:
- it assumes a bound local EVM wallet already exists for the configured user
- it sends a very small amount of Sepolia ETH to a configured recipient
- it verifies the full OpenClaw CLI path: balance -> prepare -> issue-approval -> execute -> receipt
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT))

from _secret_test_utils import install_test_sealed_secrets  # noqa: E402
from agent_wallet.user_wallets import normalize_user_id  # noqa: E402


DEFAULT_USER_ID = "evm-live@example.com"
DEFAULT_NETWORK = "sepolia"
DEFAULT_SERVICE_URL = "http://127.0.0.1:18087"
DEFAULT_RECIPIENT = "0x3333333333333333333333333333333333333333"
DEFAULT_AMOUNT_WEI = "100000000000000"


def _config() -> dict[str, object]:
    return {
        "backend": "wdk_evm_local",
        "network": os.environ.get("OPENCLAW_EVM_TEST_NETWORK", DEFAULT_NETWORK),
        "wdkEvmServiceUrl": os.environ.get(
            "OPENCLAW_EVM_TEST_SERVICE_URL",
            DEFAULT_SERVICE_URL,
        ),
        "wdkEvmAccountIndex": 0,
        "signOnly": False,
    }


def _user_id() -> str:
    return os.environ.get("OPENCLAW_EVM_TEST_USER_ID", DEFAULT_USER_ID)


def _recipient() -> str:
    return os.environ.get("OPENCLAW_EVM_TEST_RECIPIENT", DEFAULT_RECIPIENT)


def _amount_wei() -> str:
    return os.environ.get("OPENCLAW_EVM_TEST_AMOUNT_WEI", DEFAULT_AMOUNT_WEI)


def _run_cli(*args: str) -> dict[str, object]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(PACKAGE_ROOT)
    try:
        completed = subprocess.run(
            [sys.executable, "-m", "agent_wallet.openclaw_cli", *args],
            check=True,
            capture_output=True,
            text=True,
            cwd=str(PACKAGE_ROOT),
            env=env,
        )
    except subprocess.CalledProcessError as exc:  # pragma: no cover - live diagnostics
        raise RuntimeError(
            f"CLI command failed: {' '.join(exc.cmd)}\n"
            f"stdout: {exc.stdout}\n"
            f"stderr: {exc.stderr}"
        ) from exc
    return json.loads(completed.stdout)


def _invoke(tool: str, arguments: dict[str, object]) -> dict[str, object]:
    return _run_cli(
        "invoke",
        "--user-id",
        _user_id(),
        "--tool",
        tool,
        "--arguments-json",
        json.dumps(arguments),
        "--config-json",
        json.dumps(_config()),
    )


def _issue_approval(tool: str, summary: dict[str, object]) -> dict[str, object]:
    return _run_cli(
        "issue-approval",
        "--user-id",
        _user_id(),
        "--tool",
        tool,
        "--summary-json",
        json.dumps(summary),
        "--config-json",
        json.dumps(_config()),
    )


def _require_ok(payload: dict[str, object], label: str) -> dict[str, object]:
    if payload.get("ok") is not True:
        raise RuntimeError(f"{label} failed: {payload}")
    data = payload.get("data")
    if not isinstance(data, dict):
        raise RuntimeError(f"{label} returned invalid data payload: {payload}")
    return data


def _wait_for_receipt(tx_hash: str, *, timeout_seconds: int = 60) -> dict[str, object]:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        receipt_payload = _invoke("get_evm_transaction_receipt", {"tx_hash": tx_hash})
        receipt_data = _require_ok(receipt_payload, "get_evm_transaction_receipt")
        if receipt_data.get("found") is True:
            receipt = receipt_data.get("receipt")
            if isinstance(receipt, dict):
                return receipt_data
        time.sleep(2)
    raise RuntimeError(f"Transaction receipt was not found within {timeout_seconds} seconds: {tx_hash}")


def _prepare_isolated_openclaw_home(temp_home: Path) -> None:
    source_home = Path.home() / ".openclaw"
    source_binding = (
        source_home
        / "users"
        / normalize_user_id(_user_id())
        / "wallets"
        / f"evm-{_config()['network']}-agent.json"
    )
    if not source_binding.exists():
        raise RuntimeError(f"Expected live EVM wallet binding to exist: {source_binding}")

    source_token = source_home / "wdk-evm-wallet" / "local-auth-token"
    if not source_token.exists():
        raise RuntimeError(f"Expected local WDK EVM auth token to exist: {source_token}")

    target_binding = (
        temp_home
        / "users"
        / normalize_user_id(_user_id())
        / "wallets"
        / source_binding.name
    )
    target_binding.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_binding, target_binding)

    target_token = temp_home / "wdk-evm-wallet" / "local-auth-token"
    target_token.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_token, target_token)

    install_test_sealed_secrets(
        temp_home,
        boot_key="live-evm-smoke-boot-key",
        master_key="live-evm-smoke-master-key",
        approval_secret="live-evm-smoke-approval-secret",
    )


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="openclaw-evm-live-smoke-") as temp_dir:
        temp_home = Path(temp_dir)
        _prepare_isolated_openclaw_home(temp_home)

        balance_data = _require_ok(_invoke("get_wallet_balance", {}), "get_wallet_balance")
        assert balance_data["chain"] == "evm"
        assert balance_data["network"] == _config()["network"]
        assert str(balance_data["address"]).startswith("0x")

        prepare_payload = _invoke(
            "transfer_evm_native",
            {
                "recipient": _recipient(),
                "amount_wei": _amount_wei(),
                "mode": "prepare",
                "purpose": "live sepolia native transfer smoke",
                "user_intent": True,
            },
        )
        prepare_data = _require_ok(prepare_payload, "transfer_evm_native prepare")
        assert prepare_data["execution_plan_only"] is True
        assert prepare_data["prepared"] is False
        assert prepare_data["broadcasted"] is False
        assert prepare_data["confirmed"] is False
        assert isinstance(prepare_data.get("confirmation_summary"), dict)

        approval_payload = _issue_approval(
            "transfer_evm_native",
            prepare_data["confirmation_summary"],
        )
        approval_token = str(approval_payload.get("approval_token") or "").strip()
        if not approval_token:
            raise RuntimeError(f"issue-approval did not return an approval_token: {approval_payload}")

        execute_payload = _invoke(
            "transfer_evm_native",
            {
                "recipient": _recipient(),
                "amount_wei": _amount_wei(),
                "mode": "execute",
                "purpose": "live sepolia native transfer smoke",
                "approval_token": approval_token,
            },
        )
        execute_data = _require_ok(execute_payload, "transfer_evm_native execute")
        tx_hash = str(execute_data.get("hash") or "").strip()
        if not tx_hash.startswith("0x"):
            raise RuntimeError(f"execute did not return a transaction hash: {execute_payload}")

        receipt_data = _wait_for_receipt(tx_hash)
        receipt = receipt_data["receipt"]
        assert isinstance(receipt, dict)
        assert receipt.get("transactionHash") == tx_hash
        assert receipt.get("status") == "0x1"

        print(
            json.dumps(
                {
                    "user_id": _user_id(),
                    "network": _config()["network"],
                    "wallet_address": balance_data["address"],
                    "recipient": _recipient(),
                    "amount_wei": _amount_wei(),
                    "tx_hash": tx_hash,
                    "receipt_status": receipt.get("status"),
                },
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
