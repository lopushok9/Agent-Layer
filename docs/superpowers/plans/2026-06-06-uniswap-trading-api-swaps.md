# Uniswap Trading API Swaps (CLASSIC + Permit2 EIP-712) Implementation Plan

> **For agentic workers:** Steps use checkbox (`- [ ]`) syntax for tracking. Implemented inline in branch `feat/uniswap-trading-api-swaps` with a commit per task so any stage can be rolled back.

**Goal:** Add the Uniswap Trading API as a third swap provider in `wdk-evm-wallet`, supporting native-ETH and ERC-20 inputs on `ethereum`/`base` via CLASSIC routing, with full Permit2 EIP-712 signing for ERC-20 inputs.

**Architecture:** Mirror the existing LI.FI REST-provider pattern (`quoteLifiSwap`/`sendLifiSwap` + `#buildLifiEvmSwapPlan`). Two new public methods (`quoteUniswapSwap`/`sendUniswapSwap`) call the Trading API `/quote` and `/swap` endpoints, reuse the existing on-chain allowance/approval/simulation/anti-stale machinery (spender = Permit2 contract), and sign the `permitData` returned by `/quote` with the WDK account's existing `account.signTypedData(...)` (already used for x402). UniswapX (Dutch/Priority) is explicitly out of scope — only `routing === "CLASSIC"` is accepted.

**Tech Stack:** Node.js, `@tetherto/wdk-wallet-evm` (EIP-712 + sendTransaction), ethers v6, Uniswap Trading API (`https://trade-api.gateway.uniswap.org/v1`).

---

## Scope & boundaries

- **In scope:** `ethereum` (1) and `base` (8453); `EXACT_INPUT`; CLASSIC routing; native ETH input (no permit) and ERC-20 input (Permit2 SignatureTransfer EIP-712); single-chain only (no bridge).
- **Out of scope (later phase):** UniswapX (`DUTCH_V2/V3`, `PRIORITY`), `EXACT_OUTPUT`, cross-chain bridge, chains beyond eth/base.
- **Safety invariants preserved:** calldata comes from the trusted Trading API and is **simulated** before broadcast; `swap.to` must equal a known Universal Router address (allow-list); reuse Velora/LI.FI allowance-restore-on-failure; seed/key only in memory via `#withAccount`; anti-stale via `quoteFingerprint` + `minimumTokenOutAmount`.

## Files

- Modify: `wdk-evm-wallet/src/config.js` — add `uniswap*` config keys.
- Modify: `wdk-evm-wallet/src/wdk_evm_wallet.js` — constants, pure helpers, `normalizeUniswapPermitData`, `#uniswapTradingApiRequest`, `#buildUniswapSwapPlan`, `#signUniswapPermit`, `#formatUniswapSwapResponse`, public `quoteUniswapSwap`/`sendUniswapSwap`.
- Modify: `wdk-evm-wallet/src/server.js` — routes `/v1/evm/uniswap/swap/quote|send` + error codes.
- Create: `wdk-evm-wallet/tests/unit_uniswap_helpers.mjs` — `node:test` unit tests for pure helpers.
- Create: `wdk-evm-wallet/tests/smoke_uniswap_runtime.mjs` — gated live smoke test.
- Modify: `wdk-evm-wallet/.env.example`, `wdk-evm-wallet/README.md`, `wdk-evm-wallet/package.json` (test scripts).

## Testing note (TDD deviation, deliberate)

The repo has **no unit harness for API/runtime code** — existing tests are live `node --test` smoke scripts gated on keys/funds. So:
- **Pure logic** (`normalizeUniswapTokenAddress`, `assertUniswapSupportedNetwork`, slippage bps→percent, `normalizeUniswapPermitData`) is built **test-first** with `node:test` (`unit_uniswap_helpers.mjs`) — no network needed.
- **API-dependent flow** is validated by a smoke script that requires `UNISWAP_API_KEY` (and, for `send`, funds), matching the Velora/LI.FI/Aave testing convention.

---

## Task 1: Config keys

**Files:** Modify `wdk-evm-wallet/src/config.js:281-287` (the return block, after the `lifi*`/`lido*` keys).

- [ ] **Step 1:** Add to the returned config object (after `lidoReferralAddress`):

```js
    uniswapTradingApiBaseUrl:
      String(env.UNISWAP_TRADING_API_BASE_URL ?? "").trim() ||
      "https://trade-api.gateway.uniswap.org/v1",
    uniswapApiKey: String(env.UNISWAP_API_KEY ?? "").trim(),
    uniswapRouterVersion: String(env.UNISWAP_ROUTER_VERSION ?? "").trim() || "2.0",
    uniswapDefaultSlippageBps: parseInteger(
      env.UNISWAP_DEFAULT_SLIPPAGE_BPS,
      50,
      "UNISWAP_DEFAULT_SLIPPAGE_BPS"
    ),
```

- [ ] **Step 2:** `node --check src/config.js` → expect no output (pass).
- [ ] **Step 3:** Commit `feat(config): add uniswap trading api config keys`.

## Task 2: Constants + pure token/network/slippage helpers (TDD)

**Files:** Modify `wdk_evm_wallet.js` (constants near line 17-21; helpers near the other `normalize*`/`assert*` functions ~239-297). Test: create `tests/unit_uniswap_helpers.mjs`.

- [ ] **Step 1 (test first):** Create `tests/unit_uniswap_helpers.mjs`:

```js
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  __testables,
} from "../src/wdk_evm_wallet.js";

const {
  PERMIT2_ADDRESS,
  UNISWAP_SUPPORTED_CHAIN_IDS,
  normalizeUniswapTokenAddress,
  assertUniswapSupportedNetwork,
  uniswapSlippagePercentFromBps,
} = __testables;

test("native aliases normalize to zero address", () => {
  assert.equal(normalizeUniswapTokenAddress("native", "tokenIn"), "0x0000000000000000000000000000000000000000");
  assert.equal(normalizeUniswapTokenAddress("ETH", "tokenIn"), "0x0000000000000000000000000000000000000000");
});

test("erc20 address is lowercased and validated", () => {
  assert.equal(
    normalizeUniswapTokenAddress("0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48", "tokenOut"),
    "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"
  );
});

test("supported network assertion", () => {
  assert.equal(assertUniswapSupportedNetwork("ethereum"), 1);
  assert.equal(assertUniswapSupportedNetwork("base"), 8453);
  assert.throws(() => assertUniswapSupportedNetwork("sepolia"));
});

test("slippage bps to percent", () => {
  assert.equal(uniswapSlippagePercentFromBps(50), 0.5);
  assert.equal(uniswapSlippagePercentFromBps(100), 1);
  assert.throws(() => uniswapSlippagePercentFromBps(-1));
  assert.throws(() => uniswapSlippagePercentFromBps(6000));
});

assert.ok(PERMIT2_ADDRESS);
assert.deepEqual(UNISWAP_SUPPORTED_CHAIN_IDS, { ethereum: 1, base: 8453 });
```

- [ ] **Step 2:** Run `cd wdk-evm-wallet && node --test tests/unit_uniswap_helpers.mjs` → expect FAIL (`__testables` undefined / not exported).

- [ ] **Step 3:** Add constants after line 21 in `wdk_evm_wallet.js`:

```js
const PERMIT2_ADDRESS = "0x000000000022D473030F116dDEE9F6B43aC78BA3";
const UNISWAP_SUPPORTED_CHAIN_IDS = { ethereum: 1, base: 8453 };
// Universal Router v2.0 allow-list (defense-in-depth: /swap response `to` must match)
const UNISWAP_UNIVERSAL_ROUTER_BY_NETWORK = {
  ethereum: "0x66a9893cc07d91d95644aedd05d03f95e1dba8af",
  base: "0x6ff5693b99212da76ad316178a184ab56d299b43",
};
```

- [ ] **Step 4:** Add pure helpers near line 297 (after `parseLifiSlippage`):

```js
function normalizeUniswapTokenAddress(value, fieldName) {
  return normalizeEvmTokenAddressAllowingNative(value, fieldName);
}

function assertUniswapSupportedNetwork(network) {
  const chainId = UNISWAP_SUPPORTED_CHAIN_IDS[network];
  if (!chainId) {
    throw new Error(
      "Uniswap Trading API swaps are currently supported only on ethereum and base mainnet."
    );
  }
  return chainId;
}

function uniswapSlippagePercentFromBps(bps) {
  const parsed = Number(bps);
  if (!Number.isInteger(parsed) || parsed < 0 || parsed > 5000) {
    throw new Error("slippageBps must be an integer between 0 and 5000.");
  }
  return parsed / 100;
}
```

- [ ] **Step 5:** Export a `__testables` object at the end of the module (append near the end of the file, after the class/exports). Add `normalizeUniswapTokenAddress`, `assertUniswapSupportedNetwork`, `uniswapSlippagePercentFromBps`, `normalizeUniswapPermitData` (added in Task 3 — include now as a forward reference only after Task 3), `PERMIT2_ADDRESS`, `UNISWAP_SUPPORTED_CHAIN_IDS`:

```js
export const __testables = {
  PERMIT2_ADDRESS,
  UNISWAP_SUPPORTED_CHAIN_IDS,
  normalizeUniswapTokenAddress,
  assertUniswapSupportedNetwork,
  uniswapSlippagePercentFromBps,
};
```

- [ ] **Step 6:** Run `node --test tests/unit_uniswap_helpers.mjs` → expect PASS. Run `npm run check` → pass.
- [ ] **Step 7:** Commit `feat(swap): add uniswap constants and pure helpers with unit tests`.

## Task 3: `normalizeUniswapPermitData` (EIP-712 normalizer, TDD)

**Files:** Modify `wdk_evm_wallet.js` (add function near `normalizeX402ExactTypedData` ~338). Test: extend `tests/unit_uniswap_helpers.mjs`.

The Trading API `/quote` returns `permitData = { domain, types, values }`. WDK `account.signTypedData(domain, types, message)` (ethers v6) requires `types` **without** the `EIP712Domain` entry, and `message = values`. Validate `domain.chainId === runtimeConfig.chainId`.

- [ ] **Step 1 (test first):** Append to `tests/unit_uniswap_helpers.mjs`:

```js
const { normalizeUniswapPermitData } = __testables;

test("permitData strips EIP712Domain and maps values to message", () => {
  const permitData = {
    domain: { name: "Permit2", chainId: 1, verifyingContract: PERMIT2_ADDRESS },
    types: {
      EIP712Domain: [
        { name: "name", type: "string" },
        { name: "chainId", type: "uint256" },
        { name: "verifyingContract", type: "address" },
      ],
      PermitTransferFrom: [{ name: "permitted", type: "TokenPermissions" }],
      TokenPermissions: [{ name: "token", type: "address" }],
    },
    values: { permitted: { token: "0xabc" } },
  };
  const out = normalizeUniswapPermitData(permitData, { chainId: 1 });
  assert.equal(out.types.EIP712Domain, undefined);
  assert.ok(out.types.PermitTransferFrom);
  assert.deepEqual(out.message, { permitted: { token: "0xabc" } });
  assert.equal(out.domain.chainId, 1);
});

test("permitData rejects chainId mismatch", () => {
  const permitData = { domain: { chainId: 8453 }, types: { X: [{ name: "a", type: "uint256" }] }, values: {} };
  assert.throws(() => normalizeUniswapPermitData(permitData, { chainId: 1 }));
});
```

- [ ] **Step 2:** Run `node --test tests/unit_uniswap_helpers.mjs` → expect FAIL.

- [ ] **Step 3:** Add the function after `normalizeX402ExactTypedData` (~394):

```js
function normalizeUniswapPermitData(permitData, runtimeConfig) {
  const data = assertPlainObject(permitData, "permitData");
  const domain = assertPlainObject(data.domain, "permitData.domain");
  const domainChainId = assertNonNegativeInteger(domain.chainId, "permitData.domain.chainId");
  if (domainChainId !== runtimeConfig.chainId) {
    throw new Error("permitData.domain.chainId must match the active network chain id.");
  }
  const typesObject = assertPlainObject(data.types, "permitData.types");
  const normalizedTypes = {};
  for (const [typeName, fields] of Object.entries(typesObject)) {
    if (typeName === "EIP712Domain") {
      continue; // ethers infers the domain type; including it throws
    }
    if (!Array.isArray(fields) || fields.length === 0) {
      throw new Error(`permitData.types.${typeName} must be a non-empty array.`);
    }
    normalizedTypes[typeName] = fields.map((field, index) => {
      const f = assertPlainObject(field, `permitData.types.${typeName}[${index}]`);
      return {
        name: assertNonEmptyString(f.name, `permitData.types.${typeName}[${index}].name`),
        type: assertNonEmptyString(f.type, `permitData.types.${typeName}[${index}].type`),
      };
    });
  }
  if (Object.keys(normalizedTypes).length === 0) {
    throw new Error("permitData.types must contain at least one non-domain type.");
  }
  const message = assertPlainObject(data.values, "permitData.values");
  return { domain, types: normalizedTypes, message };
}
```

- [ ] **Step 4:** Add `normalizeUniswapPermitData` to the `__testables` export object.
- [ ] **Step 5:** Run `node --test tests/unit_uniswap_helpers.mjs` → expect PASS. `npm run check` → pass.
- [ ] **Step 6:** Commit `feat(swap): add uniswap permitData EIP-712 normalizer with unit tests`.

## Task 4: Trading API request helper + quote fetch + plan builder

**Files:** Modify `wdk_evm_wallet.js` (private methods near the LI.FI block ~2685-2820).

- [ ] **Step 1:** Add `#uniswapTradingApiRequest(pathname, body)` — POST JSON with required headers, error shaping like `#fetchLifiQuote`:

```js
  async #uniswapTradingApiRequest(pathname, body) {
    if (!this.config.uniswapApiKey) {
      throw createTaggedError(
        "UNISWAP_API_KEY is not configured. Set it to use Uniswap Trading API swaps.",
        "uniswap_api_key_missing",
        { provider: "uniswap" }
      );
    }
    const base = String(this.config.uniswapTradingApiBaseUrl).replace(/\/+$/, "");
    let response;
    try {
      response = await fetch(`${base}${pathname}`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Accept: "application/json",
          "x-api-key": this.config.uniswapApiKey,
          "x-universal-router-version": this.config.uniswapRouterVersion,
        },
        body: JSON.stringify(body),
      });
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      throw createTaggedError(`Uniswap Trading API unavailable: ${message}`, "network_unavailable", {
        provider: "uniswap",
        pathname,
      });
    }
    let payload;
    try {
      payload = await response.json();
    } catch {
      payload = null;
    }
    if (!response.ok) {
      const message =
        payload?.detail || payload?.message || payload?.error || `Uniswap Trading API ${pathname} failed with HTTP ${response.status}.`;
      throw createTaggedError(String(message), "network_unavailable", {
        provider: "uniswap",
        pathname,
        httpStatus: response.status,
      });
    }
    if (!payload || typeof payload !== "object") {
      throw createTaggedError(`Uniswap Trading API ${pathname} returned an empty response.`, "network_unavailable", {
        provider: "uniswap",
        pathname,
      });
    }
    return payload;
  }
```

- [ ] **Step 2:** Add `#fetchUniswapQuote({ runtimeConfig, address, swapRequest })`:

```js
  async #fetchUniswapQuote({ runtimeConfig, address, swapRequest }) {
    const chainId = UNISWAP_SUPPORTED_CHAIN_IDS[runtimeConfig.network];
    const payload = await this.#uniswapTradingApiRequest("/quote", {
      swapper: address,
      tokenIn: swapRequest.tokenIn,
      tokenOut: swapRequest.tokenOut,
      tokenInChainId: chainId,
      tokenOutChainId: chainId,
      amount: swapRequest.tokenInAmount.toString(),
      type: "EXACT_INPUT",
      slippageTolerance: swapRequest.slippagePercent,
      routingPreference: "CLASSIC",
    });
    const routing = String(payload.routing || "").toUpperCase();
    if (routing !== "CLASSIC") {
      throw createTaggedError(
        `Uniswap returned unsupported routing '${routing}'. Only CLASSIC is enabled in this runtime.`,
        "uniswap_unsupported_route",
        { provider: "uniswap", routing }
      );
    }
    return payload;
  }
```

- [ ] **Step 3:** Add `#buildUniswapSwapPlan({ account, runtimeConfig, address, swapRequest, tolerateSwapFeeFailure })` — mirror `#buildLifiEvmSwapPlan` (lines 2685-2818) but: spender = `PERMIT2_ADDRESS` for ERC-20; obtain the swap calldata via `/swap` (carrying `permitData`/signature handled in send — for the *plan/quote* we do NOT call `/swap`, we only need the routing/output/permitData). Build:
  - `quoteResponse` from `#fetchUniswapQuote`
  - `permitData = quoteResponse.permitData ?? null`
  - `isNativeTokenIn = isZeroAddress(swapRequest.tokenIn)`
  - `spender = isNativeTokenIn ? null : PERMIT2_ADDRESS`
  - allowance/approval via `#getSwapAllowanceState` + `#buildSwapApprovalPlan` (skip when native) — same as LI.FI
  - `tokenOutAmount = BigInt(quoteResponse.quote.output.amount)`; `minimumTokenOutAmount = BigInt(quoteResponse.quote.output.amount)` adjusted by slippage is provided by the API as the floor — use `quoteResponse.quote.output.amount` for display and compute min via the API's `slippage`-derived value if present, else `tokenOutAmount`. (CLASSIC `quote` has no explicit min; record `tokenOutAmount` and rely on on-chain slippage encoded in calldata.)
  - `quoteFingerprint = sha256Hex(JSON.stringify({ chainId, from: address.toLowerCase(), tokenIn, tokenOut, tokenInAmount, output: tokenOutAmount.toString(), routing, gasFee: quoteResponse.quote.gasFee ?? null }))`
  - return `{ quoteResponse, permitData, isNativeTokenIn, spender, currentAllowance, allowanceReadError, approval, tokenInAmount, tokenOutAmount, minimumTokenOutAmount, quoteFingerprint, gasFeeUSD: quoteResponse.quote.gasFeeUSD ?? null, router: UNISWAP_UNIVERSAL_ROUTER_BY_NETWORK[runtimeConfig.network] }`

- [ ] **Step 4:** `npm run check` → pass. Commit `feat(swap): add uniswap trading api request + quote plan builder`.

## Task 5: Permit signing + `/swap` calldata + Universal Router allow-list

**Files:** Modify `wdk_evm_wallet.js`.

- [ ] **Step 1:** Add `#signUniswapPermit(account, permitData, runtimeConfig)`:

```js
  async #signUniswapPermit(account, permitData, runtimeConfig) {
    const typed = normalizeUniswapPermitData(permitData, runtimeConfig);
    return account.signTypedData({
      domain: typed.domain,
      types: typed.types,
      message: typed.message,
    });
  }
```

- [ ] **Step 2:** Add `#fetchUniswapSwapCalldata({ runtimeConfig, quoteResponse, permitData, signature })` — POST `/swap` with the spread quote, stripping `permitData`/`permitTransaction` then re-attaching for CLASSIC only when present, per the official rules:

```js
  async #fetchUniswapSwapCalldata({ runtimeConfig, quoteResponse, permitData, signature }) {
    const { permitData: _pd, permitTransaction: _pt, ...cleanQuote } = quoteResponse;
    const body = { ...cleanQuote };
    if (signature && permitData) {
      body.signature = signature;
      body.permitData = permitData; // CLASSIC: router needs permitData on-chain
    }
    const payload = await this.#uniswapTradingApiRequest("/swap", body);
    const swap = payload.swap || {};
    const to = normalizeAddress(String(swap.to || ""), "swap.to");
    const expectedRouter = UNISWAP_UNIVERSAL_ROUTER_BY_NETWORK[runtimeConfig.network];
    if (to.toLowerCase() !== expectedRouter) {
      throw createTaggedError(
        "Uniswap /swap returned an unexpected target contract.",
        "uniswap_unexpected_router",
        { provider: "uniswap", to: to.toLowerCase(), expected: expectedRouter }
      );
    }
    const data = assertNonEmptyString(String(swap.data || ""), "swap.data");
    if (data === "0x") {
      throw createTaggedError("Uniswap /swap returned empty calldata (quote expired).", "swap_quote_changed", {
        provider: "uniswap",
      });
    }
    return {
      to,
      data,
      value: parseHexOrDecimalBigInt(swap.value || "0", "swap.value"),
    };
  }
```

- [ ] **Step 3:** `npm run check` → pass. Commit `feat(swap): add uniswap permit signing and /swap calldata fetch`.

## Task 6: Public `quoteUniswapSwap` + `#formatUniswapSwapResponse`

**Files:** Modify `wdk_evm_wallet.js` (add after `sendLifiSwap`, ~2170).

- [ ] **Step 1:** Add `buildUniswapSwapRequest({ tokenIn, tokenOut, tokenInAmount, slippageBps })` near `buildLifiEvmSwapRequest` (~404):

```js
function buildUniswapSwapRequest({ tokenIn, tokenOut, tokenInAmount, slippageBps }) {
  const req = {
    tokenIn: normalizeUniswapTokenAddress(tokenIn, "tokenIn"),
    tokenOut: normalizeUniswapTokenAddress(tokenOut, "tokenOut"),
    tokenInAmount: assertPositiveBigIntString(tokenInAmount, "tokenInAmount"),
    slippagePercent: uniswapSlippagePercentFromBps(
      slippageBps === undefined || slippageBps === null ? 50 : slippageBps
    ),
  };
  assertDistinctAddresses(req.tokenIn, "tokenIn", req.tokenOut, "tokenOut");
  return req;
}
```

> Note: `buildUniswapSwapRequest` reads default slippage 50 bps; callers that want the config default pass `slippageBps: this.config.uniswapDefaultSlippageBps`.

- [ ] **Step 2:** Add `quoteUniswapSwap` (read-only, `#withReadableAccount`) mirroring `quoteLifiSwap` (1922-1969): assert network, build request with `slippageBps ?? this.config.uniswapDefaultSlippageBps`, build plan with `tolerateSwapFeeFailure: true`, return `this.#formatUniswapSwapResponse(...)`.

- [ ] **Step 3:** Add `#formatUniswapSwapResponse({ runtimeConfig, accountIndex, address, swapRequest, plan })` mirroring `#formatLifiSwapResponse` (2888-2941): `protocol: "uniswap"`, include `tokenInMetadata`/`outputTokenMetadata` (via `#getSwapTokenMetadata`), `inputAmountFormatted`/`outputAmountFormatted`, `quoteFingerprint`, `slippageBps: swapRequest... `, `permitRequired: plan.permitData !== null`, `routing: "CLASSIC"`, `router: plan.router`, `gasFeeUSD: plan.gasFeeUSD`, `allowance{...}`, `source: "uniswap-trading-api"`. Do **not** include raw `permitData` secrets beyond a boolean flag in the quote response.

- [ ] **Step 4:** `npm run check` → pass. Commit `feat(swap): add quoteUniswapSwap read-only preview`.

## Task 7: Public `sendUniswapSwap`

**Files:** Modify `wdk_evm_wallet.js` (add after `quoteUniswapSwap`).

- [ ] **Step 1:** Implement `sendUniswapSwap` (`#withAccount`), mirroring `swap` (1971-2121) and `sendLifiSwap`:
  1. `assertUniswapSupportedNetwork`; build request; `address = account.getAddress()`.
  2. `initialPlan = #buildUniswapSwapPlan(...)`; metadata; `#assertExpectedSwapFingerprint`; `#assertMinimumSwapOutput`.
  3. `approvalExecution = #executeSwapApprovalsIfNeeded({ account, runtimeConfig, swapRequest, plan: initialPlan })` (spender already Permit2 in plan).
  4. If approval performed → `finalPlan = #buildUniswapSwapPlan(...)` again (fresh quote + fresh `permitData`), re-assert fingerprint/minimum.
  5. `signature = finalPlan.isNativeTokenIn ? null : await #signUniswapPermit(account, finalPlan.permitData, runtimeConfig)` (only when `permitData` present).
  6. `swapTx = await #fetchUniswapSwapCalldata({ runtimeConfig, quoteResponse: finalPlan.quoteResponse, permitData: finalPlan.permitData, signature })`.
  7. `simulation = await #simulatePreparedTransaction({ runtimeConfig, from: address, tx: swapTx })`; `#assertSimulationSucceeded`.
  8. `{ hash } = await account.sendTransaction(swapTx)`.
  9. On any error in the try block → `#restoreAllowanceAfterFailedSwap(...)` + `#throwSwapFailureWithCleanup(...)` (same as `swap`).
  10. Return the `#formatUniswapSwapResponse(...)` shape augmented with `result: { hash, approveHash?, tokenInAmount, tokenOutAmount }`.

- [ ] **Step 2:** `npm run check` → pass. Commit `feat(swap): add sendUniswapSwap execution with permit + simulation`.

## Task 8: Routes + error codes

**Files:** Modify `server.js` (routes after the LI.FI block ~532; error classifier 30-46 and 122-135).

- [ ] **Step 1:** Add routes mirroring LI.FI (522-532):

```js
    if (method === "POST" && url.pathname === "/v1/evm/uniswap/swap/quote") {
      const body = await withResolvedNetwork(await withResolvedSeedOrAddress(await readJsonBody(request)));
      const data = await service.quoteUniswapSwap(body);
      return sendJson(response, 200, { ok: true, data });
    }

    if (method === "POST" && url.pathname === "/v1/evm/uniswap/swap/send") {
      const body = await withResolvedNetwork(await withResolvedSeed(await readJsonBody(request)));
      const data = await service.sendUniswapSwap(body);
      return sendJson(response, 200, { ok: true, data });
    }
```

- [ ] **Step 2:** In `normalizeErrorCode` add to the pass-through list (line ~37-43): `"uniswap_api_key_missing"`, `"uniswap_unsupported_route"`, `"uniswap_unexpected_router"`.
- [ ] **Step 3:** In `errorStatusCode`: map `uniswap_api_key_missing` → 400, `uniswap_unsupported_route` → 422, `uniswap_unexpected_router` → 502.
- [ ] **Step 4:** `npm run check` → pass. Commit `feat(server): expose uniswap swap routes and error codes`.

## Task 9: Smoke test (gated)

**Files:** Create `tests/smoke_uniswap_runtime.mjs`; modify `package.json` test scripts.

- [ ] **Step 1:** Create a `node:test` smoke modeled on `tests/smoke_swap_runtime.mjs` that:
  - skips (logs) when `UNISWAP_API_KEY` or a test seed is unset;
  - calls `quoteUniswapSwap` for native ETH → USDC on `base`, asserts `routing/protocol === "uniswap"`, `outputAmountFormatted` present, `permitRequired === false`;
  - calls `quoteUniswapSwap` for USDC → ETH on `base`, asserts `permitRequired === true` and `allowance` block present;
  - `send` only runs when `UNISWAP_SMOKE_SEND=1` and funded.
- [ ] **Step 2:** Add to `package.json` scripts: `"test:uniswap-runtime": "node --test --test-concurrency=1 tests/smoke_uniswap_runtime.mjs"` and `"test:unit": "node --test tests/unit_uniswap_helpers.mjs"`.
- [ ] **Step 3:** Run `npm run test:unit` → PASS. Commit `test(swap): add uniswap unit + gated smoke tests`.

## Task 10: Docs + env

**Files:** Modify `.env.example`, `README.md`.

- [ ] **Step 1:** `.env.example`: add `UNISWAP_API_KEY=`, `UNISWAP_TRADING_API_BASE_URL=`, `UNISWAP_ROUTER_VERSION=2.0`, `UNISWAP_DEFAULT_SLIPPAGE_BPS=50` with comments.
- [ ] **Step 2:** `README.md`: add the two routes to the API list; add a "Swap providers" note (Velora / LI.FI / Uniswap Trading API), Uniswap scope (eth+base, CLASSIC, native+ERC-20 via Permit2 EIP-712), and the `UNISWAP_API_KEY` requirement + config vars.
- [ ] **Step 3:** Commit `docs: document uniswap trading api swap provider`.

---

## Self-review checklist
- Spec coverage: EIP-712 (Task 3,5,7), ERC-20→X via Permit2 (Task 4-7), API key handling (Task 1,4 + `uniswap_api_key_missing`), CLASSIC-only guard (Task 4), router allow-list (Task 2,5). ✓
- Type consistency: `#buildUniswapSwapPlan` returns `{ quoteResponse, permitData, isNativeTokenIn, spender, currentAllowance, allowanceReadError, approval, tokenInAmount, tokenOutAmount, minimumTokenOutAmount, quoteFingerprint, gasFeeUSD, router }`, consumed identically in Tasks 6 & 7. ✓
- Open empirical items (resolve during Task 9 with a live key): exact `quote.output.amount`/`gasFee`/`gasFeeUSD`/`permitData` JSON paths; confirm `routingPreference:"CLASSIC"` suppresses UniswapX for ERC-20 input; confirm Universal Router addresses in the allow-list for eth/base.
