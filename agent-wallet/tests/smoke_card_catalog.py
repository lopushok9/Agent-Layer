"""Offline contracts for agent catalog, delegated pending retrieval and owner isolation."""
from __future__ import annotations

import asyncio
import base64
import copy
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from nacl.public import PrivateKey
from agent_wallet import laso_card_vault as laso
from agent_wallet.card_catalog import CardCatalog, JOB_TTL
from agent_wallet.card_vault import CardVault
from agent_wallet.openclaw_adapter import OpenClawWalletAdapter
from agent_wallet.providers import x402
from agent_wallet.wallet_layer.base import WalletBackendError
from smoke_card_vault import FakeSystemStore, FakeBackend, READY, TOKEN, PAN


class CatalogChecks(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.env = patch.dict(os.environ, {"OPENCLAW_HOME": self.temp.name})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.master = patch("agent_wallet.card_catalog.resolve_wallet_master_key", return_value="offline-test-runtime-master")
        self.master.start()
        self.addCleanup(self.master.stop)
        self.runtime_master = patch("agent_wallet.card_runtime_secrets.resolve_wallet_master_key", return_value="offline-test-runtime-master")
        self.runtime_master.start()
        self.addCleanup(self.runtime_master.stop)
        self.stores = {}
        def store(vault):
            return self.stores.setdefault(str(vault.root), FakeSystemStore())
        self.store_patch = patch.object(CardVault, "_system_store", store)
        self.store_patch.start()
        self.addCleanup(self.store_patch.stop)
        self.vault = CardVault("owner")
        self.vault.ensure_system()
        # Test-only access to verify final owner ciphertext; not through the production unlock path.
        key_bytes = next(iter(self.vault._system_store().keys.values()))
        self.owner_key = PrivateKey(key_bytes)
        self.vault._system_store().authorized = False
        self.catalog = CardCatalog(self.vault)
        self.adapter = OpenClawWalletAdapter(FakeBackend(), user_id="owner")
        self.now = [time.time()]
        self.clock = patch("time.time", side_effect=lambda: self.now[0])
        self.clock.start()
        self.addCleanup(self.clock.stop)
        self.no_unlock = patch.object(CardVault, "unlock", side_effect=AssertionError("Agent must never unlock owner Keychain"))
        self.no_unlock.start()
        self.addCleanup(self.no_unlock.stop)

    def pending_record(self):
        body = copy.deepcopy(READY)
        body["card"].pop("card_details")
        body["card"]["status"] = "queued"
        return {"card_type": "Non-Reloadable International", "order": body}

    def pending(self):
        record = self.pending_record()
        ref = self.vault.deposit(record)
        self.catalog.track(ref, record)
        return ref

    async def invoke(self, name, **arguments):
        result = await self.adapter.invoke(name, arguments)
        self.assertTrue(result.ok, result.error)
        text = result.model_dump_json()
        for secret in (PAN, TOKEN, "test-refresh-token", "new-private-id", "new-private-refresh"):
            self.assertNotIn(secret, text)
        return result.data

    async def test_queued_capture_and_catalog_without_owner_access(self):
        result = await laso.capture_request(call=AsyncMock(return_value={"status_code": 200, "paid": True, "response_preview": self.pending_record()["order"]}), user_id="owner", url="https://laso.finance/order-intl-card")
        ref = result["response_preview"]["vault_reference"]
        cards = await self.invoke("list_saved_cards")
        self.assertEqual(cards["cards"][0]["vault_reference"], ref)
        self.assertEqual(cards["cards"][0]["status"], "queued")
        self.assertTrue(cards["cards"][0]["refresh_available"])
        for path in self.vault.root.glob("*.agent"):
            text = path.read_text()
            self.assertNotIn(TOKEN, text)
            self.assertNotIn(PAN, text)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.vault._system_store().reads, 0)

    async def test_expired_token_pending_then_ready_across_sessions(self):
        ref = self.pending()
        original_receipt = self.vault._path(ref).read_bytes()
        queued = {"card_id": "order-1", "status": "queued"}
        responses = AsyncMock(side_effect=[(401, {}), (200, {"id_token": "new-private-id", "refresh_token": "new-private-refresh"}), (200, queued), (200, copy.deepcopy(READY["card"]))])
        with patch.object(laso, "_json_request", responses), patch.object(x402, "pay_and_fetch", side_effect=AssertionError("Refresh cannot purchase")):
            pending = await self.invoke("get_saved_card_status", vault_reference=ref)
            self.assertEqual(pending["status"], "queued")
            self.assertGreater(pending["retry_after_seconds"], 0)
            state = self.catalog.load(ref)
            self.assertEqual(state["job"]["auth"]["refresh_token"], "new-private-refresh")
            self.assertEqual(self.vault.read(ref, self.owner_key)["order"]["auth"]["id_token"], "new-private-id")
            await self.invoke("refresh_saved_card", vault_reference=ref)
            self.assertEqual(responses.await_count, 3)
            self.now[0] += 61
            self.adapter = OpenClawWalletAdapter(FakeBackend(), user_id="owner")
            ready = await self.invoke("refresh_saved_card", vault_reference=ref)
            self.assertEqual(ready["status"], "ready")
            self.assertTrue(ready["details_stored"])
            self.assertEqual(ready["last4"], "1111")
            self.assertFalse(ready["refresh_available"])
            self.assertIsNone(self.catalog.load(ref)["job"])
            self.assertNotIn("new-private-id", json.dumps(self.catalog.load(ref)))
            await self.invoke("get_saved_card_status", vault_reference=ref)
            self.assertEqual(responses.await_count, 4)
        self.assertEqual(self.vault._path(ref).read_bytes(), original_receipt)
        owner = self.vault.read(ref, self.owner_key)
        self.assertEqual(owner["latest"]["card_details"]["card_number"], PAN)
        self.assertEqual(owner["order"]["auth"]["refresh_token"], "new-private-refresh")
        self.assertEqual(self.vault._system_store().reads, 0)
        self.assertEqual(responses.await_args_list[1].args[1:3], ("POST", "https://laso.finance/auth"))

    async def test_cached_status_never_contacts_issuer(self):
        ref = self.pending()
        with patch.object(laso, "_json_request", side_effect=AssertionError("Cached reads must not use HTTP")):
            await self.invoke("get_saved_card_status", vault_reference=ref, refresh=False)
            await self.invoke("list_saved_cards")

    async def test_transient_failure_has_safe_backoff(self):
        ref = self.pending()
        responses = AsyncMock(side_effect=RuntimeError(PAN + TOKEN))
        with patch.object(laso, "_json_request", responses):
            failed = await self.invoke("refresh_saved_card", vault_reference=ref)
            self.assertEqual(failed["refresh_state"], "retry_later")
            self.assertGreater(failed["retry_after_seconds"], 0)
            await self.invoke("refresh_saved_card", vault_reference=ref)
            self.assertEqual(responses.await_count, 1)
        self.assertIsNotNone(self.catalog.load(ref)["job"])

    async def test_rotation_survives_owner_snapshot_failure(self):
        ref = self.pending()
        responses = AsyncMock(side_effect=[(401, {}), (200, {"id_token": "new-private-id", "refresh_token": "new-private-refresh"})])
        with patch.object(laso, "_json_request", responses), patch.object(self.vault.__class__, "store_update", side_effect=WalletBackendError("simulated disk failure")):
            failed = await self.invoke("refresh_saved_card", vault_reference=ref)
        self.assertEqual(failed["refresh_state"], "retry_later")
        self.assertEqual(self.catalog.load(ref)["job"]["auth"]["id_token"], "new-private-id")
        self.now[0] += 301
        async def retry(client, method, url, **kwargs):
            self.assertEqual(kwargs["headers"]["Authorization"], "Bearer new-private-id")
            return 200, copy.deepcopy(READY["card"])
        with patch.object(laso, "_json_request", retry):
            ready = await self.invoke("refresh_saved_card", vault_reference=ref)
        self.assertTrue(ready["details_stored"])
        self.assertEqual(self.vault.read(ref, self.owner_key)["latest"]["card_details"]["card_number"], PAN)

    async def test_expired_working_credentials_are_retired(self):
        ref = self.pending()
        self.now[0] += JOB_TTL + 1
        with patch.object(laso, "_json_request", side_effect=AssertionError("Expired job must not request")):
            result = await self.invoke("get_saved_card_status", vault_reference=ref)
        self.assertEqual(result["refresh_state"], "credentials_expired")
        self.assertFalse(result["refresh_available"])
        self.assertIsNone(self.catalog.load(ref)["job"])
        self.assertNotIn(TOKEN, json.dumps(self.catalog.load(ref)))

    async def test_terminal_status_retires_working_credentials(self):
        ref = self.pending()
        responses = AsyncMock(return_value=(200, {"card_id": "order-1", "status": "cancelled"}))
        with patch.object(laso, "_json_request", responses):
            result = await self.invoke("refresh_saved_card", vault_reference=ref)
            await self.invoke("refresh_saved_card", vault_reference=ref)
        self.assertEqual(result["status"], "cancelled")
        self.assertEqual(responses.await_count, 1)
        self.assertIsNone(self.catalog.load(ref)["job"])

    async def test_wrong_issuer_card_is_never_saved(self):
        ref = self.pending()
        wrong = copy.deepcopy(READY["card"])
        wrong["card_id"] = "different-order"
        with patch.object(laso, "_json_request", AsyncMock(return_value=(200, wrong))):
            result = await self.invoke("refresh_saved_card", vault_reference=ref)
        self.assertFalse(result["details_stored"])
        self.assertEqual(result["refresh_state"], "retry_later")
        self.assertNotIn("latest", self.vault.read(ref, self.owner_key))

    async def test_concurrent_refreshes_do_not_block_loop_or_repeat_http(self):
        ref = self.pending()
        async def response(*args, **kwargs):
            await asyncio.sleep(0.05)
            return 200, copy.deepcopy(READY["card"])
        request = AsyncMock(side_effect=response)
        with patch.object(laso, "_json_request", request):
            results = await asyncio.wait_for(asyncio.gather(
                self.invoke("refresh_saved_card", vault_reference=ref),
                self.invoke("refresh_saved_card", vault_reference=ref),
            ), timeout=3)
        self.assertEqual(request.await_count, 1)
        self.assertTrue(all(result["details_stored"] for result in results))

    async def test_incomplete_ready_response_keeps_retrieval_capability(self):
        ref = self.pending()
        incomplete = {"card_id": "order-1", "status": "ready", "card_details": {"card_number": PAN}}
        with patch.object(laso, "_json_request", AsyncMock(side_effect=[(200, incomplete), (200, copy.deepcopy(READY["card"]))])):
            first = await self.invoke("refresh_saved_card", vault_reference=ref)
            self.assertFalse(first["details_stored"])
            self.assertTrue(first["refresh_available"])
            self.assertNotIn(PAN, json.dumps(self.catalog.load(ref)))
            self.now[0] += 61
            final = await self.invoke("refresh_saved_card", vault_reference=ref)
        self.assertTrue(final["details_stored"])
        self.assertFalse(final["refresh_available"])

    async def test_failed_catalog_commit_preserves_details_and_retry_credentials(self):
        ref = self.pending()
        original_save = CardCatalog.save
        failures = [1]
        def fail_final_once(catalog, reference, state):
            if state.get("job") is None and state.get("entry", {}).get("details_stored") and failures[0]:
                failures[0] -= 1
                raise WalletBackendError("simulated catalog write failure")
            return original_save(catalog, reference, state)
        with patch.object(CardCatalog, "save", fail_final_once), patch.object(laso, "_json_request", AsyncMock(return_value=(200, copy.deepcopy(READY["card"])))):
            failed = await self.invoke("refresh_saved_card", vault_reference=ref)
            self.assertEqual(failed["refresh_state"], "retry_later")
            self.assertIsNotNone(self.catalog.load(ref)["job"])
            self.assertEqual(self.vault.read(ref, self.owner_key)["latest"]["card_details"]["card_number"], PAN)
            self.now[0] += 301
            result = await self.invoke("refresh_saved_card", vault_reference=ref)
        self.assertTrue(result["details_stored"])
        self.assertIsNone(self.catalog.load(ref)["job"])

    async def test_runtime_encryption_must_be_available_before_purchase(self):
        call = AsyncMock()
        with patch("agent_wallet.card_catalog.resolve_wallet_master_key", return_value=""):
            with self.assertRaises(WalletBackendError):
                await laso.capture_request(call=call, user_id="owner", url="https://laso.finance/get-card")
        call.assert_not_awaited()

    async def test_auth_denial_does_not_loop_on_revoked_credentials(self):
        ref = self.pending()
        request = AsyncMock(side_effect=[(401, {}), (401, {})])
        with patch.object(laso, "_json_request", request):
            result = await self.invoke("refresh_saved_card", vault_reference=ref)
            await self.invoke("refresh_saved_card", vault_reference=ref)
        self.assertEqual(result["refresh_state"], "credentials_expired")
        self.assertEqual(request.await_count, 2)
        self.assertIsNone(self.catalog.load(ref)["job"])

    async def test_cross_user_reference_and_catalog_swap_are_rejected(self):
        ref = self.pending()
        bob = CardVault("bob")
        bob.ensure_system()
        bob_ref = bob.deposit(self.pending_record())
        CardCatalog(bob).track(bob_ref, self.pending_record())
        with patch.object(laso, "_json_request", side_effect=AssertionError("Foreign references must not fetch")):
            foreign = await self.adapter.invoke("refresh_saved_card", {"vault_reference": bob_ref})
            self.assertFalse(foreign.ok)
        self.catalog._path(ref).write_bytes(CardCatalog(bob)._path(bob_ref).read_bytes())
        with self.assertRaises(WalletBackendError):
            self.catalog.load(ref)
        bob_same = bob.deposit(self.pending_record(), reference=ref)
        CardCatalog(bob).save(bob_same, {"entry": {}, "job": None})
        self.catalog._path(ref).write_bytes(CardCatalog(bob)._path(ref).read_bytes())
        with self.assertRaises(WalletBackendError):
            self.catalog.load(ref)

    async def test_metadata_output_is_allowlisted(self):
        ref = self.pending()
        state = self.catalog.load(ref)
        state["entry"].update({"status": {"card_number": PAN}, "last4": PAN, "auth": TOKEN, "balance": PAN, "label": TOKEN})
        state["unexpected"] = {"cvv": "123", "auth": TOKEN}
        self.catalog.save(ref, state)
        result = await self.invoke("get_saved_card_status", vault_reference=ref, refresh=False)
        self.assertEqual(result["status"], "unknown")
        self.assertIsNone(result["last4"])
        self.assertIsNone(result["available_balance"])

    async def test_pagination_legacy_entries_and_validation(self):
        refs = sorted([self.pending(), self.pending(), self.vault.deposit(self.pending_record())])
        first = await self.invoke("list_saved_cards", limit=2)
        second = await self.invoke("list_saved_cards", limit=2, after=first["next_cursor"])
        found = [item["vault_reference"] for item in first["cards"] + second["cards"]]
        self.assertEqual(found, refs)
        self.assertIsNone(second["next_cursor"])
        legacy = self.catalog.get(next(ref for ref in refs if not self.catalog._path(ref).exists()))
        self.assertEqual(legacy["refresh_state"], "owner_access_required")
        for arguments in ({"limit": True}, {"limit": 101}, {"after": "../vault.json"}):
            result = await self.adapter.invoke("list_saved_cards", arguments)
            self.assertFalse(result.ok)
        for name in ("get_saved_card_status", "refresh_saved_card"):
            result = await self.adapter.invoke(name, {"vault_reference": "../vault.json"})
            self.assertFalse(result.ok)

    async def test_deleted_records_cannot_be_refreshed(self):
        ref = self.pending()
        self.vault.store_update(ref, latest={"status": "queued"}, auth={"id_token": TOKEN})
        with self.vault.record_lock(ref):
            self.vault.remove_record(ref)
        for suffix in (".card", ".agent", ".auth", ".update"):
            self.assertFalse(self.vault._path(ref).with_suffix(suffix).exists())
        with patch.object(laso, "_json_request", side_effect=AssertionError("Deleted record must not request")):
            result = await self.adapter.invoke("refresh_saved_card", {"vault_reference": ref})
        self.assertFalse(result.ok)

    def test_auth_rotation_does_not_erase_saved_card_snapshot(self):
        ref = self.pending()
        self.vault.store_update(ref, latest=copy.deepcopy(READY["card"]), auth={"id_token": TOKEN})
        self.vault.store_update(ref, auth={"id_token": "new-private-id"})
        owner = self.vault.read(ref, self.owner_key)
        self.assertEqual(owner["latest"]["card_details"]["card_number"], PAN)
        self.assertEqual(owner["order"]["auth"]["id_token"], "new-private-id")

    def test_encrypted_parts_cannot_be_substituted(self):
        ref = self.pending()
        self.vault._path(ref).with_suffix(".update").write_bytes(self.vault._path(ref).read_bytes())
        self.vault._path(ref).with_suffix(".update").chmod(0o600)
        with self.assertRaises(WalletBackendError):
            self.vault.read(ref, self.owner_key)

    def test_openclaw_tool_schemas_match_python_contract(self):
        repo = Path(__file__).resolve().parents[2]
        source = (repo / ".openclaw/extensions/agent-wallet/index.ts").read_text()
        module = Path(self.temp.name) / "openclaw-fixture.mjs"
        module.write_text(source + "\nexport { walletSessionToolDefinitions };\n")
        script = "const m = await import(process.argv[1]); console.log(JSON.stringify(m.walletSessionToolDefinitions));"
        result = subprocess.run(["node", "--input-type=module", "-e", script, module.as_uri()], capture_output=True, text=True, check=True, timeout=10)
        actual = {item["name"]: item["parameters"] for item in json.loads(result.stdout)}
        for spec in self.adapter._card_tool_specs():
            self.assertEqual(actual[spec.name], spec.input_schema)

    def test_agent_tool_contracts_are_safe_reads(self):
        specs = {spec.name: spec for spec in self.adapter.list_tools()}
        for name in ("list_saved_cards", "get_saved_card_status", "refresh_saved_card"):
            self.assertTrue(specs[name].read_only)
            self.assertEqual(specs[name].risk_level, "low")
            self.assertNotIn("user_id", specs[name].input_schema["properties"])
            self.assertNotIn("headers", specs[name].input_schema["properties"])
            self.assertNotIn("url", specs[name].input_schema["properties"])


if __name__ == "__main__":
    unittest.main()
