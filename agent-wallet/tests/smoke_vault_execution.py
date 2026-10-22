"""Offline regressions for card receipts, safe retries and private Kernel dispatch."""
from __future__ import annotations

import asyncio
import copy
import json
import os
import socket
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import httpx
from agent_wallet.card_catalog import CardCatalog
from agent_wallet.card_runtime_secrets import CardRuntimeSecrets
from agent_wallet.card_vault import CardVault
from agent_wallet.kernel_browser import KernelBrowser, safe_checkout_diagnostics, validate_checkout
from agent_wallet.laso_card_vault import capture_request
from agent_wallet.vault_executor import VaultExecutor, resolve_public_destination
from smoke_card_vault import FakeSystemStore, READY, PAN


class ExecutionChecks(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        for mock in (
            patch.dict(os.environ, {"OPENCLAW_HOME": self.temp.name}),
            patch("agent_wallet.card_catalog.resolve_wallet_master_key", return_value="offline-runtime-master"),
            patch("agent_wallet.card_runtime_secrets.resolve_wallet_master_key", return_value="offline-runtime-master"),
            patch.object(CardVault, "_system_store", return_value=FakeSystemStore()),
        ):
            mock.start()
            self.addCleanup(mock.stop)
        self.vault = CardVault("execution-owner")
        self.vault.ensure_system()
        self.executor = VaultExecutor(self.vault)

    def card(self):
        record = {"card_type": "US Prepaid", "order": copy.deepcopy(READY)}
        ref = self.vault.deposit(record)
        CardCatalog(self.vault).track(ref, record)
        return ref

    def plan(self):
        return {"browser_reference": "b" * 32, "page_url": "https://merchant.example/checkout",
                "fields": [{"field": field, "selector": selector} for field, selector in (
                    ("card.number", "#number"), ("card.cvv", "#cvv"), ("card.expiry_short", "#expiry"))],
                "total_selector": "#total", "expected_total": "$19.99", "amount_usd": "19.99",
                "submit_selector": "#pay", "success_selector": "#success"}

    def prepare(self, checkout=None):
        return self.executor.prepare(vault_reference=self.card(),
            request=None if checkout else {"url": "https://merchant.example/pay", "json": {"pan": "{{card.number}}"}},
            checkout=checkout, purpose="Test subscription", network="mainnet", owner="fixture-owner", mode="prepare")

    async def execute(self, ref, authorize=None):
        return await self.executor.execute(ref, network="mainnet", owner="fixture-owner", authorize=authorize or Mock())

    async def test_non_200_laso_responses_do_not_create_cards(self):
        for status in (400, 402, 429, 500):
            with self.subTest(status=status):
                result = {"status_code": status, "response_preview": {"error": "issuer validation failed"}}
                actual = await capture_request(call=AsyncMock(return_value=result), user_id="execution-owner",
                                               url="https://laso.finance/get-card")
                self.assertIs(actual, result)
                self.assertEqual(self.vault.references(), [])
                self.assertEqual(list(self.vault.root.glob("*.agent")), [])

    async def test_dual_stack_prefers_ipv4_and_rejects_any_private_answer(self):
        answers = [(socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("2600:1f18::1", 443, 0, 0)),
                   (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("52.1.2.3", 443))]
        with patch.object(asyncio.get_running_loop(), "getaddrinfo", AsyncMock(return_value=answers)):
            self.assertEqual(await resolve_public_destination(httpx.URL("https://merchant.example")), "52.1.2.3")
        answers.append((socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443)))
        with patch.object(asyncio.get_running_loop(), "getaddrinfo", AsyncMock(return_value=answers)):
            with self.assertRaises(Exception):
                await resolve_public_destination(httpx.URL("https://merchant.example"))

    async def test_connect_failures_can_continue_without_new_authorization(self):
        for failure in (httpx.ConnectError, httpx.ConnectTimeout):
            with self.subTest(failure=failure):
                prepared = self.prepare()
                ref = prepared["operation_id"]
                authorize = Mock()
                sender = AsyncMock(side_effect=[failure("fixture"), 200])
                with patch("agent_wallet.vault_executor.resolve_public_destination", AsyncMock(return_value="52.1.2.3")), patch("agent_wallet.vault_executor.send_private_request", sender):
                    first = await self.execute(ref, authorize)
                    self.assertEqual(first["status"], "authorized")
                    self.assertTrue(first["last_attempt_not_sent"])
                    self.assertEqual(sender.await_count, 1)
                    no_approval = Mock(side_effect=AssertionError("Must reuse exact authorization"))
                    second = await self.execute(ref, no_approval)
                    self.assertEqual(second["status"], "request_succeeded")
                    self.assertFalse(second["last_attempt_not_sent"])
                    await self.execute(ref, no_approval)
                    self.assertEqual(sender.await_count, 2)
                    authorize.assert_called_once()

    async def test_read_write_and_outer_timeout_failures_never_retry(self):
        for failure in (httpx.ReadError, httpx.WriteError, httpx.ReadTimeout, asyncio.TimeoutError):
            with self.subTest(failure=failure):
                ref = self.prepare()["operation_id"]
                sender = AsyncMock(side_effect=failure("fixture"))
                with patch("agent_wallet.vault_executor.resolve_public_destination", AsyncMock(return_value="52.1.2.3")), patch("agent_wallet.vault_executor.send_private_request", sender):
                    first = await self.execute(ref)
                    self.assertEqual(first["status"], "outcome_unknown")
                    await self.execute(ref)
                    self.assertEqual(sender.await_count, 1)

    async def test_missing_billing_never_dispatches_or_fills(self):
        plan = self.plan()
        plan["fields"].append({"field": "card.billing.zip", "selector": "#zip"})
        ref = self.prepare(plan)["operation_id"]
        browser = AsyncMock()
        with patch.object(KernelBrowser, "preflight", AsyncMock()), patch.object(KernelBrowser, "checkout", browser), patch.object(VaultExecutor, "_cleanup_browser", AsyncMock()):
            result = await self.execute(ref)
        self.assertEqual(result["status"], "checkout_unavailable")
        browser.assert_not_awaited()
        self.assertNotIn("dispatching", json.dumps(self.executor.storage.load(ref)))
        self.assertNotIn(PAN, json.dumps(result))

    async def test_kernel_script_distinguishes_precheck_from_fill_failure(self):
        plan = self.plan()
        browser = KernelBrowser(self.vault)
        fields = CardRuntimeSecrets(self.vault).load_for_executor(self.card())
        selected = browser.select_fields(plan, fields)
        client = Mock()
        client.call = AsyncMock(return_value={})
        for scenario, expected in (("changed", "checkout_unavailable"), ("fill_error", "outcome_unknown"), ("submit_error", "outcome_unknown"), ("confirmation_timeout", "outcome_unknown"), ("success", "checkout_submitted"), ("fill_only", "checkout_filled")):
            with self.subTest(scenario=scenario):
                plan = self.plan()
                if scenario == "fill_only":
                    plan["action"] = "fill_only"
                    plan.pop("submit_selector")
                    plan.pop("success_selector")
                    validate_checkout(plan)
                browser.storage.save(plan["browser_reference"], {"status": "reserved", "operation_id": "op", "session_id": "fixture"})
                async def run_script(session, code):
                    fixture = r'''
const scenario=SCENARIO;
let filled=false, clicked=false;
const handle={};
const p={url:()=> 'https://merchant.example/checkout',setDefaultTimeout:()=>{},
 mainFrame:()=>p,frames:()=>[p],evaluate:async()=>({invalid:scenario==='confirmation_timeout'?1:0,categories:scenario==='confirmation_timeout'?['phone']:[],errors:[],alerts:0}),locator:s=>({
 count:async()=>s==='#success'?(clicked?1:0):1,
 innerText:async()=>scenario==='changed'?'$29.99':'$19.99',
 isVisible:async()=>s!=='#success'||clicked,isEnabled:async()=>true,isEditable:async()=>true,
 evaluate:async(fn,other)=>other?false:'INPUT',elementHandle:async()=>handle,
 fill:async()=>{filled=true;if(scenario==='fill_error')throw Error('fixture');},
 selectOption:async()=>{},click:async()=>{if(scenario==='submit_error')throw Error('fixture');clicked=true;},waitFor:async()=>{if(scenario==='confirmation_timeout')throw Error('fixture');}
 })};
const browser={contexts:()=>[{pages:()=>[p]}]};
(async()=>{const result=await (async()=>{CODE})();process.stdout.write(JSON.stringify({result,filled,clicked}));})().catch(()=>process.exit(1));
'''.replace('SCENARIO', json.dumps(scenario)).replace('CODE', code)
                    proc = subprocess.run(["node", "-"], input=fixture, text=True, capture_output=True, check=True)
                    outcome = json.loads(proc.stdout)
                    if scenario == "changed":
                        self.assertFalse(outcome["filled"])
                        self.assertFalse(outcome["clicked"])
                    if scenario == "fill_only":
                        self.assertTrue(outcome["filled"])
                        self.assertFalse(outcome["clicked"])
                    if scenario == "fill_error":
                        self.assertTrue(outcome["filled"])
                        self.assertFalse(outcome["clicked"])
                    return outcome["result"]
                client.execute = AsyncMock(side_effect=run_script)
                with patch("agent_wallet.kernel_browser.KernelClient", return_value=client):
                    result = await browser.checkout(plan, selected, "op")
                self.assertEqual(result["status"], expected)
                diagnostic = result["checkout_diagnostics"]
                expected_phase = {"changed": "precheck", "fill_error": "fill", "submit_error": "submit", "confirmation_timeout": "confirmation", "success": "complete", "fill_only": "complete"}[scenario]
                self.assertEqual(diagnostic["phase"], expected_phase)
                self.assertEqual(diagnostic["filled_fields"], 0 if scenario in {"changed", "fill_error"} else 3)
                if scenario == "fill_only":
                    self.assertFalse(result["merchant_confirmation_observed"])
                    self.assertFalse(diagnostic["submit_attempted"])
                    self.assertFalse(diagnostic["submit_completed"])
                if scenario == "confirmation_timeout":
                    self.assertTrue(diagnostic["submit_completed"])
                    self.assertEqual(diagnostic["invalid_field_categories"], ["phone"])
                    self.assertEqual(diagnostic["reason"], "confirmation_not_observed")
                self.assertEqual(browser.storage.load(plan["browser_reference"])["status"], "closed")
                self.assertNotIn(PAN, json.dumps(result))

    def test_fill_only_validation_and_action_binding(self):
        plan = self.plan()
        plan["action"] = "fill_only"
        with self.assertRaises(Exception):
            validate_checkout(plan)
        plan.pop("submit_selector")
        plan.pop("success_selector")
        self.assertEqual(validate_checkout(plan)["action"], "fill_only")
        invalid = dict(plan, action="submit")
        with self.assertRaises(Exception):
            validate_checkout(invalid)
        prepared = self.prepare(plan)
        ref = prepared["operation_id"]
        state = self.executor._load(ref)
        state["checkout"]["action"] = "submit"
        self.executor.storage.save(ref, state)
        with self.assertRaises(Exception):
            self.executor.get(ref)

    async def test_filled_operation_cannot_be_replayed(self):
        plan = self.plan()
        plan["action"] = "fill_only"
        plan.pop("submit_selector")
        plan.pop("success_selector")
        prepared = self.prepare(plan)
        ref = prepared["operation_id"]
        checkout = AsyncMock(return_value={"status": "checkout_filled"})
        with patch.object(KernelBrowser, "preflight", AsyncMock()), patch.object(KernelBrowser, "checkout", checkout), patch.object(VaultExecutor, "_cleanup_browser", AsyncMock()):
            result = await self.execute(ref)
            self.assertEqual(result["status"], "checkout_filled")
            self.assertTrue(result["private_fill_completed"])
            self.assertFalse(result["can_continue"])
            again = await self.execute(ref, Mock(side_effect=AssertionError("No replay")))
            self.assertEqual(again["status"], "checkout_filled")
            checkout.assert_awaited_once()

    def test_checkout_diagnostics_drop_all_free_text_and_unknown_fields(self):
        raw = {"phase": "confirmation", "reason": "confirmation_not_observed", "filled_fields": 3,
               "submit_attempted": True, "submit_completed": True,
               "invalid_field_categories": ["phone", PAN, {"secret": PAN}],
               "error_categories": ["card_declined", PAN], "body": PAN, "stdout": PAN,
               "invalid_fields": True, "visible_alerts": -1}
        safe = safe_checkout_diagnostics(raw)
        self.assertEqual(safe["invalid_field_categories"], ["phone"])
        self.assertEqual(safe["error_categories"], ["card_declined"])
        self.assertNotIn(PAN, json.dumps(safe))
        self.assertNotIn("body", safe)
        self.assertNotIn("invalid_fields", safe)
        self.assertNotIn("visible_alerts", safe)


if __name__ == "__main__":
    unittest.main()
