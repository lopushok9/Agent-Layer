"""Managed Kernel sessions. No CDP, arbitrary code, cookies or filled DOM in tools.

Kernel is a trusted cloud processor: private fill values cross TLS to its
Playwright API and exist in its VM and merchant page. This is not isolation
from Kernel/account administrators or from the merchant's own JavaScript.
"""
from __future__ import annotations

import json
import re
import time
import uuid
from typing import Any
from urllib.parse import quote

import httpx

from agent_wallet.card_runtime_secrets import RuntimeVaultStorage
from agent_wallet.card_vault import CardVault
from agent_wallet.config import resolve_kernel_api_key
from agent_wallet.wallet_layer.base import WalletBackendError

BROWSER_SCHEMA = {"type": "object", "properties": {
    "action": {"type": "string", "enum": ["open", "observe", "inspect", "click", "fill", "select", "press", "close", "status"]},
    "browser_reference": {"type": "string", "pattern": "^[a-f0-9]{32}$"},
    "url": {"type": "string"}, "selector": {"type": "string", "maxLength": 512},
    "value": {"type": "string", "maxLength": 2048}, "user_intent": {"type": "boolean"},
}, "required": ["action"], "additionalProperties": False}
CHECKOUT_SCHEMA = {"type": "object", "properties": {
    "action": {"type": "string", "enum": ["submit", "fill_only"], "default": "submit",
               "description": "fill_only fills privately without clicking submit, then closes the browser."},
    "browser_reference": {"type": "string", "pattern": "^[a-f0-9]{32}$"},
    "page_url": {"type": "string"},
    "fields": {"type": "array", "minItems": 3, "maxItems": 14, "items": {
        "type": "object", "properties": {
            "field": {"type": "string", "enum": ["card.number", "card.cvv", "card.exp_month", "card.exp_year", "card.expiry", "card.expiry_short", "card.exp_year_short", *["card.billing." + k for k in ("name", "line_1", "line_2", "city", "state", "zip", "country")]]},
            "selector": {"type": "string", "maxLength": 512},
            "frame_url": {"type": "string"},
        }, "required": ["field", "selector"], "additionalProperties": False}},
    "total_selector": {"type": "string", "maxLength": 512},
    "expected_total": {"type": "string", "maxLength": 128},
    "amount_usd": {"type": "string", "pattern": "^[0-9]{1,6}(\\.[0-9]{1,2})?$"},
    "submit_selector": {"type": "string", "maxLength": 512},
    "success_selector": {"type": "string", "maxLength": 512},
}, "required": ["browser_reference", "page_url", "fields", "total_selector", "expected_total", "amount_usd"], "additionalProperties": False}


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, allow_nan=False, separators=(",", ":"))


def _selector(value: Any) -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= 512 or any(ord(c) < 32 for c in value):
        raise WalletBackendError("Use a nonempty selector of at most 512 characters.")
    return value


def validate_checkout(value: Any) -> dict[str, Any]:
    from decimal import Decimal
    from agent_wallet.vault_executor import _url, FIELDS

    if (not isinstance(value, dict) or set(value) - set(CHECKOUT_SCHEMA["properties"])
            or not set(CHECKOUT_SCHEMA["required"]) <= set(value)):
        raise WalletBackendError("checkout requires a fixed browser, fields and total plan.")
    action = value.get("action", "submit")
    if action not in ("submit", "fill_only"):
        raise WalletBackendError("checkout.action must be submit or fill_only.")
    if action == "submit" and not {"submit_selector", "success_selector"} <= set(value):
        raise WalletBackendError("Submitting checkout requires submit_selector and success_selector.")
    if action == "fill_only" and set(value) & {"submit_selector", "success_selector"}:
        raise WalletBackendError("fill_only must not include submit or success selectors.")
    result = json.loads(_json(value))
    if not isinstance(result["browser_reference"], str) or not re.fullmatch(r"[a-f0-9]{32}", result["browser_reference"]):
        raise WalletBackendError("Invalid browser reference.")
    _url(result["page_url"])
    selector_keys = ("total_selector", "submit_selector", "success_selector") if action == "submit" else ("total_selector",)
    for key in selector_keys:
        _selector(result[key])
    if len({result[k] for k in selector_keys}) != len(selector_keys):
        raise WalletBackendError("Total, submit and success selectors must differ.")
    amount = result["amount_usd"]
    if not isinstance(amount, str) or not re.fullmatch(r"[0-9]{1,6}(?:\.[0-9]{1,2})?", amount) or Decimal(amount) <= 0:
        raise WalletBackendError("A positive USD amount with at most two decimal places is required.")
    # Intentionally narrow: refuse ambiguous localized/currency display strings.
    total = result["expected_total"]
    if not isinstance(total, str) or len(total) > 128:
        raise WalletBackendError("Provide the exact displayed USD total.")
    match = re.fullmatch(r"(?:USD\s*\$?|US\$|\$)\s*([0-9]+(?:\.[0-9]{2})?)|([0-9]+(?:\.[0-9]{2})?)\s*USD", re.sub(r"^(?:Donate|Pay)\s+", "", total.strip(), flags=re.IGNORECASE))
    if not match or Decimal(match.group(1) or match.group(2)) != Decimal(amount):
        raise WalletBackendError("expected_total must be an unambiguous USD price matching amount_usd, e.g. $19.99 or 19.99 USD.")
    fields = result["fields"]
    if not isinstance(fields, list) or not 3 <= len(fields) <= 14:
        raise WalletBackendError("Bind the card number, CVV and expiry fields.")
    seen, targets = set(), set()
    for binding in fields:
        if not isinstance(binding, dict) or set(binding) - {"field", "selector", "frame_url"} or not {"field", "selector"} <= set(binding):
            raise WalletBackendError("Invalid checkout field binding.")
        field = binding["field"]
        if field not in FIELDS | {"card.expiry", "card.expiry_short", "card.exp_year_short"} or field in seen:
            raise WalletBackendError("Unknown or repeated checkout card field.")
        _selector(binding["selector"])
        if "frame_url" in binding:
            _url(binding["frame_url"])
        target = (binding.get("frame_url", result["page_url"]), binding["selector"])
        if target in targets:
            raise WalletBackendError("Checkout field targets must be distinct.")
        targets.add(target)
        seen.add(field)
    if not {"card.number", "card.cvv"} <= seen or not ({"card.exp_month", "card.exp_year"} <= seen or {"card.exp_month", "card.exp_year_short"} <= seen or seen & {"card.expiry", "card.expiry_short"}):
        raise WalletBackendError("Card number, CVV and complete expiry are required.")
    return result


DIAGNOSTIC_PHASES = {"precheck", "fill", "verify_total", "submit", "confirmation", "complete", "transport"}
DIAGNOSTIC_REASONS = {"precheck_failed", "page_changed", "fill_failed", "total_changed",
                      "success_already_visible", "submit_failed", "confirmation_not_observed",
                      "origin_changed", "completed", "filled_without_submit", "executor_result_unavailable"}
ERROR_CATEGORIES = {"card_declined", "card_invalid", "expiry_invalid", "cvv_invalid",
                    "authentication_required", "demo_restriction"}
FIELD_CATEGORIES = {"email", "name", "address", "postal_code", "phone", "card_number", "card_expiry", "card_cvv", "other"}


def safe_checkout_diagnostics(value: Any) -> dict:
    """Treat provider results as untrusted; never return free text or field values."""
    if not isinstance(value, dict):
        return {}
    safe = {}
    for key, allowed in (("phase", DIAGNOSTIC_PHASES), ("reason", DIAGNOSTIC_REASONS)):
        if isinstance(value.get(key), str) and value[key] in allowed:
            safe[key] = value[key]
    for key, maximum in (("filled_fields", 14), ("invalid_fields", 1000), ("visible_alerts", 1000)):
        if type(value.get(key)) is int and 0 <= value[key] <= maximum:
            safe[key] = value[key]
    for key in ("submit_attempted", "submit_completed"):
        if type(value.get(key)) is bool:
            safe[key] = value[key]
    for key, allowed in (("invalid_field_categories", FIELD_CATEGORIES), ("error_categories", ERROR_CATEGORIES)):
        if isinstance(value.get(key), list):
            safe[key] = sorted({item for item in value[key][:32] if isinstance(item, str) and item in allowed})
    return safe


class KernelClient:
    def __init__(self, key: str | None = None):
        self.key = key or resolve_kernel_api_key()
        if not self.key:
            raise WalletBackendError("Connect Kernel in your terminal: wallet vault kernel-connect")

    async def call(self, method: str, path: str, body: Any = None, *, missing_ok: bool = False) -> dict:
        try:
            async with httpx.AsyncClient(trust_env=False, follow_redirects=False, timeout=75) as client:
                async with client.stream(method, "https://api.onkernel.com" + path,
                                         headers={"Authorization": "Bearer " + self.key},
                                         **({"json": body} if body is not None else {})) as response:
                    if missing_ok and response.status_code == 404:
                        return {}
                    if not 200 <= response.status_code < 300:
                        raise WalletBackendError("Kernel API request failed. Check the connection and saved operation status before retrying.")
                    data = bytearray()
                    async for chunk in response.aiter_bytes():
                        data.extend(chunk)
                        if len(data) > 512 * 1024:
                            raise WalletBackendError("Kernel response exceeded the private executor limit.")
                    result = json.loads(data) if data else {}
                    return result if isinstance(result, dict) else {}
        except WalletBackendError:
            raise
        except Exception:
            raise WalletBackendError("Kernel transport failed; check the saved operation before retrying.") from None

    async def execute(self, session_id: str, code: str) -> dict:
        data = await self.call("POST", "/browsers/" + quote(session_id, safe="") + "/playwright/execute",
                               {"code": code, "timeout_sec": 60})
        # Discard stdout, stderr, error and tab metadata even on failure.
        if data.get("success") is not True or not isinstance(data.get("result"), dict):
            raise WalletBackendError("Kernel browser action did not complete. No private error details were returned.")
        return data["result"]


# Scripts only return preselected properties, never DOM/HTML/input values wholesale.
PAGE = "const pages=browser.contexts().flatMap(c=>c.pages()); if(pages.length!==1) throw new Error('page count'); const p=pages[0]; p.setDefaultTimeout(8000);\n"
SNAPSHOT = r"""
const main = await p.evaluate(() => {
 const cut=s=>String(s||'').replace(/(?:\d[ -]?){12,19}/g,'[redacted]').slice(0,8000);
 const controls=Array.from(document.querySelectorAll('input,select,button,a')).slice(0,100).map(e=>({
  tag:e.tagName.toLowerCase(),type:e.getAttribute('type'),id:e.id||null,name:e.getAttribute('name'),
  autocomplete:e.getAttribute('autocomplete'),label:cut(e.getAttribute('aria-label')||((e.tagName==='BUTTON'||e.tagName==='A')?e.textContent:'')),
 }));
 const copy=document.body.cloneNode(true); copy.querySelectorAll('input,textarea,select,script,style').forEach(e=>e.remove());
 return {url:cut(location.href),text:cut(copy.textContent),controls,frames:Array.from(document.querySelectorAll('iframe')).map(e=>({src:cut(e.src),title:cut(e.title)})).slice(0,20)};
});
const childFrames=[];
for(const f of p.frames().filter(f=>f!==p.mainFrame()).slice(0,20)) {
 try { childFrames.push({url:f.url(),controls:await f.evaluate(()=>Array.from(document.querySelectorAll('input,select')).slice(0,30).map(e=>({tag:e.tagName,id:e.id,name:e.getAttribute('name'),autocomplete:e.getAttribute('autocomplete'),type:e.getAttribute('type')})))}); } catch (_) {}
}
return {...main,child_frames:childFrames};
"""


class KernelBrowser:
    def __init__(self, vault: CardVault):
        self.vault = vault
        self.storage = RuntimeVaultStorage(vault, "browser")

    def safe(self, ref: str, state: dict) -> dict:
        return {"browser_reference": ref, "status": state["status"], "cleanup_pending": bool(state.get("cleanup_pending")),
                "secrets_returned": False, "provider": "kernel"}

    async def close(self, ref: str, state: dict) -> None:
        state["status"] = "closed"
        state["cleanup_pending"] = True
        try:
            self.storage.save(ref, state)  # Persist inaccessible even if remote deletion fails.
        finally:
            await self._delete_remote(ref, state)

    async def _delete_remote(self, ref: str, state: dict) -> None:
        try:
            await KernelClient().call("DELETE", "/browsers/" + quote(state["session_id"], safe=""), missing_ok=True)
            state["cleanup_pending"] = False
            self.storage.save(ref, state)
        except Exception:
            pass  # Retry via close; remote session also has a short inactivity TTL.

    async def invoke(self, args: dict) -> dict:
        if set(args) - set(BROWSER_SCHEMA["properties"]):
            raise WalletBackendError("Unsupported Kernel browser arguments.")
        action = args.get("action")
        if action not in BROWSER_SCHEMA["properties"]["action"]["enum"]:
            raise WalletBackendError("Unsupported Kernel browser action.")
        if action == "open":
            if set(args) - {"action", "url", "user_intent"} or args.get("user_intent") is not True:
                raise WalletBackendError("Opening a billable Kernel browser requires user_intent=true.")
            from agent_wallet.vault_executor import _url, resolve_public_destination
            await resolve_public_destination(_url(args.get("url")))
            self.vault._config()
            self.storage._key()  # Require working encryption before creating a paid resource.
            ref = uuid.uuid4().hex
            client = KernelClient()
            data = await client.call("POST", "/browsers", {"headless": True, "timeout_seconds": 300,
                                                          "telemetry": {"enabled": False}})
            session = data.get("session_id")
            if not isinstance(session, str) or not 1 <= len(session) <= 256:
                raise WalletBackendError("Kernel did not return a usable browser session.")
            state = {"status": "open", "session_id": session, "created_at": int(time.time())}
            try:
                self.storage.save(ref, state)
                result = await client.execute(session, PAGE + "await p.goto(" + _json(args["url"]) + ", {waitUntil:'domcontentloaded',timeout:30000});\n" + SNAPSHOT)
            except BaseException:
                await self.close(ref, state)
                raise
            return {**self.safe(ref, state), "page": result, "untrusted_page_content": True}
        ref = args.get("browser_reference")
        allowed = {"action", "browser_reference"}
        if action == "inspect":
            allowed.add("selector")
        if action in {"click", "fill", "select", "press"}:
            allowed |= {"selector", "user_intent"}
            if action != "click":
                allowed.add("value")
        if set(args) - allowed:
            raise WalletBackendError("Unsupported arguments for this browser action.")
        async with self.vault.async_record_lock(ref):
            state = self.storage.load(ref)
            if action == "close":
                await self.close(ref, state)
                return self.safe(ref, state)
            if action == "status":
                return self.safe(ref, state)
            if state["status"] != "open":
                raise WalletBackendError("Browser is reserved for private checkout or closed; observation and interaction are disabled.")
            code = PAGE
            if action == "inspect":
                selector = _selector(args.get("selector"))
                code += "return {elements:await p.locator(" + _json(selector) + ").evaluateAll(es=>es.slice(0,40).map(e=>{const c=e.cloneNode(true); c.querySelectorAll('input,textarea,select,script,style').forEach(x=>x.remove()); return {tag:e.tagName,id:e.id,testid:e.getAttribute('data-testid'),text:['INPUT','TEXTAREA','SELECT'].includes(e.tagName)?'':String(c.textContent||'').replace(/(?:\\d[ -]?){12,19}/g,'[redacted]').slice(0,512)};}))};"
                result = await KernelClient().execute(state["session_id"], code)
                return {**self.safe(ref, state), "page": result, "untrusted_page_content": True}
            if action != "observe":
                if args.get("user_intent") is not True:
                    raise WalletBackendError("Browser interaction requires user_intent=true for the user's task.")
                selector = _selector(args.get("selector"))
                value = args.get("value")
                if action != "click" and (not isinstance(value, str) or len(value) > 2048):
                    raise WalletBackendError("A public form value of at most 2048 characters is required.")
                if action == "press" and value not in {"Tab", "Enter", "Escape", "ArrowDown", "ArrowUp"}:
                    raise WalletBackendError("Unsupported browser key.")
                method = {"click": "click", "fill": "fill", "select": "selectOption", "press": "press"}[action]
                code += "const el=p.locator(" + _json(selector) + "); if(await el.count()!==1) throw new Error('target count'); await el." + method + "(" + (_json(value) if action != "click" else "") + ");\n"
            result = await KernelClient().execute(state["session_id"], code + SNAPSHOT)
            return {**self.safe(ref, state), "page": result, "untrusted_page_content": True}

    async def preflight(self, plan: dict, *, operation_id: str | None = None) -> None:
        ref = plan["browser_reference"]
        async with self.vault.async_record_lock(ref):
            state = self.storage.load(ref)
            if state["status"] != "open" and not (state["status"] == "reserved" and state.get("operation_id") == operation_id):
                raise WalletBackendError("Kernel browser is unavailable or reserved for another operation.")
            result = await KernelClient().execute(state["session_id"], self._check_code(plan) + "return {ready:true};")
            if result.get("ready") is not True:
                raise WalletBackendError("Checkout page is not ready.")
            if operation_id:
                state.update(status="reserved", operation_id=operation_id)
                self.storage.save(ref, state)

    @staticmethod
    def _check_code(plan: dict) -> str:
        # Exact page and displayed total checked both before approval and dispatch.
        return PAGE + "const plan=" + _json(plan) + ";\n" + r"""
if(p.url()!==plan.page_url) throw new Error('page changed');
const fillOnly=plan.action==='fill_only';
const total=p.locator(plan.total_selector), submit=fillOnly?null:p.locator(plan.submit_selector), success=fillOnly?null:p.locator(plan.success_selector);
if(await total.count()!==1 || (await total.innerText()).trim()!==plan.expected_total.trim()) throw new Error('total changed');
if(!fillOnly && (await submit.count()!==1 || !(await submit.isVisible()))) throw new Error('submit unavailable');
if(!fillOnly && (await success.count()>1 || await success.isVisible())) throw new Error('success already present');
const targets=[], targetFrames=[];
for(const b of plan.fields){
 const frames=b.frame_url?p.frames().filter(f=>f.url()===b.frame_url):[p.mainFrame()];
 if(frames.length!==1) throw new Error('frame count');
 const el=frames[0].locator(b.selector);
 if(await el.count()!==1 || !(await el.isVisible()) || !(await el.isEditable())) throw new Error('field unavailable');
 const tag=await el.evaluate(e=>e.tagName); if(!['INPUT','SELECT','TEXTAREA'].includes(tag)) throw new Error('field type');
 targets.push(el); targetFrames.push(frames[0]);
}
for(let i=0;i<targets.length;i++) for(let j=i+1;j<targets.length;j++)
 if(targetFrames[i]===targetFrames[j] && await targets[i].evaluate((e,other)=>e===other,await targets[j].elementHandle())) throw new Error('duplicate target');
"""

    @staticmethod
    def select_fields(plan: dict, fields: dict[str, str]) -> list[str]:
        """Resolve every requested secret before dispatch/private state changes."""
        values = dict(fields)
        try:
            values.update({"card.expiry": fields["card.exp_month"] + "/" + fields["card.exp_year"],
                           "card.expiry_short": fields["card.exp_month"] + "/" + fields["card.exp_year"][-2:],
                           "card.exp_year_short": fields["card.exp_year"][-2:]})
            return [values[b["field"]] for b in plan["fields"]]
        except KeyError:
            raise WalletBackendError("The saved card is missing a requested checkout field; no private fill was started.") from None
        finally:
            values.clear()

    async def checkout(self, plan: dict, selected: list[str], operation_id: str) -> dict:
        ref = plan["browser_reference"]
        async with self.vault.async_record_lock(ref):
            state = self.storage.load(ref)
            if state.get("operation_id") != operation_id or state["status"] != "reserved":
                raise WalletBackendError("Checkout session is not reserved by this operation.")
            state["status"] = "private"
            self.storage.save(ref, state)  # No future DOM/observation access, including on crash.
            try:
                # Values are encoded as JSON data literals, never inserted as executable JS.
                # No logs or errors escape this call. Kernel still processes the request.
                code = r"""
let fillStarted=false, phase='precheck', filledFields=0, submitAttempted=false, submitCompleted=false;
async function finish(outcome,reason){
 const diagnostic={phase,reason,filled_fields:filledFields,submit_attempted:submitAttempted,submit_completed:submitCompleted};
 let invalid=0, alerts=0; const categories=new Set(), errors=new Set();
 // Read only inside the private executor; return fixed categories/counts, never text/values.
 try {
  for(const context of browser.contexts()) for(const page of context.pages()) for(const frame of page.frames().slice(0,20)) {
   try {
    const d=await frame.evaluate(()=>{
     const visible=e=>!!e.getClientRects().length && getComputedStyle(e).visibility!=='hidden';
     const invalid=Array.from(document.querySelectorAll('input:invalid,select:invalid,textarea:invalid,[aria-invalid="true"]')).filter(visible);
     const categories=invalid.map(e=>{
      const a=e.getAttribute('autocomplete')||'', id=e.id.toLowerCase();
      if(a==='cc-number'||id==='cardnumber') return 'card_number';
      if(a==='cc-exp'||id==='cardexpiry') return 'card_expiry';
      if(a==='cc-csc'||id==='cardcvc') return 'card_cvv';
      if(a.includes('email')||e.type==='email'||id==='email') return 'email';
      if(a.includes('tel')||e.type==='tel'||id.includes('phone')) return 'phone';
      if(a.includes('postal-code')||id.includes('postal')) return 'postal_code';
      if(a.includes('name')||id.includes('name')) return 'name';
      if(a.includes('address')||a.includes('country')||id.includes('shipping')) return 'address';
      return 'other';
     });
     const text=(document.body?.innerText||'').slice(0,65536), errors=[];
     if(/card (?:was |has been )?declined/i.test(text)) errors.push('card_declined');
     if(/(?:invalid|incorrect) card number|card number is (?:invalid|incorrect|incomplete)/i.test(text)) errors.push('card_invalid');
     if(/(?:invalid|incorrect|expired) expir|expir(?:y|ation).*?(?:invalid|incorrect|incomplete)/i.test(text)) errors.push('expiry_invalid');
     if(/(?:security code|cvc|cvv).*?(?:invalid|incorrect|incomplete)/i.test(text)) errors.push('cvv_invalid');
     if(/authentication required|verify your identity|3d secure/i.test(text)) errors.push('authentication_required');
     if(/(?:payments?|checkout).*?(?:disabled|not supported).*?demo|cannot (?:pay|process).*?demo/i.test(text)) errors.push('demo_restriction');
     return {invalid:invalid.length,categories,errors,alerts:Array.from(document.querySelectorAll('[role="alert"]')).filter(visible).length};
    });
    invalid+=d.invalid; alerts+=d.alerts; d.categories.forEach(x=>categories.add(x)); d.errors.forEach(x=>errors.add(x));
   } catch (_) {}
  }
  diagnostic.invalid_fields=Math.min(1000,invalid); diagnostic.visible_alerts=Math.min(1000,alerts);
  diagnostic.invalid_field_categories=[...categories]; diagnostic.error_categories=[...errors];
 } catch (_) {}
 return {outcome,diagnostic};
}
try {
""" + self._check_code(plan) + "const values=" + _json(selected) + ";\n" + r"""
phase='fill';
for(let i=0;i<targets.length;i++) {
 if(p.url()!==plan.page_url) return await finish(fillStarted?'unknown':'not_started','page_changed');
 const tag=await targets[i].evaluate(e=>e.tagName);
 // Input/change handlers may have effects even if this fill later fails.
 fillStarted=true;
 if(tag==='SELECT') await targets[i].selectOption(values[i]); else await targets[i].fill(values[i]);
 filledFields++;
}
phase='verify_total';
if(p.url()!==plan.page_url) return await finish('unknown','page_changed');
if((await total.innerText()).trim()!==plan.expected_total.trim()) return await finish('unknown','total_changed');
if(fillOnly) { phase='complete'; return await finish('fields_filled','filled_without_submit'); }
if(await success.count()>1 || await success.isVisible()) return await finish('unknown','success_already_visible');
phase='submit'; submitAttempted=true;
await submit.click({timeout:8000}); submitCompleted=true;
phase='confirmation';
await success.waitFor({state:'visible',timeout:20000});
if(new URL(p.url()).origin!==new URL(plan.page_url).origin) return await finish('unknown','origin_changed');
phase='complete'; return await finish('merchant_confirmation_observed','completed');
} catch (_) {
 const reason={precheck:'precheck_failed',fill:'fill_failed',verify_total:'total_changed',submit:'submit_failed',confirmation:'confirmation_not_observed'}[phase]||'precheck_failed';
 return await finish(fillStarted?'unknown':'not_started',reason);
}
"""
                result = await KernelClient().execute(state["session_id"], code)
                outcome = result.get("outcome")
                diagnostics = safe_checkout_diagnostics(result.get("diagnostic"))
                fill_only = plan.get("action") == "fill_only"
                status = "outcome_unknown"
                if outcome == "not_started":
                    status = "checkout_unavailable"
                elif fill_only and outcome == "fields_filled":
                    if (diagnostics.get("filled_fields") == len(plan["fields"])
                            and diagnostics.get("submit_attempted") is False
                            and diagnostics.get("submit_completed") is False):
                        status = "checkout_filled"
                elif not fill_only and outcome == "merchant_confirmation_observed":
                    status = "checkout_submitted"
                return {"status": status,
                        "merchant_confirmation_observed": status == "checkout_submitted",
                        "checkout_diagnostics": diagnostics}
            finally:
                await self.close(ref, state)

    async def cleanup(self, plan: dict, operation_id: str) -> None:
        ref = plan["browser_reference"]
        async with self.vault.async_record_lock(ref):
            state = self.storage.load(ref)
            if state.get("operation_id") == operation_id:
                await self.close(ref, state)
