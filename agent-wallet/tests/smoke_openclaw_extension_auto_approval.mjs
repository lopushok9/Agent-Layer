import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const ROOT = path.resolve(path.dirname(new URL(import.meta.url).pathname), "..", "..");
const SOURCE = path.join(ROOT, ".openclaw", "extensions", "agent-wallet", "index.ts");

function fakeApprovalToken(toolName, summary) {
  const payload = {
    v: 1,
    binding: {
      tool: toolName,
      network: "mainnet",
      summary,
    },
  };
  const encoded = Buffer.from(
    JSON.stringify(payload),
    "utf8"
  ).toString("base64url");
  return `${encoded}.fake-signature`;
}

function parseCliArgs(args) {
  const get = (name) => {
    const idx = args.indexOf(name);
    return idx >= 0 ? args[idx + 1] : undefined;
  };
  return {
    command: args[2],
    userId: get("--user-id"),
    tool: get("--tool"),
    config: JSON.parse(get("--config-json") || "{}"),
    arguments: JSON.parse(get("--arguments-json") || "{}"),
    summary: JSON.parse(get("--summary-json") || "{}"),
    mainnetConfirmed: args.includes("--mainnet-confirmed"),
  };
}

async function main() {
  let source = fs.readFileSync(SOURCE, "utf8");
  source = source.replace(
    'import { execFile } from "node:child_process";',
    "const execFile = globalThis.__TEST_EXEC_FILE__;"
  );
  source = source.replace(
    "const execFileAsync = promisify(execFile);",
    "const execFileAsync = (...args) => globalThis.__TEST_EXEC_FILE_ASYNC__(...args);"
  );

  const preview = {
    chain: "solana",
    network: "mainnet",
    is_mainnet: true,
    mode: "preview",
    asset_type: "swap",
    input_mint: "So11111111111111111111111111111111111111112",
    output_mint: "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
    input_amount_ui: 0.056,
    slippage_bps: 100,
    swap_provider: "jupiter",
    estimated_output_amount_ui: 4.95,
    minimum_output_amount_ui: 4.9,
    price_impact_pct: 0.01,
    route_plan: [{ market: "test" }],
    fee_summary: { priority_fee_sol: 0.002 },
    confirmation_summary: {
      operation: "Swap",
      network: "mainnet",
      swap_provider: "jupiter",
      estimated_output_amount_ui: 4.95,
      minimum_output_amount_ui: 4.9,
      price_impact_pct: 0.01,
      quote_fingerprint: "preview-fingerprint",
      input_mint: "So11111111111111111111111111111111111111112",
      output_mint: "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
      input_amount_ui: 0.056,
      slippage_bps: 100,
    },
  };
  const preparedPreview = {
    ...preview,
    mode: "prepare",
    prepared: false,
    signed: false,
    broadcasted: false,
    confirmed: false,
    execution_plan_only: true,
  };
  const evmPrepared = {
    chain: "evm",
    network: "base",
    is_mainnet: true,
    mode: "prepare",
    asset_type: "swap",
    input_amount_raw: "1000000",
    token_in: "0x1111111111111111111111111111111111111111",
    token_out: "0x2222222222222222222222222222222222222222",
    swap_provider: "velora",
    estimated_output_amount_raw: "995000",
    minimum_output_amount_raw: "985050",
    price_impact_pct: 0.002,
    fee_summary: { gas_fee_native: "4722815300334" },
    confirmation_summary: {
      operation: "EVM swap",
      network: "base",
      swap_provider: "velora",
      estimated_output_amount_raw: "995000",
      minimum_output_amount_raw: "985050",
      price_impact_pct: 0.002,
      quote_fingerprint: "evm-prepare-fingerprint",
      token_in: "0x1111111111111111111111111111111111111111",
      token_out: "0x2222222222222222222222222222222222222222",
      input_amount_raw: "1000000",
    },
  };
  const solTransferPrepared = {
    chain: "solana",
    network: "mainnet",
    is_mainnet: true,
    mode: "prepare",
    asset_type: "transfer",
    recipient: "7dHbWXmci3dT8UF2LQbYkWQy3YJX6m6x98M5VvXwZLad",
    amount: 0.01,
    confirmation_summary: {
      operation: "Transfer SOL",
      network: "mainnet",
      recipient: "7dHbWXmci3dT8UF2LQbYkWQy3YJX6m6x98M5VvXwZLad",
      amount_sol: 0.01,
    },
  };
  const evmTransferPrepared = {
    chain: "evm",
    network: "base",
    is_mainnet: true,
    mode: "prepare",
    asset_type: "transfer",
    recipient: "0x3333333333333333333333333333333333333333",
    amount_wei: "100000000000000",
    confirmation_summary: {
      operation: "EVM native transfer",
      network: "base",
      recipient: "0x3333333333333333333333333333333333333333",
      amount_wei: "100000000000000",
    },
  };
  const x402Preview = {
    mode: "preview",
    network: "solana:mainnet",
    is_mainnet: true,
    response_status: 402,
    response_headers: { "content-type": "application/json" },
    confirmation_summary: {
      operation: "x402 Paid Request",
      network: "solana:mainnet",
      amount_usdc: 0.001,
      amount_raw: "1000",
      asset: "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
      pay_to: "6KsbSAzhFe5YzqBK9ngeZzdU5xauZsni9osQeB8rSy5R",
      method: "POST",
      url: "https://x402.alchemy.com/solana-mainnet/v2",
    },
  };
  const staleSwapToken = fakeApprovalToken("swap_solana_tokens", {
    operation: "Swap",
    network: "mainnet",
    _preview_digest: "stale-preview-digest",
  });

  const calls = [];
  globalThis.__TEST_EXEC_FILE_ASYNC__ = async (pythonBin, args, options) => {
    const parsed = parseCliArgs(args);
    calls.push({ pythonBin, args, options, parsed });
    if (parsed.command === "invoke" && parsed.tool === "swap_solana_tokens" && parsed.arguments.mode === "preview") {
      return { stdout: JSON.stringify({ ok: true, data: preview }), stderr: "" };
    }
    if (parsed.command === "invoke" && parsed.tool === "swap_solana_tokens" && parsed.arguments.mode === "prepare") {
      return { stdout: JSON.stringify({ ok: true, data: preparedPreview }), stderr: "" };
    }
    if (parsed.command === "invoke" && parsed.tool === "swap_evm_tokens" && parsed.arguments.mode === "prepare") {
      return { stdout: JSON.stringify({ ok: true, data: evmPrepared }), stderr: "" };
    }
    if (parsed.command === "invoke" && parsed.tool === "transfer_sol" && parsed.arguments.mode === "prepare") {
      return { stdout: JSON.stringify({ ok: true, data: solTransferPrepared }), stderr: "" };
    }
    if (parsed.command === "invoke" && parsed.tool === "transfer_evm_native" && parsed.arguments.mode === "prepare") {
      return { stdout: JSON.stringify({ ok: true, data: evmTransferPrepared }), stderr: "" };
    }
    if (
      parsed.command === "invoke" &&
      parsed.tool === "x402_preview_request" &&
      parsed.arguments.url === x402Preview.confirmation_summary.url
    ) {
      return { stdout: JSON.stringify({ ok: true, data: x402Preview }), stderr: "" };
    }
    if (parsed.command === "issue-approval") {
      assert.ok(["swap_solana_tokens", "swap_evm_tokens", "transfer_sol", "transfer_evm_native", "x402_pay_request"].includes(parsed.tool));
      assert.equal(parsed.mainnetConfirmed, true);
      if (parsed.tool === "swap_solana_tokens") {
        assert.equal(typeof parsed.summary._preview_digest, "string");
        assert.ok(parsed.summary._preview_digest.length > 10);
      } else if (parsed.tool === "swap_evm_tokens") {
        assert.equal(parsed.summary._preview_digest, undefined);
        assert.equal(parsed.summary.network, "base");
        assert.equal(parsed.summary.input_amount_raw, "1000000");
      } else if (parsed.tool === "transfer_sol") {
        assert.equal(parsed.summary._preview_digest, undefined);
        assert.equal(parsed.summary.recipient, solTransferPrepared.recipient);
      } else if (parsed.tool === "transfer_evm_native") {
        assert.equal(parsed.summary._preview_digest, undefined);
        assert.equal(parsed.summary.recipient, evmTransferPrepared.recipient);
      } else {
        assert.equal(parsed.summary._preview_digest, undefined);
      }
      return {
        stdout: JSON.stringify({ ok: true, approval_token: fakeApprovalToken(parsed.tool, parsed.summary) }),
        stderr: "",
      };
    }
    if (parsed.command === "invoke" && parsed.tool === "swap_solana_tokens" && parsed.arguments.mode === "execute") {
      assert.equal(parsed.tool, "swap_solana_tokens");
      assert.equal(typeof parsed.arguments.approval_token, "string");
      assert.notEqual(parsed.arguments.approval_token, staleSwapToken);
      assert.equal(parsed.arguments._approved_preview.input_mint, preparedPreview.input_mint);
      assert.equal(parsed.arguments._approved_preview.mode, "prepare");
      return { stdout: JSON.stringify({ ok: true, data: { executed: true } }), stderr: "" };
    }
    if (parsed.command === "invoke" && parsed.tool === "swap_evm_tokens" && parsed.arguments.mode === "execute") {
      assert.equal(typeof parsed.arguments.approval_token, "string");
      assert.equal(parsed.arguments.approval_token.includes("."), true);
      return { stdout: JSON.stringify({ ok: true, data: { hash: "0xevmhash" } }), stderr: "" };
    }
    if (parsed.command === "invoke" && parsed.tool === "transfer_sol" && parsed.arguments.mode === "execute") {
      assert.equal(typeof parsed.arguments.approval_token, "string");
      assert.equal(parsed.arguments._approved_preview, undefined);
      return { stdout: JSON.stringify({ ok: true, data: { signature: "sol-transfer-sig" } }), stderr: "" };
    }
    if (parsed.command === "invoke" && parsed.tool === "transfer_evm_native" && parsed.arguments.mode === "execute") {
      assert.equal(typeof parsed.arguments.approval_token, "string");
      assert.equal(parsed.arguments._approved_preview, undefined);
      return { stdout: JSON.stringify({ ok: true, data: { hash: "0xevmtransferhash" } }), stderr: "" };
    }
    if (parsed.command === "invoke" && parsed.tool === "x402_pay_request" && parsed.arguments.mode === "execute") {
      assert.equal(typeof parsed.arguments.approval_token, "string");
      return { stdout: JSON.stringify({ ok: true, data: { paid: true } }), stderr: "" };
    }
    throw new Error(`Unexpected command: ${JSON.stringify(parsed)}`);
  };
  globalThis.__TEST_EXEC_FILE__ = (pythonBin, args, options, callback) => {
    globalThis.__TEST_EXEC_FILE_ASYNC__(pythonBin, args, options)
      .then(({ stdout, stderr }) => callback(null, stdout, stderr))
      .catch((error) => callback(error));
  };

  const moduleUrl = `data:text/javascript;charset=utf-8,${encodeURIComponent(source)}`;
  const mod = await import(moduleUrl);
  const register = mod.default;

  const tools = [];
  const api = {
    config: {
      plugins: {
        entries: {
          "agent-wallet": {
            config: {
              userId: "openclaw-test-user",
              backend: "solana_local",
              network: "mainnet",
              packageRoot: path.join(ROOT, "agent-wallet"),
              pythonBin: "/tmp/fake-python",
            },
          },
        },
      },
    },
    logger: { info() {}, debug() {} },
    registerTool(definition) {
      tools.push(definition);
    },
  };

  register(api);
  const swapTool = tools.find((tool) => tool.name === "swap_solana_tokens");
  assert.ok(swapTool, "swap_solana_tokens tool should be registered");
  const x402PreviewTool = tools.find((tool) => tool.name === "x402_preview_request");
  assert.ok(x402PreviewTool, "x402_preview_request tool should be registered");
  const x402PayTool = tools.find((tool) => tool.name === "x402_pay_request");
  assert.ok(x402PayTool, "x402_pay_request tool should be registered");
  for (const tool of tools) {
    assert.equal(
      tool.parameters?.properties?.approval_token,
      undefined,
      `${tool.name} should not expose approval_token to OpenClaw agents`
    );
  }

  await swapTool.execute("1", {
    input_mint: preview.input_mint,
    output_mint: preview.output_mint,
    amount: 0.056,
    slippage_bps: 100,
    mode: "prepare",
    purpose: "test prepare",
    user_intent: true,
  });

  const executed = await swapTool.execute("2", {
    input_mint: preview.input_mint,
    output_mint: preview.output_mint,
    amount: 0.056,
    slippage_bps: 100,
    mode: "execute",
    purpose: "test execute",
  });

  assert.equal(JSON.parse(executed.content[0].text).executed, true);
  await swapTool.execute("2-stale-agent-token", {
    input_mint: preview.input_mint,
    output_mint: preview.output_mint,
    amount: 0.056,
    slippage_bps: 100,
    mode: "execute",
    purpose: "test execute overwrites stale agent token",
    approval_token: staleSwapToken,
    _approved_preview: { mode: "preview", input_mint: "stale" },
  });

  const evmSwapTool = tools.find((tool) => tool.name === "swap_evm_tokens");
  assert.ok(evmSwapTool, "swap_evm_tokens tool should be registered");
  await evmSwapTool.execute("evm-1", {
    token_in: evmPrepared.token_in,
    token_out: evmPrepared.token_out,
    amount_in_raw: evmPrepared.input_amount_raw,
    mode: "prepare",
    purpose: "test evm prepare",
    user_intent: true,
    network: "base",
  });
  const evmExecuted = await evmSwapTool.execute("evm-2", {
    token_in: evmPrepared.token_in,
    token_out: evmPrepared.token_out,
    amount_in_raw: evmPrepared.input_amount_raw,
    mode: "execute",
    purpose: "test evm execute",
    network: "base",
  });
  assert.equal(JSON.parse(evmExecuted.content[0].text).hash, "0xevmhash");

  const transferSolTool = tools.find((tool) => tool.name === "transfer_sol");
  assert.ok(transferSolTool, "transfer_sol tool should be registered");
  await transferSolTool.execute("sol-transfer-1", {
    recipient: solTransferPrepared.recipient,
    amount: solTransferPrepared.amount,
    mode: "prepare",
    purpose: "test sol transfer prepare",
    user_intent: true,
  });
  const solTransferExecuted = await transferSolTool.execute("sol-transfer-2", {
    recipient: solTransferPrepared.recipient,
    amount: solTransferPrepared.amount,
    mode: "execute",
    purpose: "test sol transfer execute",
  });
  assert.equal(JSON.parse(solTransferExecuted.content[0].text).signature, "sol-transfer-sig");

  const evmTransferTool = tools.find((tool) => tool.name === "transfer_evm_native");
  assert.ok(evmTransferTool, "transfer_evm_native tool should be registered");
  await evmTransferTool.execute("evm-transfer-1", {
    recipient: evmTransferPrepared.recipient,
    amount_wei: evmTransferPrepared.amount_wei,
    mode: "prepare",
    purpose: "test evm transfer prepare",
    user_intent: true,
    network: "base",
  });
  const evmTransferExecuted = await evmTransferTool.execute("evm-transfer-2", {
    recipient: evmTransferPrepared.recipient,
    amount_wei: evmTransferPrepared.amount_wei,
    mode: "execute",
    purpose: "test evm transfer execute",
    network: "base",
  });
  assert.equal(JSON.parse(evmTransferExecuted.content[0].text).hash, "0xevmtransferhash");

  const transferSplTool = tools.find((tool) => tool.name === "transfer_spl_token");
  assert.ok(transferSplTool, "transfer_spl_token tool should be registered");
  await assert.rejects(
    () =>
      transferSplTool.execute("spl-transfer-missing-context", {
        recipient: "MissingContext111111111111111111111111111111111",
        mint: "So11111111111111111111111111111111111111112",
        amount: 0.02,
        mode: "execute",
        purpose: "test missing context",
    }),
    (error) => {
      assert.match(error.message, /Confirmation context is not ready or expired/);
      assert.match(error.message, /Do not ask for \/approve, buttons, popups, or a manual token/);
      return true;
    }
  );

  const x402Previewed = await x402PreviewTool.execute("3", {
    url: x402Preview.confirmation_summary.url,
    method: "POST",
    json_body: { jsonrpc: "2.0", id: 1, method: "getBalance", params: ["test"] },
  });
  assert.equal(JSON.parse(x402Previewed.content[0].text).mode, "preview");

  const x402Executed = await x402PayTool.execute("4", {
    url: x402Preview.confirmation_summary.url,
    method: "POST",
    json_body: { jsonrpc: "2.0", id: 1, method: "getBalance", params: ["test"] },
    mode: "execute",
    purpose: "test x402 execute",
  });

  assert.equal(JSON.parse(x402Executed.content[0].text).paid, true);
  assert.equal(
    calls.filter((entry) => entry.parsed.command === "issue-approval").length,
    6
  );

  delete globalThis.__TEST_EXEC_FILE__;
  delete globalThis.__TEST_EXEC_FILE_ASYNC__;
  console.log("smoke_openclaw_extension_auto_approval: ok");
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
