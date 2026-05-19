import { execFile } from "node:child_process";
import crypto from "node:crypto";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { promisify } from "node:util";

const execFileAsync = promisify(execFile);
const PLUGIN_ID = "agent-wallet";
const PLUGIN_ROOT = path.dirname(new URL(import.meta.url).pathname);
let selectedWalletBackend = null;
let selectedSolanaNetwork = null;
let selectedEvmNetwork = null;
let selectedBtcNetwork = null;
const PREVIEW_CACHE_TTL_MS = 15 * 60 * 1000;
const PRIVATE_SWAP_CACHE_TTL_MS = 35 * 60 * 1000;
const PREVIEW_BOUND_SWAP_TOOLS = new Set([
  "swap_solana_tokens",
  "swap_solana_privately",
  "flash_trade_open_position",
  "flash_trade_close_position",
]);
const PRIVATE_SWAP_APPROVAL_TOOL_NAME = "swap_solana_privately";
const approvalPreviewCache = new Map();
const privateSwapOrderCache = new Map();
const WALLET_TOOL_ONLY_GUIDANCE =
  "Use this wallet tool instead of shelling out to solana CLI, spl-token CLI, curl, or exec. If it fails, surface the wallet-tool error and stop rather than falling back to terminal commands.";
const APPROVAL_PREVIEW_TOOL_ALIASES = new Map([
  ["x402_pay_request", "x402_preview_request"],
]);

function canonicalJsonText(payload) {
  const normalize = (value) => {
    if (Array.isArray(value)) {
      return value.map(normalize);
    }
    if (value && typeof value === "object") {
      return Object.fromEntries(
        Object.keys(value)
          .sort()
          .map((key) => [key, normalize(value[key])])
      );
    }
    return value;
  };
  return JSON.stringify(normalize(payload));
}

function previewDigest(preview) {
  return crypto.createHash("sha256").update(canonicalJsonText(preview), "utf8").digest("hex");
}

function approvalCacheKey(userId, toolName) {
  return `${userId}::${toolName}`;
}

function approvalPreviewToolName(toolName) {
  const normalized = typeof toolName === "string" ? toolName.trim() : "";
  return APPROVAL_PREVIEW_TOOL_ALIASES.get(normalized) || normalized;
}

function pruneApprovalPreviewCache() {
  const now = Date.now();
  for (const [key, value] of approvalPreviewCache.entries()) {
    if (!value || typeof value !== "object" || Number(value.expiresAt || 0) <= now) {
      approvalPreviewCache.delete(key);
    }
  }
}

function cachePreviewForApproval(userId, toolName, payload) {
  const cacheToolName = approvalPreviewToolName(toolName);
  if (!payload || payload.ok !== true || !payload.data || typeof payload.data !== "object") return;
  const preview = payload.data;
  if (preview.mode !== "preview") return;
  if (!preview.confirmation_summary || typeof preview.confirmation_summary !== "object") return;
  pruneApprovalPreviewCache();
  const digest = previewDigest(preview);
  approvalPreviewCache.set(approvalCacheKey(userId, cacheToolName), {
    digest,
    expiresAt:
      cacheToolName === "swap_solana_privately"
        ? Date.now() + PRIVATE_SWAP_CACHE_TTL_MS
        : Date.now() + PREVIEW_CACHE_TTL_MS,
    preview,
    summary: preview.confirmation_summary,
  });
  if (cacheToolName === "swap_solana_privately") {
    privateSwapOrderCache.delete(approvalCacheKey(userId, cacheToolName));
  }
}

function latestCachedPreview(userId, toolName) {
  pruneApprovalPreviewCache();
  return approvalPreviewCache.get(approvalCacheKey(userId, approvalPreviewToolName(toolName))) || null;
}

function approvalTokenPreviewDigest(token) {
  if (typeof token !== "string" || !token.includes(".")) return "";
  try {
    const encoded = token.split(".", 1)[0];
    const payload = JSON.parse(Buffer.from(encoded, "base64url").toString("utf8"));
    const summary = payload?.binding?.summary;
    return summary && typeof summary._preview_digest === "string" ? summary._preview_digest : "";
  } catch {
    return "";
  }
}

function cachedPreviewForToken(userId, toolName, token) {
  const digest = approvalTokenPreviewDigest(token);
  if (!digest) return null;
  const cached = latestCachedPreview(userId, toolName);
  if (!cached || cached.digest !== digest) return null;
  return cached.preview && typeof cached.preview === "object" ? cached.preview : null;
}

function cachePendingPrivateSwapOrder(userId, toolName, preview, details) {
  if (toolName !== "swap_solana_privately") return;
  if (!preview || typeof preview !== "object") return;
  if (!details || typeof details !== "object") return;
  const houdiniId = typeof details.houdini_id === "string" ? details.houdini_id.trim() : "";
  const depositAddress =
    typeof details.deposit_address === "string" ? details.deposit_address.trim() : "";
  if (!houdiniId || !depositAddress) return;
  privateSwapOrderCache.set(approvalCacheKey(userId, toolName), {
    digest: previewDigest(preview),
    expiresAt: Date.now() + PRIVATE_SWAP_CACHE_TTL_MS,
    order: {
      multi_id: typeof details.multi_id === "string" ? details.multi_id.trim() : null,
      houdini_id: houdiniId,
      deposit_address: depositAddress,
      order: details.order && typeof details.order === "object" ? details.order : {},
    },
  });
}

function latestPendingPrivateSwapOrder(userId, toolName, preview) {
  if (toolName !== "swap_solana_privately") return null;
  const cached = privateSwapOrderCache.get(approvalCacheKey(userId, toolName));
  if (!cached || typeof cached !== "object") return null;
  if (Number(cached.expiresAt || 0) <= Date.now()) {
    privateSwapOrderCache.delete(approvalCacheKey(userId, toolName));
    return null;
  }
  if (!preview || typeof preview !== "object") return null;
  if (cached.digest !== previewDigest(preview)) return null;
  return cached.order && typeof cached.order === "object" ? cached.order : null;
}

function clearPendingPrivateSwapOrder(userId, toolName) {
  if (toolName !== "swap_solana_privately") return;
  privateSwapOrderCache.delete(approvalCacheKey(userId, toolName));
}

function formatPrivateSwapPendingOrderError(details) {
  const houdiniId = typeof details?.houdini_id === "string" ? details.houdini_id.trim() : "";
  const multiId = typeof details?.multi_id === "string" ? details.multi_id.trim() : "";
  const depositAddress =
    typeof details?.deposit_address === "string" ? details.deposit_address.trim() : "";
  const orderStatus =
    typeof details?.order_status === "string" ? details.order_status.trim() : "";
  const parts = [
    "Houdini order was created, but the Solana deposit account is not ready yet.",
  ];
  if (houdiniId) parts.push(`houdini_id=${houdiniId}`);
  if (multiId) parts.push(`multi_id=${multiId}`);
  if (depositAddress) parts.push(`deposit_address=${depositAddress}`);
  if (orderStatus) parts.push(`status=${orderStatus}`);
  parts.push("Retry execute for this existing order instead of generating a new preview.");
  return parts.join(" ");
}

function formatPrivateSwapRateLimitError(details) {
  const retryAfter =
    typeof details?.retry_after === "number"
      ? details.retry_after
      : typeof details?.retry_after === "string"
        ? details.retry_after
        : "";
  const quoteId = typeof details?.quote_id === "string" ? details.quote_id.trim() : "";
  const parts = [
    "Houdini exchange create is rate-limited right now.",
  ];
  if (retryAfter !== "") parts.push(`retry_after=${retryAfter}s`);
  if (quoteId) parts.push(`quote_id=${quoteId}`);
  parts.push("Do not generate a new preview yet; wait, then retry execute.");
  return parts.join(" ");
}

function listPendingPrivateSwapOrders(userId) {
  const key = approvalCacheKey(userId, PRIVATE_SWAP_APPROVAL_TOOL_NAME);
  const pending = privateSwapOrderCache.get(key);
  if (!pending || typeof pending !== "object" || Number(pending.expiresAt || 0) <= Date.now()) {
    privateSwapOrderCache.delete(key);
    return [];
  }
  return [
    {
      ...(pending.order && typeof pending.order === "object" ? pending.order : {}),
      expires_at_ms: Number(pending.expiresAt || 0),
    },
  ];
}

function resolvePluginConfig(api) {
  const globalConfig = api?.config ?? {};
  const pluginEntry = globalConfig?.plugins?.entries?.[PLUGIN_ID];
  return pluginEntry?.config ?? globalConfig?.config ?? {};
}

function resolveUserId(api, config) {
  return (
    config.userId ||
    process.env.OPENCLAW_AGENT_WALLET_USER_ID ||
    process.env.USER ||
    "openclaw-main"
  );
}

function resolveBackend(api) {
  const config = resolvePluginConfig(api);
  return normalizeWalletBackend(config.backend || process.env.AGENT_WALLET_BACKEND || "solana_local");
}

function normalizeWalletBackend(value) {
  const normalized = String(value || "").trim().toLowerCase();
  const aliases = {
    sol: "solana_local",
    solana: "solana_local",
    solana_local: "solana_local",
    "solana-local": "solana_local",
    evm: "wdk_evm_local",
    ethereum: "wdk_evm_local",
    eth: "wdk_evm_local",
    base: "wdk_evm_local",
    wdk_evm_local: "wdk_evm_local",
    "wdk-evm-local": "wdk_evm_local",
    evm_local: "wdk_evm_local",
    "evm-local": "wdk_evm_local",
    btc: "wdk_btc_local",
    bitcoin: "wdk_btc_local",
    wdk_btc_local: "wdk_btc_local",
    "wdk-btc-local": "wdk_btc_local",
    btc_local: "wdk_btc_local",
    "btc-local": "wdk_btc_local",
  };
  const backend = aliases[normalized] || normalized;
  if (!["solana_local", "wdk_evm_local", "wdk_btc_local"].includes(backend)) {
    throw new Error("Wallet backend must be solana, evm, base, ethereum, btc, or bitcoin.");
  }
  return backend;
}

function backendLabel(backend) {
  if (backend === "wdk_evm_local") return "evm";
  if (backend === "wdk_btc_local") return "bitcoin";
  return "solana";
}

function normalizeEvmNetwork(value) {
  const normalized = String(value || "").trim().toLowerCase();
  const aliases = {
    mainnet: "ethereum",
    eth: "ethereum",
    "eth-mainnet": "ethereum",
    "base-mainnet": "base",
    base_sepolia: "base-sepolia",
  };
  return aliases[normalized] || normalized;
}

function normalizeSelectableEvmNetwork(value) {
  const network = normalizeEvmNetwork(value);
  if (!["ethereum", "base"].includes(network)) {
    throw new Error("EVM network must be 'ethereum' or 'base'.");
  }
  return network;
}

function normalizeSolanaNetwork(value) {
  const network = String(value || "").trim().toLowerCase();
  if (!network) return null;
  const aliases = {
    solana: "mainnet",
    "solana-mainnet": "mainnet",
    mainnet_beta: "mainnet",
    "mainnet-beta": "mainnet",
  };
  const normalized = aliases[network] || network;
  if (!["mainnet", "devnet", "testnet"].includes(normalized)) {
    throw new Error("Solana network must be mainnet, devnet, or testnet.");
  }
  return normalized;
}

function normalizeBtcNetwork(value) {
  const network = String(value || "").trim().toLowerCase();
  if (!network) return null;
  const aliases = {
    btc: "bitcoin",
    bitcoin_mainnet: "bitcoin",
    "bitcoin-mainnet": "bitcoin",
    mainnet: "bitcoin",
  };
  const normalized = aliases[network] || network;
  if (!["bitcoin", "testnet", "regtest"].includes(normalized)) {
    throw new Error("Bitcoin network must be bitcoin, testnet, or regtest.");
  }
  return normalized;
}

function defaultSelectableEvmNetwork(api) {
  const config = resolvePluginConfig(api);
  const configured = normalizeEvmNetwork(config.network || process.env.WDK_EVM_NETWORK);
  return ["ethereum", "base"].includes(configured) ? configured : null;
}

function defaultSolanaNetwork(api) {
  const config = resolvePluginConfig(api);
  try {
    return normalizeSolanaNetwork(config.network || process.env.SOLANA_NETWORK) || "mainnet";
  } catch {
    return "mainnet";
  }
}

function defaultBtcNetwork(api) {
  const config = resolvePluginConfig(api);
  try {
    return normalizeBtcNetwork(config.network || process.env.WDK_BTC_NETWORK) || "bitcoin";
  } catch {
    return "bitcoin";
  }
}

function inferBackendForTool(toolName) {
  if (
    toolName.startsWith("get_evm_") ||
    toolName.startsWith("manage_evm_") ||
    toolName.startsWith("swap_evm_") ||
    toolName.startsWith("transfer_evm_") ||
    toolName === "set_evm_network"
  ) {
    return "wdk_evm_local";
  }
  if (toolName.startsWith("get_btc_") || toolName === "transfer_btc") {
    return "wdk_btc_local";
  }
  if (
    toolName.includes("solana") ||
    toolName.includes("jupiter") ||
    toolName.includes("kamino") ||
    toolName.includes("bags") ||
    toolName === "transfer_sol" ||
    toolName === "transfer_spl_token" ||
    toolName === "sign_wallet_message" ||
    toolName === "close_empty_token_accounts" ||
    toolName === "request_devnet_airdrop" ||
    toolName === "get_wallet_portfolio" ||
    toolName === "get_solana_token_prices"
  ) {
    return "solana_local";
  }
  return null;
}

function activeBackendForTool(api, toolName) {
  return selectedWalletBackend || inferBackendForTool(toolName) || resolveBackend(api);
}

function networkForBackend(api, backend) {
  const config = resolvePluginConfig(api);
  if (backend === "wdk_evm_local") {
    return selectedEvmNetwork || defaultSelectableEvmNetwork(api) || "ethereum";
  }
  if (backend === "wdk_btc_local") {
    try {
      return selectedBtcNetwork || defaultBtcNetwork(api);
    } catch {
      return "bitcoin";
    }
  }
  try {
    return (
      selectedSolanaNetwork ||
      normalizeSolanaNetwork(config.network || process.env.SOLANA_NETWORK) ||
      "mainnet"
    );
  } catch {
    return "mainnet";
  }
}

function effectiveConfigForBackend(api, backend) {
  const config = resolvePluginConfig(api);
  return {
    ...config,
    backend,
    network: networkForBackend(api, backend),
  };
}

function resolvePythonBin(config) {
  return config.pythonBin || process.env.OPENCLAW_AGENT_WALLET_PYTHON || "python3";
}

function resolveOpenclawHome(config) {
  return path.resolve(config.openclawHome || process.env.OPENCLAW_HOME || path.join(os.homedir(), ".openclaw"));
}

function resolvePackageRoot(config) {
  const openclawHome = resolveOpenclawHome(config);
  const candidates = [
    config.packageRoot,
    process.env.OPENCLAW_AGENT_WALLET_PACKAGE_ROOT,
    path.join(openclawHome, "agent-wallet-runtime/current/agent-wallet"),
    path.resolve(PLUGIN_ROOT, "../../../agent-wallet"),
    path.resolve(process.cwd(), "agent-wallet"),
  ].filter(Boolean);

  for (const candidate of candidates) {
    const resolved = path.resolve(candidate);
    if (fs.existsSync(path.join(resolved, "agent_wallet", "__init__.py"))) {
      return resolved;
    }
  }
  throw new Error(
    `Could not resolve agent-wallet package root. Checked ${path.join(openclawHome, "agent-wallet-runtime/current/agent-wallet")} and local workspace fallbacks. Set plugins.entries.agent-wallet.config.packageRoot if your runtime lives elsewhere.`
  );
}

function buildCliEnv(packageRoot) {
  const env = { ...process.env };
  env.PYTHONPATH = env.PYTHONPATH
    ? `${packageRoot}${path.delimiter}${env.PYTHONPATH}`
    : packageRoot;
  return env;
}

async function callWalletCli(api, command, extraArgs = [], configOverride = null) {
  const config = configOverride || resolvePluginConfig(api);
  const packageRoot = resolvePackageRoot(config);
  const pythonBin = resolvePythonBin(config);
  const userId = resolveUserId(api, config);
  const args = [
    "-m",
    "agent_wallet.openclaw_cli",
    command,
    "--user-id",
    userId,
    "--config-json",
    JSON.stringify(config),
    ...extraArgs,
  ];

  let stdout = "";
  let stderr = "";
  try {
    const result = await execFileAsync(pythonBin, args, {
      cwd: packageRoot,
      env: buildCliEnv(packageRoot),
      maxBuffer: 1024 * 1024 * 8,
    });
    stdout = result.stdout;
    stderr = result.stderr;
  } catch (error) {
    stdout = typeof error?.stdout === "string" ? error.stdout : "";
    stderr = typeof error?.stderr === "string" ? error.stderr : "";
    const stderrText = String(stderr || "").trim();
    if (stderrText) {
      try {
        const payload = JSON.parse(stderrText);
        const wrapped = new Error(payload?.error || "agent-wallet CLI failed");
        if (payload?.code) wrapped.code = payload.code;
        if (payload?.details && typeof payload.details === "object") {
          wrapped.details = payload.details;
        }
        throw wrapped;
      } catch (parseError) {
        if (parseError instanceof Error && parseError !== error) {
          throw parseError;
        }
      }
    }
    throw error;
  }

  if (stderr && stderr.trim()) {
    api?.logger?.debug?.(`[agent-wallet] stderr: ${stderr.trim()}`);
  }

  const payload = JSON.parse(stdout.trim() || "{}");
  if (payload?.ok === false && payload?.error) {
    const wrapped = new Error(payload.error);
    if (payload?.error_code) wrapped.code = payload.error_code;
    if (payload?.error_details && typeof payload.error_details === "object") {
      wrapped.details = payload.error_details;
    }
    throw wrapped;
  }
  return payload;
}

async function issueApprovalToken(api, config, userId, toolName, previewPayload) {
  const summary = previewPayload?.confirmation_summary;
  if (!summary || typeof summary !== "object") {
    throw new Error(`No confirmation_summary available for ${toolName}.`);
  }
  const digest = previewDigest(previewPayload);
  const summaryForToken = { ...summary, _preview_digest: digest };
  const extraArgs = [
    "--tool",
    toolName,
    "--summary-json",
    JSON.stringify(summaryForToken),
  ];
  if (previewPayload?.is_mainnet === true) {
    extraArgs.push("--mainnet-confirmed");
  }
  if (toolName === "swap_solana_privately") {
    extraArgs.push("--ttl-seconds", "1800");
  }
  const payload = await callWalletCli(api, "issue-approval", extraArgs, config);
  const token = String(payload?.approval_token || "").trim();
  if (!token) {
    throw new Error(`issue-approval did not return an approval_token for ${toolName}.`);
  }
  return token;
}

function asContent(data) {
  return {
    content: [
      {
        type: "text",
        text: JSON.stringify(data, null, 2),
      },
    ],
  };
}

function registerTool(api, definition) {
  api.registerTool({
    name: definition.name,
    description: definition.description,
    parameters: definition.parameters,
    returns: {
      type: "object",
      additionalProperties: true,
    },
    optional: Boolean(definition.optional),
    async execute(_id, params = {}) {
      if (definition.name === "get_active_wallet_backend") {
        const configuredBackend = resolveBackend(api);
        const activeBackend = selectedWalletBackend || configuredBackend;
        const activeNetwork = networkForBackend(api, activeBackend);
        return asContent({
          active_backend: activeBackend,
          active_wallet: backendLabel(activeBackend),
          active_network: activeNetwork,
          configured_backend: configuredBackend,
          configured_network: String(resolvePluginConfig(api).network || "").trim() || null,
          session_override_active: Boolean(selectedWalletBackend),
          available_wallets: ["solana", "evm", "bitcoin"],
          usage:
            "Use set_wallet_backend to switch between Solana, EVM, and Bitcoin for this OpenClaw plugin session. Do not edit plugin config for normal wallet switching.",
        });
      }

      if (definition.name === "set_wallet_backend") {
        const requestedWallet = String(params?.backend || params?.wallet || "").trim().toLowerCase();
        const backend = normalizeWalletBackend(requestedWallet);
        const impliedNetwork =
          ["base", "base-mainnet"].includes(requestedWallet)
            ? "base"
            : ["ethereum", "eth", "mainnet", "eth-mainnet"].includes(requestedWallet)
              ? "ethereum"
              : null;
        if (backend === "wdk_evm_local") {
          selectedEvmNetwork = normalizeSelectableEvmNetwork(
            params?.network || impliedNetwork || selectedEvmNetwork || defaultSelectableEvmNetwork(api) || "ethereum"
          );
        } else if (backend === "solana_local") {
          selectedSolanaNetwork = normalizeSolanaNetwork(
            params?.network || selectedSolanaNetwork || defaultSolanaNetwork(api)
          );
        } else if (backend === "wdk_btc_local") {
          selectedBtcNetwork = normalizeBtcNetwork(
            params?.network || selectedBtcNetwork || defaultBtcNetwork(api)
          );
        }
        const configOverride = effectiveConfigForBackend(api, backend);
        const payload = await callWalletCli(api, "invoke", [
          "--tool",
          backend === "wdk_evm_local" ? "get_evm_network" : "get_wallet_capabilities",
          "--arguments-json",
          JSON.stringify({}),
        ], configOverride);
        if (payload?.ok === false) {
          throw new Error(payload?.error || "set_wallet_backend failed");
        }
        selectedWalletBackend = backend;
        return asContent({
          selected_backend: backend,
          selected_wallet: backendLabel(backend),
          selected_network: networkForBackend(api, backend),
          configured_backend: resolveBackend(api),
          session_override_active: true,
          config_file_changed: false,
          usage:
            "Subsequent wallet calls in this OpenClaw plugin session use this wallet backend by default. The startup plugin config remains unchanged.",
          data: payload?.data ?? {},
        });
      }

      if (definition.name === "set_evm_network") {
        const network = normalizeSelectableEvmNetwork(params?.network);
        const configOverride = effectiveConfigForBackend(api, "wdk_evm_local");
        configOverride.network = network;
        const payload = await callWalletCli(api, "invoke", [
          "--tool",
          "get_evm_network",
          "--arguments-json",
          JSON.stringify({ network }),
        ], configOverride);
        if (payload?.ok === false) {
          throw new Error(payload?.error || "set_evm_network failed");
        }
        selectedWalletBackend = "wdk_evm_local";
        selectedEvmNetwork = network;
        return asContent({
          selected_backend: "wdk_evm_local",
          selected_wallet: "evm",
          selected_network: network,
          session_active_network: network,
          session_override_active: true,
          network_switch_persistent_for_runtime_session: true,
          usage:
            "Subsequent wallet calls in this OpenClaw plugin session use the EVM wallet on this network by default. You can still override a single EVM call with its network parameter.",
          data: payload?.data ?? {},
        });
      }

      if (definition.name === "list_pending_solana_private_swaps") {
        return asContent({
          orders: listPendingPrivateSwapOrders(resolveUserId(api, resolvePluginConfig(api))),
        });
      }

      const effectiveParams = { ...(params ?? {}) };
      const activeBackend = activeBackendForTool(api, definition.name);
      const userId = resolveUserId(api, resolvePluginConfig(api));
      if (
        activeBackend === "wdk_evm_local" &&
        selectedEvmNetwork &&
        definition.parameters?.properties?.network &&
        effectiveParams.network === undefined
      ) {
        effectiveParams.network = selectedEvmNetwork;
      }
      const configOverride = effectiveConfigForBackend(api, activeBackend);
      if (activeBackend === "wdk_evm_local" && effectiveParams.network !== undefined) {
        configOverride.network = normalizeSelectableEvmNetwork(effectiveParams.network);
      }
      if (String(effectiveParams.mode || "") === "execute") {
        if (
          PREVIEW_BOUND_SWAP_TOOLS.has(definition.name) &&
          typeof effectiveParams.approval_token === "string" &&
          effectiveParams.approval_token.trim() &&
          effectiveParams._approved_preview === undefined
        ) {
          const cachedPreview = cachedPreviewForToken(userId, definition.name, effectiveParams.approval_token);
          if (cachedPreview) {
            effectiveParams._approved_preview = cachedPreview;
          }
        }
        if (!effectiveParams.approval_token) {
          const cached = latestCachedPreview(userId, definition.name);
          if (cached?.preview && cached?.summary) {
            effectiveParams.approval_token = await issueApprovalToken(
              api,
              configOverride,
              userId,
              definition.name,
              cached.preview
            );
            if (PREVIEW_BOUND_SWAP_TOOLS.has(definition.name) && effectiveParams._approved_preview === undefined) {
              effectiveParams._approved_preview = cached.preview;
            }
          }
        }
      }
      if (definition.name === "continue_solana_private_swap") {
        const cached = latestCachedPreview(userId, PRIVATE_SWAP_APPROVAL_TOOL_NAME);
        if (cached?.preview && effectiveParams._approved_preview === undefined) {
          effectiveParams._approved_preview = cached.preview;
        }
        if (!effectiveParams.approval_token && cached?.preview && cached?.summary) {
          effectiveParams.approval_token = await issueApprovalToken(
            api,
            configOverride,
            userId,
            PRIVATE_SWAP_APPROVAL_TOOL_NAME,
            cached.preview
          );
        }
        if (effectiveParams._resume_private_swap_order === undefined && cached?.preview) {
          const pendingOrder = latestPendingPrivateSwapOrder(
            userId,
            PRIVATE_SWAP_APPROVAL_TOOL_NAME,
            cached.preview
          );
          if (pendingOrder) {
            if (
              effectiveParams.houdini_id &&
              pendingOrder.houdini_id &&
              String(effectiveParams.houdini_id).trim() !== String(pendingOrder.houdini_id).trim()
            ) {
              throw new Error("The requested houdini_id does not match the cached pending private swap order.");
            }
            effectiveParams._resume_private_swap_order = pendingOrder;
          }
        }
      }
      const executeWalletTool = async () =>
        callWalletCli(api, "invoke", [
          "--tool",
          definition.name,
          "--arguments-json",
          JSON.stringify(effectiveParams),
        ], configOverride);

      let payload;
      if (definition.name === "swap_solana_privately" && String(effectiveParams.mode || "") === "execute") {
        const approvedPreview =
          effectiveParams._approved_preview && typeof effectiveParams._approved_preview === "object"
            ? effectiveParams._approved_preview
            : null;
        const pendingOrder = approvedPreview
          ? latestPendingPrivateSwapOrder(userId, definition.name, approvedPreview)
          : null;
        if (pendingOrder && effectiveParams._resume_private_swap_order === undefined) {
          effectiveParams._resume_private_swap_order = pendingOrder;
        }

        let remainingRetries = 3;
        while (true) {
          try {
            payload = await executeWalletTool();
            const executionState = payload?.data?.execution_state;
            if (executionState === "awaiting_deposit_funding" && approvedPreview) {
              cachePendingPrivateSwapOrder(userId, definition.name, approvedPreview, payload.data);
            } else {
              clearPendingPrivateSwapOrder(userId, definition.name);
            }
            break;
          } catch (error) {
            const errorCode = typeof error?.code === "string" ? error.code : "";
            const errorDetails =
              error?.details && typeof error.details === "object" ? error.details : null;
            if (
              (errorCode === "houdini_deposit_not_ready" ||
                errorCode === "houdini_order_initializing_timeout") &&
              approvedPreview &&
              errorDetails &&
              remainingRetries > 0
            ) {
              cachePendingPrivateSwapOrder(userId, definition.name, approvedPreview, errorDetails);
              effectiveParams._resume_private_swap_order =
                latestPendingPrivateSwapOrder(userId, definition.name, approvedPreview) || undefined;
              remainingRetries -= 1;
              continue;
            }
            if (
              (errorCode === "houdini_deposit_not_ready" ||
                errorCode === "houdini_order_initializing_timeout") &&
              errorDetails
            ) {
              cachePendingPrivateSwapOrder(userId, definition.name, approvedPreview, errorDetails);
              throw new Error(formatPrivateSwapPendingOrderError(errorDetails));
            }
            if (errorCode === "houdini_exchange_rate_limited" && errorDetails) {
              throw new Error(formatPrivateSwapRateLimitError(errorDetails));
            }
            throw error;
          }
        }
      } else if (definition.name === "continue_solana_private_swap") {
        payload = await executeWalletTool();
        if (payload?.data?.execution_state === "funding_submitted") {
          clearPendingPrivateSwapOrder(userId, PRIVATE_SWAP_APPROVAL_TOOL_NAME);
        }
      } else {
        payload = await executeWalletTool();
      }
      cachePreviewForApproval(userId, definition.name, payload);
      if (payload?.ok === false) {
        throw new Error(payload?.error || `${definition.name} failed`);
      }
      return asContent(payload?.data ?? {});
    },
  });
}

const walletSessionToolDefinitions = [
  {
    name: "get_wallet_capabilities",
    description: "Describe the active wallet backend, chain, network, address, and safety limits. Use set_wallet_backend to switch between Solana, EVM, and Bitcoin instead of editing plugin config.",
    parameters: { type: "object", properties: {}, additionalProperties: false },
  },
  {
    name: "get_wallet_address",
    description: "Return the active wallet address for the current session-selected backend.",
    parameters: { type: "object", properties: {}, additionalProperties: false },
  },
  {
    name: "get_wallet_balance",
    description: `Get the active wallet overview. Solana and EVM return native assets, discovered token balances, per-asset USD values when available, and total_value_usd. Use set_wallet_backend first when the user asks to switch wallets. ${WALLET_TOOL_ONLY_GUIDANCE}`,
    parameters: {
      type: "object",
      properties: {
        address: {
          type: "string",
          description: "Optional wallet address override.",
        },
      },
      additionalProperties: false,
    },
  },
  {
    name: "x402_search_services",
    description:
      "Search x402-paid services through CDP Bazaar or Agentic Market. This is read-only discovery and does not spend funds.",
    parameters: {
      type: "object",
      properties: {
        query: { type: "string" },
        discovery_provider: {
          type: "string",
          enum: ["auto", "cdp_bazaar", "agentic_market"],
        },
        network: { type: "string" },
        asset: { type: "string" },
        scheme: { type: "string" },
        max_usd_price: { type: "string" },
        limit: { type: "integer" },
      },
      additionalProperties: false,
    },
  },
  {
    name: "x402_get_service_details",
    description:
      "Resolve one x402 service or resource into a normalized details payload. Use a resource URL for CDP Bazaar or a domain/service id for Agentic Market.",
    parameters: {
      type: "object",
      properties: {
        reference: { type: "string" },
        discovery_provider: {
          type: "string",
          enum: ["auto", "cdp_bazaar", "agentic_market"],
        },
      },
      required: ["reference"],
      additionalProperties: false,
    },
  },
  {
    name: "x402_preview_request",
    description:
      "Make an unpaid HTTP request to an x402 endpoint, detect HTTP 402, parse PAYMENT-REQUIRED, and summarize the payment options. This does not pay or execute.",
    parameters: {
      type: "object",
      properties: {
        url: { type: "string" },
        method: { type: "string" },
        headers: { type: "object", additionalProperties: { type: "string" } },
        query: { type: "object", additionalProperties: true },
        json_body: {},
        text_body: { type: "string" },
      },
      required: ["url"],
      additionalProperties: false,
    },
  },
  {
    name: "x402_pay_request",
    description:
      "Prepare or execute an x402 paid request using the active wallet backend. This milestone executes the Solana exact buyer flow and keeps EVM as prepare-only.",
    parameters: {
      type: "object",
      properties: {
        url: { type: "string" },
        method: { type: "string" },
        headers: { type: "object", additionalProperties: { type: "string" } },
        query: { type: "object", additionalProperties: true },
        json_body: {},
        text_body: { type: "string" },
        mode: {
          type: "string",
          enum: ["prepare", "execute"],
          description: "prepare validates the payment plan; execute sends the paid retry.",
        },
        purpose: { type: "string" },
        user_intent: {
          type: "boolean",
          description: "Must be true for prepare mode.",
        },
        approval_token: {
          type: "string",
          description: "Required for execute mode and must be issued against the exact x402 payment summary.",
        },
      },
      required: ["url", "mode", "purpose"],
      additionalProperties: false,
    },
  },
  {
    name: "get_active_wallet_backend",
    description: "Show which wallet backend is active in this OpenClaw plugin session and whether it differs from the startup plugin config.",
    parameters: { type: "object", properties: {}, additionalProperties: false },
  },
  {
    name: "set_wallet_backend",
    description:
      "Switch the active wallet backend for this OpenClaw plugin session. Use this for user requests like 'switch to EVM wallet', 'use Base', 'switch back to Solana', or 'use Bitcoin'. This does not edit code, environment variables, or plugin config.",
    parameters: {
      type: "object",
      properties: {
        backend: {
          type: "string",
          enum: ["solana", "sol", "evm", "ethereum", "base", "bitcoin", "btc"],
          description: "Wallet backend or common alias to make active.",
        },
        network: {
          type: "string",
          description: "Optional network for the selected wallet. Examples: mainnet, devnet, ethereum, base, bitcoin, testnet.",
        },
      },
      required: ["backend"],
      additionalProperties: false,
    },
  },
];

const solanaToolDefinitions = [
  {
    name: "list_pending_solana_private_swaps",
    description:
      "List cached pending Houdini private Solana orders from this OpenClaw session, including houdini_id, multi_id, deposit_address, and the last known order payload.",
    parameters: { type: "object", properties: {}, additionalProperties: false },
  },
  {
    name: "get_wallet_capabilities",
    description: "Describe the connected wallet backend, chain, and safety limits.",
    parameters: { type: "object", properties: {}, additionalProperties: false },
  },
  {
    name: "get_wallet_address",
    description: "Return the configured wallet address for the connected backend.",
    parameters: { type: "object", properties: {}, additionalProperties: false },
  },
  {
    name: "get_wallet_balance",
    description: `Get the wallet overview: native balance, discovered token balances, per-asset USD values when available, and total_value_usd. Solana token discovery uses RPC; pricing uses Jupiter rather than RPC. ${WALLET_TOOL_ONLY_GUIDANCE}`,
    parameters: {
      type: "object",
      properties: {
        address: {
          type: "string",
          description: "Optional wallet address override.",
        },
      },
      additionalProperties: false,
    },
  },
  {
    name: "get_lifi_supported_chains",
    description: "List the LI.FI chains currently allowed for OpenClaw cross-chain routing.",
    parameters: { type: "object", properties: {}, additionalProperties: false },
  },
  {
    name: "get_lifi_quote",
    description: "Get a read-only LI.FI cross-chain quote for Ethereum/Base/Solana routes. Execution is not enabled by this tool.",
    parameters: {
      type: "object",
      properties: {
        from_chain: { type: "string", description: "Source chain: ethereum, base, solana, or the LI.FI chain id." },
        to_chain: { type: "string", description: "Destination chain: ethereum, base, solana, or the LI.FI chain id." },
        from_token: { type: "string", description: "Source token address. Use native/eth/sol for native tokens." },
        to_token: { type: "string", description: "Destination token address. Use native/eth/sol for native tokens." },
        amount_in_raw: { type: "string", description: "Input amount in token base units as a base-10 integer string." },
        from_address: { type: "string", description: "Optional source wallet address. Defaults to the active wallet when the source chain matches it." },
        to_address: { type: "string", description: "Optional destination wallet address. Defaults to the active wallet when the destination chain matches it." },
        slippage: { type: "number", description: "Optional decimal fraction, for example 0.01 for 1%." },
        allow_bridges: { type: "array", items: { type: "string" } },
        deny_bridges: { type: "array", items: { type: "string" } },
        prefer_bridges: { type: "array", items: { type: "string" } },
      },
      required: ["from_chain", "to_chain", "from_token", "to_token", "amount_in_raw"],
      additionalProperties: false,
    },
  },
  {
    name: "get_lifi_transfer_status",
    description: "Get LI.FI cross-chain transfer status using a source/destination transaction hash or LI.FI step id.",
    parameters: {
      type: "object",
      properties: {
        tx_hash: { type: "string" },
        bridge: { type: "string" },
        from_chain: { type: "string" },
        to_chain: { type: "string" },
      },
      required: ["tx_hash"],
      additionalProperties: false,
    },
  },
  {
    name: "get_wallet_portfolio",
    description: `Get the Solana wallet portfolio. This is the detailed equivalent of get_wallet_balance and includes native SOL, non-zero SPL token accounts, USD pricing when available, and total_value_usd. ${WALLET_TOOL_ONLY_GUIDANCE}`,
    parameters: {
      type: "object",
      properties: {
        address: {
          type: "string",
          description: "Optional wallet address override.",
        },
      },
      additionalProperties: false,
    },
  },
  {
    name: "get_solana_token_prices",
    description: "Get current token prices for one or more Solana mint addresses via Jupiter.",
    parameters: {
      type: "object",
      properties: {
        mints: {
          type: "array",
          items: { type: "string" },
          description: "List of Solana token mint addresses.",
        },
      },
      required: ["mints"],
      additionalProperties: false,
    },
  },
  {
    name: "get_bags_claimable_positions",
    description: "Get claimable Bags fee-share positions for a Solana wallet on mainnet.",
    parameters: {
      type: "object",
      properties: {
        wallet: {
          type: "string",
          description: "Optional wallet address override.",
        },
      },
      additionalProperties: false,
    },
  },
  {
    name: "get_bags_fee_analytics",
    description: "Get Bags fee analytics for a launched token, with optional claim event history.",
    parameters: {
      type: "object",
      properties: {
        token_mint: {
          type: "string",
          description: "Launched token mint address.",
        },
        include_claim_events: {
          type: "boolean",
          description: "If true, also fetch claim event history.",
        },
        mode: {
          type: "string",
          enum: ["offset", "time"],
        },
        limit: { type: "integer" },
        offset: { type: "integer" },
        from_ts: { type: "integer" },
        to_ts: { type: "integer" },
      },
      required: ["token_mint"],
      additionalProperties: false,
    },
  },
  {
    name: "get_jupiter_earn_tokens",
    description: "List Jupiter Earn vault tokens currently supported on Solana mainnet.",
    parameters: { type: "object", properties: {}, additionalProperties: false },
  },
  {
    name: "get_jupiter_earn_positions",
    description: "Get Jupiter Earn positions for one or more Solana wallet addresses on mainnet.",
    parameters: {
      type: "object",
      properties: {
        users: {
          type: "array",
          items: { type: "string" },
          description: "Optional list of Solana wallet addresses. If omitted, use the configured wallet address.",
        },
      },
      additionalProperties: false,
    },
  },
  {
    name: "get_jupiter_earn_earnings",
    description: "Get Jupiter Earn earnings for a wallet and one or more position addresses on mainnet.",
    parameters: {
      type: "object",
      properties: {
        user: {
          type: "string",
          description: "Optional Solana wallet address override.",
        },
        positions: {
          type: "array",
          items: { type: "string" },
          description: "List of Jupiter Earn position addresses.",
        },
      },
      required: ["positions"],
      additionalProperties: false,
    },
  },
  {
    name: "get_flash_trade_markets",
    description: "List Flash Trade perpetual markets currently available on Solana mainnet.",
    parameters: {
      type: "object",
      properties: {
        pool_name: {
          type: "string",
          description: "Optional Flash pool identifier such as Crypto.1.",
        },
      },
      additionalProperties: false,
    },
  },
  {
    name: "get_flash_trade_positions",
    description: "Get Flash Trade perpetual positions for a Solana wallet on mainnet.",
    parameters: {
      type: "object",
      properties: {
        owner: {
          type: "string",
          description: "Optional Solana wallet address override. If omitted, use the configured wallet.",
        },
        pool_name: {
          type: "string",
          description: "Optional Flash pool identifier such as Crypto.1.",
        },
      },
      additionalProperties: false,
    },
  },
  {
    name: "get_kamino_lend_markets",
    description: "List Kamino lending markets currently available on Solana mainnet.",
    parameters: { type: "object", properties: {}, additionalProperties: false },
  },
  {
    name: "get_kamino_lend_market_reserves",
    description: "Get reserve metrics for one Kamino lending market on Solana mainnet.",
    parameters: {
      type: "object",
      properties: {
        market: {
          type: "string",
          description: "Kamino market address.",
        },
      },
      required: ["market"],
      additionalProperties: false,
    },
  },
  {
    name: "get_kamino_lend_user_obligations",
    description: "Get Kamino obligations for a wallet in a specific Kamino market on Solana mainnet.",
    parameters: {
      type: "object",
      properties: {
        market: {
          type: "string",
          description: "Kamino market address.",
        },
        user: {
          type: "string",
          description: "Optional Solana wallet address override.",
        },
      },
      required: ["market"],
      additionalProperties: false,
    },
  },
  {
    name: "get_kamino_lend_user_rewards",
    description: "Get Kamino rewards summary for a Solana wallet on mainnet.",
    parameters: {
      type: "object",
      properties: {
        user: {
          type: "string",
          description: "Optional Solana wallet address override.",
        },
      },
      additionalProperties: false,
    },
  },
  {
    name: "sign_wallet_message",
    description: "Sign an arbitrary message with the connected wallet after explicit approval.",
    optional: true,
    parameters: {
      type: "object",
      properties: {
        message: { type: "string" },
        purpose: { type: "string" },
        user_confirmed: { type: "boolean" },
      },
      required: ["message", "purpose", "user_confirmed"],
      additionalProperties: false,
    },
  },
  {
    name: "transfer_sol",
    description: "Preview, prepare, or execute a native SOL transfer. Prepare returns an execution plan only, and execute requires a host-issued approval token bound to the previewed operation.",
    optional: true,
    parameters: {
      type: "object",
      properties: {
        recipient: { type: "string" },
        amount: { type: "number" },
        mode: { type: "string", enum: ["preview", "prepare", "execute"] },
        purpose: { type: "string" },
        user_intent: { type: "boolean" },
        approval_token: { type: "string" },
      },
      required: ["recipient", "amount", "mode", "purpose"],
      additionalProperties: false,
    },
  },
  {
    name: "transfer_spl_token",
    description: "Preview, prepare, or execute an SPL token transfer by mint address. Prepare returns an execution plan only, and execute requires a host-issued approval token bound to the previewed operation.",
    optional: true,
    parameters: {
      type: "object",
      properties: {
        recipient: { type: "string" },
        mint: { type: "string" },
        amount: { type: "number" },
        decimals: { type: "integer" },
        mode: { type: "string", enum: ["preview", "prepare", "execute"] },
        purpose: { type: "string" },
        user_intent: { type: "boolean" },
        approval_token: { type: "string" },
      },
      required: ["recipient", "mint", "amount", "mode", "purpose"],
      additionalProperties: false,
    },
  },
  {
    name: "swap_solana_tokens",
    description: `Preview, prepare, or execute a Solana token swap via Jupiter. Prepare returns an execution plan only, and execute requires a host-issued approval token bound to the previewed operation. ${WALLET_TOOL_ONLY_GUIDANCE}`,
    optional: true,
    parameters: {
      type: "object",
      properties: {
        input_mint: { type: "string" },
        output_mint: { type: "string" },
        amount: { type: "number" },
        slippage_bps: { type: "integer" },
        mode: { type: "string", enum: ["preview", "prepare", "execute"] },
        purpose: { type: "string" },
        user_intent: { type: "boolean" },
        approval_token: { type: "string" },
      },
      required: ["input_mint", "output_mint", "amount", "mode", "purpose"],
      additionalProperties: false,
    },
  },
  {
    name: "swap_solana_privately",
    description: `Preview or create a Solana private payout through Houdini's anonymous routing. The initial implementation supports same-token private payouts only, such as SOL->SOL or USDC->USDC. Use preview first, then execute after explicit approval. The first execute creates the Houdini order and returns its deposit address; use continue_solana_private_swap to submit the funding transfer. ${WALLET_TOOL_ONLY_GUIDANCE}`,
    optional: true,
    parameters: {
      type: "object",
      properties: {
        input_token: { type: "string" },
        output_token: { type: "string" },
        destination_address: { type: "string" },
        amount: { type: "number" },
        use_xmr: { type: "boolean" },
        mode: { type: "string", enum: ["preview", "execute"] },
        purpose: { type: "string" },
        user_intent: { type: "boolean" },
        approval_token: { type: "string" },
      },
      required: ["input_token", "output_token", "destination_address", "amount", "mode", "purpose"],
      additionalProperties: false,
    },
  },
  {
    name: "continue_solana_private_swap",
    description:
      "Continue a previously created Houdini private Solana payout and submit the funding transfer to the cached deposit address. Use this after swap_solana_privately execute has returned a pending order.",
    optional: true,
    parameters: {
      type: "object",
      properties: {
        houdini_id: { type: "string" },
        approval_token: { type: "string" },
      },
      required: ["approval_token"],
      additionalProperties: false,
    },
  },
  {
    name: "get_solana_private_swap_status",
    description: "Check Houdini status for a Solana private payout created by swap_solana_privately. Prefer houdini_id from the execute result; multi_id is only needed for legacy multi-order flows.",
    optional: true,
    parameters: {
      type: "object",
      properties: {
        multi_id: { type: "string" },
        houdini_id: { type: "string" },
      },
      anyOf: [{ required: ["multi_id"] }, { required: ["houdini_id"] }],
      additionalProperties: false,
    },
  },
  {
    name: "swap_solana_lifi_cross_chain_tokens",
    description: "Preview, prepare, or execute a Solana-origin cross-chain swap through LI.FI. This currently supports Solana as the source chain and ethereum/base as the destination chain. Prepare returns an execution plan only, and execute requires a host-issued approval token bound to the previewed operation.",
    optional: true,
    parameters: {
      type: "object",
      properties: {
        input_token: { type: "string" },
        destination_chain: { type: "string", enum: ["ethereum", "base", "1", "8453"] },
        output_token: { type: "string" },
        destination_address: { type: "string" },
        amount_in_raw: { type: "string" },
        slippage: { type: "number" },
        allow_bridges: { type: "array", items: { type: "string" } },
        deny_bridges: { type: "array", items: { type: "string" } },
        prefer_bridges: { type: "array", items: { type: "string" } },
        mode: { type: "string", enum: ["preview", "prepare", "execute"] },
        purpose: { type: "string" },
        user_intent: { type: "boolean" },
        approval_token: { type: "string" },
      },
      required: [
        "input_token",
        "destination_chain",
        "output_token",
        "destination_address",
        "amount_in_raw",
        "mode",
        "purpose",
      ],
      additionalProperties: false,
    },
  },
  {
    name: "claim_bags_fees",
    description: "Preview, prepare, or execute a Bags fee-share claim for the connected wallet on mainnet. Prepare returns an execution plan only, and execute requires a host-issued approval token bound to the previewed operation.",
    optional: true,
    parameters: {
      type: "object",
      properties: {
        token_mint: { type: "string" },
        mode: { type: "string", enum: ["preview", "prepare", "execute"] },
        purpose: { type: "string" },
        user_intent: { type: "boolean" },
        approval_token: { type: "string" },
      },
      required: ["token_mint", "mode", "purpose"],
      additionalProperties: false,
    },
  },
  {
    name: "launch_bags_token",
    description: "Preview, prepare, or execute a Bags token launch with fee-share config on mainnet. Prepare returns an execution plan only, and execute requires a host-issued approval token bound to the previewed operation.",
    optional: true,
    parameters: {
      type: "object",
      properties: {
        name: { type: "string" },
        symbol: { type: "string" },
        description: { type: "string" },
        image_url: { type: "string" },
        website: { type: "string" },
        twitter: { type: "string" },
        telegram: { type: "string" },
        discord: { type: "string" },
        base_mint: { type: "string" },
        claimers: {
          type: "array",
          items: { type: "string" },
        },
        basis_points: {
          type: "array",
          items: { type: "integer" },
        },
        initial_buy_sol: { type: "number" },
        bags_config_type: { type: "integer" },
        mode: { type: "string", enum: ["preview", "prepare", "execute"] },
        purpose: { type: "string" },
        user_intent: { type: "boolean" },
        approval_token: { type: "string" },
      },
      required: [
        "name",
        "symbol",
        "description",
        "base_mint",
        "claimers",
        "basis_points",
        "initial_buy_sol",
        "mode",
        "purpose",
      ],
      additionalProperties: false,
    },
  },
  {
    name: "jupiter_earn_deposit",
    description: "Preview, prepare, or execute a Jupiter Earn deposit using a raw base-unit amount. Prepare returns an execution plan only, and execute requires a host-issued approval token bound to the previewed operation.",
    optional: true,
    parameters: {
      type: "object",
      properties: {
        asset: { type: "string" },
        amount_raw: { type: "string" },
        mode: { type: "string", enum: ["preview", "prepare", "execute"] },
        purpose: { type: "string" },
        user_intent: { type: "boolean" },
        approval_token: { type: "string" },
      },
      required: ["asset", "amount_raw", "mode", "purpose"],
      additionalProperties: false,
    },
  },
  {
    name: "jupiter_earn_withdraw",
    description: "Preview, prepare, or execute a Jupiter Earn withdraw using a raw base-unit amount. Prepare returns an execution plan only, and execute requires a host-issued approval token bound to the previewed operation.",
    optional: true,
    parameters: {
      type: "object",
      properties: {
        asset: { type: "string" },
        amount_raw: { type: "string" },
        mode: { type: "string", enum: ["preview", "prepare", "execute"] },
        purpose: { type: "string" },
        user_intent: { type: "boolean" },
        approval_token: { type: "string" },
      },
      required: ["asset", "amount_raw", "mode", "purpose"],
      additionalProperties: false,
    },
  },
  {
    name: "kamino_lend_deposit",
    description: "Preview, prepare, or execute a Kamino lending deposit using a decimal token amount. Prepare returns an execution plan only, and execute requires a host-issued approval token bound to the previewed operation.",
    optional: true,
    parameters: {
      type: "object",
      properties: {
        market: { type: "string" },
        reserve: { type: "string" },
        amount_ui: { type: "string" },
        mode: { type: "string", enum: ["preview", "prepare", "execute"] },
        purpose: { type: "string" },
        user_intent: { type: "boolean" },
        approval_token: { type: "string" },
      },
      required: ["market", "reserve", "amount_ui", "mode", "purpose"],
      additionalProperties: false,
    },
  },
  {
    name: "kamino_lend_withdraw",
    description: "Preview, prepare, or execute a Kamino lending withdraw using a decimal token amount. Prepare returns an execution plan only, and execute requires a host-issued approval token bound to the previewed operation.",
    optional: true,
    parameters: {
      type: "object",
      properties: {
        market: { type: "string" },
        reserve: { type: "string" },
        amount_ui: { type: "string" },
        mode: { type: "string", enum: ["preview", "prepare", "execute"] },
        purpose: { type: "string" },
        user_intent: { type: "boolean" },
        approval_token: { type: "string" },
      },
      required: ["market", "reserve", "amount_ui", "mode", "purpose"],
      additionalProperties: false,
    },
  },
  {
    name: "kamino_lend_borrow",
    description: "Preview, prepare, or execute a Kamino lending borrow using a decimal token amount. Prepare returns an execution plan only, and execute requires a host-issued approval token bound to the previewed operation.",
    optional: true,
    parameters: {
      type: "object",
      properties: {
        market: { type: "string" },
        reserve: { type: "string" },
        amount_ui: { type: "string" },
        mode: { type: "string", enum: ["preview", "prepare", "execute"] },
        purpose: { type: "string" },
        user_intent: { type: "boolean" },
        approval_token: { type: "string" },
      },
      required: ["market", "reserve", "amount_ui", "mode", "purpose"],
      additionalProperties: false,
    },
  },
  {
    name: "kamino_lend_repay",
    description: "Preview, prepare, or execute a Kamino lending repay using a decimal token amount. Prepare returns an execution plan only, and execute requires a host-issued approval token bound to the previewed operation.",
    optional: true,
    parameters: {
      type: "object",
      properties: {
        market: { type: "string" },
        reserve: { type: "string" },
        amount_ui: { type: "string" },
        mode: { type: "string", enum: ["preview", "prepare", "execute"] },
        purpose: { type: "string" },
        user_intent: { type: "boolean" },
        approval_token: { type: "string" },
      },
      required: ["market", "reserve", "amount_ui", "mode", "purpose"],
      additionalProperties: false,
    },
  },
  {
    name: "flash_trade_open_position",
    description: "Preview, prepare, or execute a Flash Trade perpetual open on Solana mainnet using a supported Flash collateral.",
    optional: true,
    parameters: {
      type: "object",
      properties: {
        pool_name: {
          type: "string",
          description: "Flash pool identifier such as Crypto.1.",
        },
        market_symbol: {
          type: "string",
          description: "Flash market symbol such as SOL or BTC.",
        },
        collateral_symbol: {
          type: "string",
          description: "Flash collateral symbol, for example SOL for SOL longs or USDC for SOL shorts.",
        },
        collateral_amount_raw: {
          type: "string",
          description: "Collateral amount in raw token units.",
        },
        leverage: {
          type: "string",
          description: "Requested leverage as a decimal string such as 5 or 7.5.",
        },
        side: {
          type: "string",
          enum: ["long", "short"],
          description: "Position direction.",
        },
        mode: { type: "string", enum: ["preview", "prepare", "execute"] },
        purpose: { type: "string" },
        user_intent: { type: "boolean" },
        approval_token: { type: "string" },
      },
      required: [
        "pool_name",
        "market_symbol",
        "collateral_symbol",
        "collateral_amount_raw",
        "leverage",
        "side",
        "mode",
        "purpose",
      ],
      additionalProperties: false,
    },
  },
  {
    name: "flash_trade_close_position",
    description: "Preview, prepare, or execute a Flash Trade perpetual close on Solana mainnet.",
    optional: true,
    parameters: {
      type: "object",
      properties: {
        pool_name: {
          type: "string",
          description: "Flash pool identifier such as Crypto.1.",
        },
        market_symbol: {
          type: "string",
          description: "Flash market symbol such as SOL or BTC.",
        },
        side: {
          type: "string",
          enum: ["long", "short"],
          description: "Position direction to close.",
        },
        mode: { type: "string", enum: ["preview", "prepare", "execute"] },
        purpose: { type: "string" },
        user_intent: { type: "boolean" },
        approval_token: { type: "string" },
      },
      required: ["pool_name", "market_symbol", "side", "mode", "purpose"],
      additionalProperties: false,
    },
  },
  {
    name: "close_empty_token_accounts",
    description: "Preview or execute closing zero-balance token accounts. Execute requires a host-issued approval token bound to the previewed operation.",
    optional: true,
    parameters: {
      type: "object",
      properties: {
        limit: { type: "integer" },
        mode: { type: "string", enum: ["preview", "execute"] },
        purpose: { type: "string" },
        approval_token: { type: "string" },
      },
      required: ["limit", "mode", "purpose"],
      additionalProperties: false,
    },
  },
  {
    name: "request_devnet_airdrop",
    description: "Request devnet or testnet SOL from the faucet.",
    optional: true,
    parameters: {
      type: "object",
      properties: {
        amount: { type: "number" },
      },
      required: ["amount"],
      additionalProperties: false,
    },
  },
];

const btcToolDefinitions = [
  {
    name: "get_wallet_capabilities",
    description: "Describe the connected wallet backend, chain, and safety limits.",
    parameters: { type: "object", properties: {}, additionalProperties: false },
  },
  {
    name: "get_wallet_address",
    description: "Return the configured wallet address for the connected backend.",
    parameters: { type: "object", properties: {}, additionalProperties: false },
  },
  {
    name: "get_wallet_balance",
    description: "Get the native BTC balance for the configured wallet address.",
    parameters: {
      type: "object",
      properties: {
        address: {
          type: "string",
          description: "Optional wallet address override.",
        },
      },
      additionalProperties: false,
    },
  },
  {
    name: "get_btc_transfer_history",
    description: "Get BTC transfer history for the configured wallet account.",
    parameters: {
      type: "object",
      properties: {
        direction: { type: "string", enum: ["incoming", "outgoing", "all"] },
        limit: { type: "integer" },
        skip: { type: "integer" },
      },
      additionalProperties: false,
    },
  },
  {
    name: "get_btc_fee_rates",
    description: "Get current BTC fee-rate suggestions from the local BTC wallet service.",
    parameters: { type: "object", properties: {}, additionalProperties: false },
  },
  {
    name: "get_btc_max_spendable",
    description: "Estimate the maximum BTC spendable amount after fees.",
    parameters: {
      type: "object",
      properties: {
        fee_rate: { type: "integer" },
      },
      additionalProperties: false,
    },
  },
  {
    name: "transfer_btc",
    description: "Preview, prepare, or execute a BTC transfer in satoshis. Prepare returns an execution plan only, and execute requires a host-issued approval token bound to the previewed operation.",
    optional: true,
    parameters: {
      type: "object",
      properties: {
        recipient: { type: "string" },
        amount_sats: { type: "integer" },
        fee_rate: { type: "integer" },
        confirmation_target: { type: "integer" },
        mode: { type: "string", enum: ["preview", "prepare", "execute"] },
        purpose: { type: "string" },
        user_intent: { type: "boolean" },
        approval_token: { type: "string" },
      },
      required: ["recipient", "amount_sats", "mode", "purpose"],
      additionalProperties: false,
    },
  },
];

const evmToolDefinitions = [
  {
    name: "get_wallet_capabilities",
    description: "Describe the connected wallet backend, chain, and safety limits.",
    parameters: {
      type: "object",
      properties: {
        network: {
          type: "string",
          enum: ["ethereum", "base"],
          description: "Optional EVM network override for this request.",
        },
      },
      additionalProperties: false,
    },
  },
  {
    name: "get_wallet_address",
    description: "Return the configured wallet address for the connected backend.",
    parameters: {
      type: "object",
      properties: {
        network: {
          type: "string",
          enum: ["ethereum", "base"],
          description: "Optional EVM network override for this request.",
        },
      },
      additionalProperties: false,
    },
  },
  {
    name: "get_wallet_balance",
    description: "Get the EVM wallet overview: native asset, discovered ERC-20 balances, per-asset USD values, assets, balance_usd, and total_value_usd when available. Pricing uses aggregator APIs rather than RPC.",
    parameters: {
      type: "object",
      properties: {
        address: {
          type: "string",
          description: "Optional wallet address override.",
        },
        network: {
          type: "string",
          enum: ["ethereum", "base"],
          description: "Optional EVM network override for this request.",
        },
      },
      additionalProperties: false,
    },
  },
  {
    name: "get_lifi_supported_chains",
    description: "List the LI.FI chains currently allowed for OpenClaw cross-chain routing.",
    parameters: { type: "object", properties: {}, additionalProperties: false },
  },
  {
    name: "get_lifi_quote",
    description: "Get a read-only LI.FI cross-chain quote for Ethereum/Base/Solana routes. Execution is not enabled by this tool.",
    parameters: {
      type: "object",
      properties: {
        from_chain: { type: "string", description: "Source chain: ethereum, base, solana, or the LI.FI chain id." },
        to_chain: { type: "string", description: "Destination chain: ethereum, base, solana, or the LI.FI chain id." },
        from_token: { type: "string", description: "Source token address. Use native/eth/sol for native tokens." },
        to_token: { type: "string", description: "Destination token address. Use native/eth/sol for native tokens." },
        amount_in_raw: { type: "string", description: "Input amount in token base units as a base-10 integer string." },
        from_address: { type: "string", description: "Optional source wallet address. Defaults to the active wallet when the source chain matches it." },
        to_address: { type: "string", description: "Optional destination wallet address. Defaults to the active wallet when the destination chain matches it." },
        slippage: { type: "number", description: "Optional decimal fraction, for example 0.01 for 1%." },
        allow_bridges: { type: "array", items: { type: "string" } },
        deny_bridges: { type: "array", items: { type: "string" } },
        prefer_bridges: { type: "array", items: { type: "string" } },
      },
      required: ["from_chain", "to_chain", "from_token", "to_token", "amount_in_raw"],
      additionalProperties: false,
    },
  },
  {
    name: "get_lifi_transfer_status",
    description: "Get LI.FI cross-chain transfer status using a source/destination transaction hash or LI.FI step id.",
    parameters: {
      type: "object",
      properties: {
        tx_hash: { type: "string" },
        bridge: { type: "string" },
        from_chain: { type: "string" },
        to_chain: { type: "string" },
      },
      required: ["tx_hash"],
      additionalProperties: false,
    },
  },
  {
    name: "get_evm_network",
    description: "Show the effective EVM network context, available networks, and swap-supported networks.",
    parameters: {
      type: "object",
      properties: {
        network: {
          type: "string",
          enum: ["ethereum", "base"],
        },
      },
      additionalProperties: false,
    },
  },
  {
    name: "set_evm_network",
    description:
      "Select the active EVM network for subsequent wallet tool calls in this OpenClaw plugin session. Use this to switch between ethereum and base instead of editing code or plugin configuration.",
    parameters: {
      type: "object",
      properties: {
        network: {
          type: "string",
          enum: ["ethereum", "base"],
          description: "EVM network to make active for subsequent calls.",
        },
      },
      required: ["network"],
      additionalProperties: false,
    },
  },
  {
    name: "get_evm_token_balance",
    description: "Get the ERC-20 balance for the configured EVM wallet account.",
    parameters: {
      type: "object",
      properties: {
        token_address: { type: "string" },
        network: { type: "string", enum: ["ethereum", "base"] },
      },
      required: ["token_address"],
      additionalProperties: false,
    },
  },
  {
    name: "get_evm_token_metadata",
    description: "Get ERC-20 token metadata for a contract address on the active EVM network.",
    parameters: {
      type: "object",
      properties: {
        token_address: { type: "string" },
        network: { type: "string", enum: ["ethereum", "base"] },
      },
      required: ["token_address"],
      additionalProperties: false,
    },
  },
  {
    name: "get_evm_fee_rates",
    description: "Get current EVM fee-rate suggestions for the active network.",
    parameters: {
      type: "object",
      properties: {
        network: { type: "string", enum: ["ethereum", "base"] },
      },
      additionalProperties: false,
    },
  },
  {
    name: "get_evm_transaction_receipt",
    description: "Get the transaction receipt for a broadcast EVM transaction hash.",
    parameters: {
      type: "object",
      properties: {
        tx_hash: { type: "string" },
        network: { type: "string", enum: ["ethereum", "base"] },
      },
      required: ["tx_hash"],
      additionalProperties: false,
    },
  },
  {
    name: "get_evm_aave_account",
    description: "Get read-only Aave V3 account data for the configured EVM wallet on supported mainnet networks.",
    parameters: {
      type: "object",
      properties: {
        network: { type: "string", enum: ["ethereum", "base"] },
      },
      additionalProperties: false,
    },
  },
  {
    name: "get_evm_aave_reserves",
    description: "Get the read-only Aave V3 reserve catalog for the configured EVM network, including reserve flags, pricing, and liquidity metadata.",
    parameters: {
      type: "object",
      properties: {
        network: { type: "string", enum: ["ethereum", "base"] },
      },
      additionalProperties: false,
    },
  },
  {
    name: "get_evm_aave_positions",
    description: "Get read-only Aave V3 per-reserve positions for the configured EVM wallet, including supplied and borrowed balances on supported mainnet networks.",
    parameters: {
      type: "object",
      properties: {
        network: { type: "string", enum: ["ethereum", "base"] },
      },
      additionalProperties: false,
    },
  },
  {
    name: "manage_evm_aave_position",
    description: "Preview, prepare, or execute a narrow Aave V3 lending operation on supported EVM mainnet networks. Supported operations are supply, withdraw, borrow, and repay. Prepare returns an execution plan only, and execute requires a host-issued approval token bound to the previewed operation.",
    optional: true,
    parameters: {
      type: "object",
      properties: {
        operation: { type: "string", enum: ["supply", "withdraw", "borrow", "repay"] },
        token_address: { type: "string" },
        amount_raw: { type: "string" },
        mode: { type: "string", enum: ["preview", "prepare", "execute"] },
        purpose: { type: "string" },
        user_intent: { type: "boolean" },
        approval_token: { type: "string" },
        network: { type: "string", enum: ["ethereum", "base"] },
      },
      required: ["operation", "token_address", "amount_raw", "mode", "purpose"],
      additionalProperties: false,
    },
  },
  {
    name: "get_evm_lido_overview",
    description: "Get the read-only Lido staking overview for the configured EVM wallet on supported networks, including contract addresses and sample wrap rates.",
    parameters: {
      type: "object",
      properties: {
        network: { type: "string", enum: ["ethereum"] },
      },
      additionalProperties: false,
    },
  },
  {
    name: "get_evm_lido_positions",
    description: "Get read-only Lido positions for the configured EVM wallet, including stETH, wstETH, and stETH-equivalent balances.",
    parameters: {
      type: "object",
      properties: {
        network: { type: "string", enum: ["ethereum"] },
      },
      additionalProperties: false,
    },
  },
  {
    name: "manage_evm_lido_position",
    description: "Preview, prepare, or execute a narrow Lido staking operation on Ethereum mainnet. Supported operations are stake_eth_for_wsteth, wrap_steth, and unwrap_wsteth. Prepare returns an execution plan only, and execute requires a host-issued approval token bound to the previewed operation.",
    optional: true,
    parameters: {
      type: "object",
      properties: {
        operation: { type: "string", enum: ["stake_eth_for_wsteth", "wrap_steth", "unwrap_wsteth"] },
        amount_raw: { type: "string" },
        mode: { type: "string", enum: ["preview", "prepare", "execute"] },
        purpose: { type: "string" },
        user_intent: { type: "boolean" },
        approval_token: { type: "string" },
        network: { type: "string", enum: ["ethereum"] },
      },
      required: ["operation", "amount_raw", "mode", "purpose"],
      additionalProperties: false,
    },
  },
  {
    name: "get_evm_lido_withdrawal_requests",
    description: "Get read-only Lido withdrawal queue requests for the configured EVM wallet, including finalized and claimable request statuses.",
    parameters: {
      type: "object",
      properties: {
        network: { type: "string", enum: ["ethereum"] },
      },
      additionalProperties: false,
    },
  },
  {
    name: "manage_evm_lido_withdrawal",
    description: "Preview, prepare, or execute a narrow Lido withdrawal queue operation on Ethereum mainnet. Supported operations are request_withdrawal_steth, request_withdrawal_wsteth, and claim_withdrawal. Prepare returns an execution plan only, and execute requires a host-issued approval token bound to the previewed operation.",
    optional: true,
    parameters: {
      type: "object",
      properties: {
        operation: {
          type: "string",
          enum: ["request_withdrawal_steth", "request_withdrawal_wsteth", "claim_withdrawal"],
        },
        amount_raw: { type: "string" },
        request_id: { type: "string" },
        mode: { type: "string", enum: ["preview", "prepare", "execute"] },
        purpose: { type: "string" },
        user_intent: { type: "boolean" },
        approval_token: { type: "string" },
        network: { type: "string", enum: ["ethereum"] },
      },
      required: ["operation", "mode", "purpose"],
      additionalProperties: false,
    },
  },
  {
    name: "get_evm_swap_quote",
    description: "Get a read-only Velora quote for an ERC-20 to ERC-20 swap on supported EVM mainnet networks. This does not approve or execute a swap.",
    parameters: {
      type: "object",
      properties: {
        token_in: { type: "string" },
        token_out: { type: "string" },
        amount_in_raw: { type: "string" },
        network: { type: "string", enum: ["ethereum", "base"] },
      },
      required: ["token_in", "token_out", "amount_in_raw"],
      additionalProperties: false,
    },
  },
  {
    name: "swap_evm_tokens",
    description: "Preview, prepare, or execute an ERC-20 to ERC-20 swap through Velora on supported EVM mainnet networks. Prepare returns an execution plan only, and execute requires a host-issued approval token bound to the previewed operation.",
    optional: true,
    parameters: {
      type: "object",
      properties: {
        token_in: { type: "string" },
        token_out: { type: "string" },
        amount_in_raw: { type: "string" },
        mode: { type: "string", enum: ["preview", "prepare", "execute"] },
        purpose: { type: "string" },
        user_intent: { type: "boolean" },
        approval_token: { type: "string" },
        network: { type: "string", enum: ["ethereum", "base"] },
      },
      required: ["token_in", "token_out", "amount_in_raw", "mode", "purpose"],
      additionalProperties: false,
    },
  },
  {
    name: "swap_evm_lifi_cross_chain_tokens",
    description: "Preview, prepare, or execute an EVM-origin cross-chain swap through LI.FI. This currently supports ethereum/base as the source network and ethereum/base/solana as the destination chain. Prepare returns an execution plan only, and execute requires a host-issued approval token bound to the previewed operation.",
    optional: true,
    parameters: {
      type: "object",
      properties: {
        token_in: { type: "string" },
        destination_chain: { type: "string", enum: ["ethereum", "base", "solana", "1", "8453", "1151111081099710"] },
        output_token: { type: "string" },
        destination_address: { type: "string" },
        amount_in_raw: { type: "string" },
        slippage: { type: "number" },
        allow_bridges: { type: "array", items: { type: "string" } },
        deny_bridges: { type: "array", items: { type: "string" } },
        prefer_bridges: { type: "array", items: { type: "string" } },
        mode: { type: "string", enum: ["preview", "prepare", "execute"] },
        purpose: { type: "string" },
        user_intent: { type: "boolean" },
        approval_token: { type: "string" },
        network: { type: "string", enum: ["ethereum", "base"] },
      },
      required: [
        "token_in",
        "destination_chain",
        "output_token",
        "destination_address",
        "amount_in_raw",
        "mode",
        "purpose",
      ],
      additionalProperties: false,
    },
  },
  {
    name: "transfer_evm_native",
    description: "Preview, prepare, or execute a native EVM transfer using a wei amount. Prepare returns an execution plan only, and execute requires a host-issued approval token bound to the previewed operation.",
    optional: true,
    parameters: {
      type: "object",
      properties: {
        recipient: { type: "string" },
        amount_wei: { type: "string" },
        mode: { type: "string", enum: ["preview", "prepare", "execute"] },
        purpose: { type: "string" },
        user_intent: { type: "boolean" },
        approval_token: { type: "string" },
        network: { type: "string", enum: ["ethereum", "base"] },
      },
      required: ["recipient", "amount_wei", "mode", "purpose"],
      additionalProperties: false,
    },
  },
  {
    name: "transfer_evm_token",
    description: "Preview, prepare, or execute an ERC-20 transfer using a raw base-unit amount. Prepare returns an execution plan only, and execute requires a host-issued approval token bound to the previewed operation.",
    optional: true,
    parameters: {
      type: "object",
      properties: {
        token_address: { type: "string" },
        recipient: { type: "string" },
        amount_raw: { type: "string" },
        mode: { type: "string", enum: ["preview", "prepare", "execute"] },
        purpose: { type: "string" },
        user_intent: { type: "boolean" },
        approval_token: { type: "string" },
        network: { type: "string", enum: ["ethereum", "base"] },
      },
      required: ["token_address", "recipient", "amount_raw", "mode", "purpose"],
      additionalProperties: false,
    },
  },
];

export default function registerAgentWalletPlugin(api) {
  api?.logger?.info?.("[agent-wallet] registering OpenClaw wallet plugin");

  const backend = resolveBackend(api);
  selectedWalletBackend = null;
  selectedSolanaNetwork = defaultSolanaNetwork(api);
  selectedEvmNetwork = defaultSelectableEvmNetwork(api);
  selectedBtcNetwork = defaultBtcNetwork(api);
  const duplicateSessionToolNames = new Set(
    walletSessionToolDefinitions.map((definition) => definition.name)
  );
  const toolDefinitions = [];
  const seen = new Set();
  for (const definition of [
    ...walletSessionToolDefinitions,
    ...solanaToolDefinitions.filter((item) => !duplicateSessionToolNames.has(item.name)),
    ...btcToolDefinitions.filter((item) => !duplicateSessionToolNames.has(item.name)),
    ...evmToolDefinitions.filter((item) => !duplicateSessionToolNames.has(item.name)),
  ]) {
    if (seen.has(definition.name)) {
      continue;
    }
    seen.add(definition.name);
    toolDefinitions.push(definition);
  }

  for (const definition of toolDefinitions) {
    registerTool(api, definition);
  }

  api?.logger?.info?.(
    `[agent-wallet] default wallet backend ${backend}; registered ${toolDefinitions.length} multi-wallet tools`
  );
}
