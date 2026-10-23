"""Offline security/contract checks for card custody and Laso response isolation."""
from __future__ import annotations

import asyncio
import base64
import copy
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent_wallet.card_vault import CardVault
from agent_wallet import card_vault_cli, laso_card_vault as laso
from agent_wallet.openclaw_adapter import OpenClawWalletAdapter
from agent_wallet.providers import x402
from agent_wallet.wallet_layer.base import WalletBackendError
from smoke_x402_adapter import FakeBackend

PASSWORD = "offline-test-vault-password"
PAN = "4111111111111111"
TOKEN = "test-only-secret-id-token"
READY = {"card": {"card_id": "order-1", "status": "ready", "card_details": {"card_number": PAN, "exp_month": "12", "exp_year": "2030", "cvv": "731", "available_balance": 25}}, "auth": {"id_token": TOKEN, "refresh_token": "test-refresh-token"}, "unexpected": {"secret": TOKEN}}


class FakeSystemStore:
    def __init__(self):
        self.keys = {}
        self.authorized = True
        self.reads = 0
        self.creates = 0

    def create(self, account, key):
        if account in self.keys:
            raise WalletBackendError("Key already exists")
        self.keys[account] = key
        self.creates += 1

    def check(self, account):
        if account not in self.keys:
            raise WalletBackendError("System key unavailable")

    def get(self, account):
        self.check(account)
        self.reads += 1
        if not self.authorized:
            raise WalletBackendError("System authentication denied")
        return self.keys[account]


class VaultChecks(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.env = patch.dict(os.environ, {"OPENCLAW_HOME": str(self.home)})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.master_patch = patch("agent_wallet.card_catalog.resolve_wallet_master_key", return_value="test-runtime-master-material-only")
        self.master_patch.start()
        self.addCleanup(self.master_patch.stop)
        self.runtime_master_patch = patch("agent_wallet.card_runtime_secrets.resolve_wallet_master_key", return_value="test-runtime-master-material-only")
        self.runtime_master_patch.start()
        self.addCleanup(self.runtime_master_patch.stop)
        self.stores = {}
        def system_store(vault):
            return self.stores.setdefault(str(vault.root), FakeSystemStore())
        self.store_patch = patch.object(CardVault, "_system_store", system_store)
        self.store_patch.start()
        self.addCleanup(self.store_patch.stop)
        self.vault = CardVault("alice")
        self.vault.initialize(PASSWORD)
        self.key = self.vault.unlock(PASSWORD)

    def test_encryption_permissions_and_password(self):
        ref = self.vault.deposit(READY)
        self.assertEqual(self.vault.read(ref, self.key), READY)
        for file in self.vault.root.iterdir():
            self.assertNotIn(PAN, file.read_text())
            self.assertNotIn(TOKEN, file.read_text())
            self.assertEqual(file.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.vault.root.stat().st_mode & 0o777, 0o700)
        with self.assertRaises(WalletBackendError):
            self.vault.unlock("wrong password")
        with self.assertRaises(FileExistsError):
            self.vault.initialize("different long password")
        self.assertEqual(self.vault.read(ref, self.vault.unlock(PASSWORD)), READY)

    def test_tamper_and_record_swap_are_rejected(self):
        ref = self.vault.deposit(READY)
        other = self.vault.deposit({"status": "pending"})
        self.vault._path(other).write_bytes(self.vault._path(ref).read_bytes())
        with self.assertRaises(WalletBackendError):
            self.vault.read(other, self.key)
        envelope = json.loads(self.vault._path(ref).read_text())
        data = bytearray(base64.b64decode(envelope["sealed"]))
        data[-1] ^= 1
        envelope["sealed"] = base64.b64encode(data).decode()
        self.vault._path(ref).write_text(json.dumps(envelope))
        with self.assertRaises(WalletBackendError):
            self.vault.read(ref, self.key)

    def test_cross_user_and_paths(self):
        bob = CardVault("bob")
        bob.initialize(PASSWORD)
        ref = self.vault.deposit(READY)
        bob._path(ref).write_bytes(self.vault._path(ref).read_bytes())
        bob._path(ref).chmod(0o600)
        with self.assertRaises(WalletBackendError):
            bob.read(ref, bob.unlock(PASSWORD))
        for ref in ["../vault.json", "/tmp/card", "a" * 33]:
            with self.assertRaises(WalletBackendError):
                self.vault.read(ref, self.key)

    def test_unsafe_file_and_symlink(self):
        ref = self.vault.deposit(READY)
        path = self.vault._path(ref)
        path.chmod(0o644)
        with self.assertRaises(WalletBackendError):
            self.vault.read(ref, self.key)
        path.unlink()
        path.symlink_to(self.vault.config_path)
        with self.assertRaises(WalletBackendError):
            self.vault.read(ref, self.key)

    async def test_capture_never_returns_provider_secrets(self):
        call = AsyncMock(return_value={"status_code": 200, "paid": True, "confirmed": True, "response_preview": copy.deepcopy(READY)})
        result = await laso.capture_request(call=call, user_id="alice", url="https://laso.finance/get-card")
        output = json.dumps(result)
        self.assertNotIn(PAN, output)
        self.assertNotIn(TOKEN, output)
        # A three-digit CVV can occur coincidentally in a timestamp or UUID.
        # Reject the secret-bearing field; PAN/token checks above cover values.
        self.assertNotIn('"cvv"', output.lower())
        safe = result["response_preview"]
        self.assertEqual(safe["last4"], "1111")
        self.assertTrue(result["confirmed"])
        self.assertEqual(self.vault.read(safe["vault_reference"], self.key)["order"], READY)

    async def test_preflight_blocks_before_network_or_payment(self):
        call = AsyncMock()
        with patch.object(CardVault, "_system_store", side_effect=WalletBackendError("OS Keychain unavailable")):
            with self.assertRaises(WalletBackendError):
                await laso.capture_request(call=call, user_id="missing-user", url="https://laso.finance/get-card")
        call.assert_not_awaited()
        for url in ["https://laso.finance/get-card-data", "http://laso.finance/get-card", "https://laso.finance:443/get-card", "https://www.laso.finance/get-card", "https://laso.finance/%67et-card", "https://laso.finance/a/../get-card"]:
            with self.assertRaises(WalletBackendError):
                await laso.capture_request(call=call, user_id="alice", url=url)
        call.assert_not_awaited()

    async def test_402_and_non_laso_keep_payment_contract(self):
        quote = {"payment_required": True, "selected_payment": {"amount": "25000000"}, "response_headers": {"payment-required": "encoded-challenge"}}
        result = await laso.capture_request(call=AsyncMock(return_value=quote), user_id="alice", url="https://laso.finance/get-card")
        self.assertEqual(result, quote)
        self.assertEqual(self.vault.references(), [])
        other = {"response_preview": {"report": "test"}}
        self.assertEqual(await laso.capture_request(call=AsyncMock(return_value=other), user_id=None, url="https://example.com/report"), other)

    async def test_uncertain_payment_keeps_receipt_and_sanitizes_errors(self):
        with self.assertRaises(WalletBackendError) as raised:
            await laso.capture_request(call=AsyncMock(side_effect=RuntimeError(TOKEN + PAN)), user_id="alice", url="https://laso.finance/get-card")
        self.assertNotIn(TOKEN, str(raised.exception))
        refs = self.vault.references()
        self.assertEqual(len(refs), 1)
        self.assertEqual(self.vault.read(refs[0], self.key)["state"], "request_started")

    async def test_pending_order_survives_retrieval_failure(self):
        pending = copy.deepcopy(READY)
        pending["card"].pop("card_details")
        pending["card"]["status"] = "pending"
        with patch.object(laso, "refresh_record", AsyncMock(side_effect=WalletBackendError("offline"))):
            result = await laso.capture_request(call=AsyncMock(return_value={"status_code": 200, "response_preview": pending}), user_id="alice", url="https://laso.finance/get-card")
        ref = result["response_preview"]["vault_reference"]
        self.assertIn("do not purchase again", result["response_preview"]["notice"])
        self.assertEqual(self.vault.read(ref, self.key)["order"]["auth"]["id_token"], TOKEN)

    async def test_token_rotation_saved_before_retrieval_retry(self):
        record = {"order": copy.deepcopy(READY), "card_type": "Non-Reloadable International"}
        ref = self.vault.deposit(record)
        async def fake_request(client, method, url, **kwargs):
            if method == "POST":
                self.assertEqual(url, "https://laso.finance/auth")
                return 200, {"id_token": "new-token", "refresh_token": "rotated-token"}
            if kwargs["headers"]["Authorization"] == f"Bearer {TOKEN}":
                return 401, {}
            saved = self.vault.read(ref, self.key)
            self.assertEqual(saved["order"]["auth"]["refresh_token"], "rotated-token")
            return 200, copy.deepcopy(READY["card"])
        with patch.object(laso, "_json_request", fake_request):
            result = await laso.refresh_record(self.vault, ref, record)
        self.assertEqual(result["latest"]["status"], "ready")
        self.assertEqual(self.vault.read(ref, self.key)["order"]["auth"]["id_token"], "new-token")

    async def test_adapter_contract_is_private_and_user_scoped(self):
        adapter = OpenClawWalletAdapter(FakeBackend(), user_id="alice")
        kwargs = {"url": "https://laso.finance/order-intl-card", "purpose": "offline test"}
        with patch.object(x402, "resolve_payment_preview", AsyncMock(return_value={"payment_required": False})), patch.object(x402, "pay_and_fetch", AsyncMock(return_value={"status_code": 200, "response_preview": copy.deepcopy(READY)})):
            result = await adapter.invoke("x402_pay_request", kwargs)
        self.assertTrue(result.ok, result.error)
        self.assertNotIn(TOKEN, result.model_dump_json())
        self.assertNotIn(PAN, result.model_dump_json())
        blocked = await adapter.invoke("x402_preview_request", {"url": "https://laso.finance/get-card-data"})
        self.assertFalse(blocked.ok)

    def test_owner_can_reveal_and_export_without_provider_tokens(self):
        ref = self.vault.deposit({"order": READY})
        with patch.object(card_vault_cli, "require_terminal"), patch.object(card_vault_cli.getpass, "getpass", return_value=PASSWORD), redirect_stdout(io.StringIO()) as output:
            code = card_vault_cli.main(["reveal", ref, "--user-id", "alice"])
        self.assertEqual(code, 0)
        payload = json.loads(output.getvalue())
        self.assertEqual(payload["card_details"]["card_number"], PAN)
        self.assertNotIn(TOKEN, output.getvalue())
        destination = self.home / "export.json"
        with patch.object(card_vault_cli, "require_terminal"), patch.object(card_vault_cli.getpass, "getpass", return_value=PASSWORD), redirect_stdout(io.StringIO()):
            code = card_vault_cli.main(["reveal", ref, "--user-id", "alice", "--output", str(destination)])
        self.assertEqual(code, 0)
        self.assertEqual(destination.stat().st_mode & 0o777, 0o600)
        original = destination.read_bytes()
        with patch.object(card_vault_cli, "require_terminal"), patch.object(card_vault_cli.getpass, "getpass", return_value=PASSWORD), redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            code = card_vault_cli.main(["reveal", ref, "--user-id", "alice", "--output", str(destination)])
        self.assertEqual(code, 1)
        self.assertEqual(destination.read_bytes(), original)

    def test_system_migration_keeps_existing_cards(self):
        ref = self.vault.deposit({"order": READY})
        original_key = bytes(self.key)
        with patch.object(card_vault_cli, "require_terminal"), patch.object(card_vault_cli.getpass, "getpass", return_value=PASSWORD), redirect_stdout(io.StringIO()):
            code = card_vault_cli.main(["migrate", "--user-id", "alice"])
        self.assertEqual(code, 0)
        self.assertEqual(bytes(self.vault.unlock()), original_key)
        self.assertEqual(self.vault.read(ref, self.vault.unlock())["order"], READY)
        config = self.vault._config()
        self.assertEqual(config["version"], 2)
        self.assertNotIn("private_key", config)
        self.assertNotIn("kdf", config)

    def test_migration_denial_keeps_old_password_and_cards(self):
        ref = self.vault.deposit(READY)
        store = self.vault._system_store()
        store.authorized = False
        before = self.vault.config_path.read_bytes()
        with self.assertRaises(WalletBackendError):
            self.vault.migrate_to_system(PASSWORD)
        self.assertEqual(self.vault.config_path.read_bytes(), before)
        self.assertEqual(self.vault.read(ref, self.vault.unlock(PASSWORD)), READY)

    def test_system_provisioning_is_idempotent_and_never_reads_key(self):
        vault = CardVault("fresh-user")
        result = vault.ensure_system()
        self.assertTrue(result["created"])
        before = vault.config_path.read_bytes()
        again = vault.ensure_system()
        store = vault._system_store()
        self.assertFalse(again["created"])
        self.assertEqual(vault.config_path.read_bytes(), before)
        self.assertEqual(store.creates, 1)
        self.assertEqual(store.reads, 0)
        ref = vault.deposit(READY)
        vault.check_ready()
        self.assertEqual(store.reads, 0)
        store.authorized = False
        with self.assertRaises(WalletBackendError):
            vault.unlock()
        store.authorized = True
        self.assertEqual(vault.read(ref, vault.unlock()), READY)

    async def test_first_card_request_auto_provisions_without_owner_unlock(self):
        quote = {"payment_required": True}
        result = await laso.capture_request(call=AsyncMock(return_value=quote), user_id="fresh-runtime-user", url="https://laso.finance/get-card")
        self.assertEqual(result, quote)
        vault = CardVault("fresh-runtime-user")
        self.assertEqual(vault._config()["version"], 2)
        self.assertEqual(vault._system_store().reads, 0)

    def test_no_key_recreation_when_keychain_entry_is_missing(self):
        vault = CardVault("missing-system-key")
        vault.ensure_system()
        ref = vault.deposit(READY)
        vault._system_store().keys.clear()
        before = vault.config_path.read_bytes()
        with self.assertRaises(WalletBackendError):
            vault.ensure_system()
        self.assertEqual(vault.config_path.read_bytes(), before)
        self.assertTrue(vault._path(ref).exists())

    def test_provision_cli_needs_neither_tty_nor_password(self):
        with patch.object(sys.stdin, "isatty", return_value=False), patch.object(card_vault_cli.getpass, "getpass", side_effect=AssertionError("No password during install")), redirect_stdout(io.StringIO()) as output:
            code = card_vault_cli.main(["provision", "--user-id", "installer-user"])
        self.assertEqual(code, 0)
        self.assertTrue(json.loads(output.getvalue())["created"])
        self.assertEqual(CardVault("installer-user")._system_store().reads, 0)

    async def test_failed_token_rotation_does_not_overwrite_order(self):
        record = {"order": copy.deepcopy(READY), "card_type": "Non-Reloadable International"}
        ref = self.vault.deposit(record)
        with patch.object(laso, "_json_request", AsyncMock(side_effect=[(401, {}), (403, {})])):
            with self.assertRaises(WalletBackendError):
                await laso.refresh_record(self.vault, ref, record)
        self.assertEqual(self.vault.read(ref, self.key), record)

    def test_cli_rejects_pipes_and_exports_without_authentication(self):
        ref = self.vault.deposit({"order": READY})
        with patch.object(sys.stdin, "isatty", return_value=False), redirect_stdout(io.StringIO()) as output, redirect_stderr(io.StringIO()):
            code = card_vault_cli.main(["reveal", ref, "--user-id", "alice", "--output", str(self.home / "export.json")])
        self.assertEqual(code, 1)
        self.assertFalse((self.home / "export.json").exists())
        self.assertNotIn(PAN, output.getvalue())


if __name__ == "__main__":
    unittest.main()
