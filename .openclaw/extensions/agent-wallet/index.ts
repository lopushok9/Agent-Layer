import { execFile } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { promisify } from "node:util";

const execFileAsync = promisify(execFile);
const PLUGIN_ID = "agent-wallet";
const PLUGIN_ROOT = path.dirname(new URL(import.meta.url).pathname);

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

function resolvePythonBin(config) {
  return config.pythonBin || process.env.OPENCLAW_AGENT_WALLET_PYTHON || "python3";
}

function resolvePackageRoot(config) {
  const candidates = [
    config.packageRoot,
    process.env.OPENCLAW_AGENT_WALLET_PACKAGE_ROOT,
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
    "Could not resolve agent-wallet package root. Set plugins.entries.agent-wallet.config.packageRoot."
  );
}

function buildCliEnv(packageRoot) {
  const env = { ...process.env };
  env.PYTHONPATH = env.PYTHONPATH
    ? `${packageRoot}${path.delimiter}${env.PYTHONPATH}`
    : packageRoot;
  return env;
}

async function callWalletCli(api, command, extraArgs = []) {
  const config = resolvePluginConfig(api);
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

  const { stdout, stderr } = await execFileAsync(pythonBin, args, {
    cwd: packageRoot,
    env: buildCliEnv(packageRoot),
    maxBuffer: 1024 * 1024 * 8,
  });

  if (stderr && stderr.trim()) {
    api?.logger?.debug?.(`[agent-wallet] stderr: ${stderr.trim()}`);
  }

  const payload = JSON.parse(stdout.trim() || "{}");
  if (payload?.ok === false && payload?.error) {
    throw new Error(payload.error);
  }
  return payload;
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
      const payload = await callWalletCli(api, "invoke", [
        "--tool",
        definition.name,
        "--arguments-json",
        JSON.stringify(params ?? {}),
      ]);
      if (payload?.ok === false) {
        throw new Error(payload?.error || `${definition.name} failed`);
      }
      return asContent(payload?.data ?? {});
    },
  });
}

const toolDefinitions = [
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
    description: "Get the native token balance for the configured wallet address.",
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
    name: "get_wallet_portfolio",
    description: "Get the wallet portfolio including native balance and non-zero SPL token accounts.",
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
    description: "Preview, prepare, or execute a Solana token swap via Jupiter. Prepare returns an execution plan only, and execute requires a host-issued approval token bound to the previewed operation.",
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

export default function registerAgentWalletPlugin(api) {
  api?.logger?.info?.("[agent-wallet] registering OpenClaw wallet plugin");

  for (const definition of toolDefinitions) {
    registerTool(api, definition);
  }
}
