import process from "node:process";

const BRIDGE_NAME = "flash-sdk-bridge";

function jsonError(message, extra = {}) {
  return {
    ok: false,
    error: message,
    provider: BRIDGE_NAME,
    ...extra,
  };
}

function requireString(value, fieldName) {
  if (typeof value !== "string" || value.trim() === "") {
    throw new Error(`${fieldName} is required`);
  }
  return value.trim();
}

function normalizeSide(value) {
  const side = requireString(value, "side").toLowerCase();
  if (side !== "long" && side !== "short") {
    throw new Error("side must be 'long' or 'short'");
  }
  return side;
}

function normalizeActionInput(payload) {
  const action = requireString(payload.action, "action");
  const owner = requireString(payload.owner, "owner");
  const poolName = requireString(payload.pool_name, "pool_name");
  const marketSymbol = requireString(payload.market_symbol, "market_symbol").toUpperCase();
  const side = normalizeSide(payload.side);
  return {
    action,
    owner,
    poolName,
    marketSymbol,
    side,
    collateralSymbol:
      typeof payload.collateral_symbol === "string"
        ? payload.collateral_symbol.trim().toUpperCase()
        : undefined,
    collateralAmountRaw:
      typeof payload.collateral_amount_raw === "string"
        ? payload.collateral_amount_raw.trim()
        : undefined,
    leverage:
      typeof payload.leverage === "string"
        ? payload.leverage.trim()
        : undefined,
    network:
      typeof payload.network === "string" && payload.network.trim()
        ? payload.network.trim()
        : "mainnet",
  };
}

function mockPreview(normalized) {
  if (normalized.action === "preview_open_position_same_collateral") {
    return {
      ok: true,
      preview: {
        bridge_mode: "mock",
        estimated_size_usd: "1250.00",
        estimated_entry_price: "177.50",
        estimated_liquidation_price: "161.20",
        pool_name: normalized.poolName,
        market_symbol: normalized.marketSymbol,
        collateral_symbol: normalized.collateralSymbol,
        collateral_amount_raw: normalized.collateralAmountRaw,
        leverage: normalized.leverage,
        side: normalized.side,
      },
    };
  }

  if (normalized.action === "preview_close_position_same_collateral") {
    return {
      ok: true,
      preview: {
        bridge_mode: "mock",
        position_size_usd: "1250.00",
        close_amount_raw: "700000000",
        pool_name: normalized.poolName,
        market_symbol: normalized.marketSymbol,
        side: normalized.side,
      },
    };
  }

  return jsonError(`Unsupported mock action: ${normalized.action}`);
}

async function loadRealModules() {
  const [{ AnchorProvider }, web3, flashSdk] = await Promise.all([
    import("@coral-xyz/anchor"),
    import("@solana/web3.js"),
    import("flash-sdk"),
  ]);
  return { AnchorProvider, web3, flashSdk };
}

function createReadOnlyWallet(web3, owner) {
  const publicKey = new web3.PublicKey(owner);
  return {
    publicKey,
    async signTransaction() {
      throw new Error("Readonly Flash bridge wallet cannot sign transactions");
    },
    async signAllTransactions() {
      throw new Error("Readonly Flash bridge wallet cannot sign transactions");
    },
  };
}

function resolveClusterName(network) {
  return network === "mainnet" ? "mainnet-beta" : network;
}

async function buildRuntimeContext(normalized) {
  const rpcUrl = process.env.RPC_URL?.trim() || process.env.SOLANA_RPC_URL?.trim();
  if (!rpcUrl) {
    throw new Error("RPC_URL or SOLANA_RPC_URL is required in FLASH_SDK_BRIDGE_MODE=real");
  }

  const { AnchorProvider, web3, flashSdk } = await loadRealModules();
  const wallet = createReadOnlyWallet(web3, normalized.owner);
  const connection = new web3.Connection(rpcUrl, {
    commitment: "confirmed",
  });
  const provider = new AnchorProvider(connection, wallet, {
    commitment: "confirmed",
    preflightCommitment: "confirmed",
    skipPreflight: true,
  });
  const poolConfig = flashSdk.PoolConfig.fromIdsByName(
    normalized.poolName,
    resolveClusterName(normalized.network),
  );
  const client = new flashSdk.PerpetualsClient(
    provider,
    poolConfig.programId,
    poolConfig.perpComposibilityProgramId,
    poolConfig.fbNftRewardProgramId,
    poolConfig.rewardDistributionProgram.programId,
    {
      prioritizationFee: 0,
    },
  );
  return { web3, flashSdk, provider, poolConfig, client, rpcUrl };
}

async function realPreview(normalized) {
  const runtime = await buildRuntimeContext(normalized);
  const targetToken = runtime.poolConfig.tokens.find(
    (token) => String(token.symbol || "").toUpperCase() === normalized.marketSymbol,
  );
  if (!targetToken) {
    throw new Error(
      `Market symbol ${normalized.marketSymbol} is not available in pool ${normalized.poolName}`,
    );
  }

  if (normalized.action === "preview_open_position_same_collateral") {
    if (!normalized.collateralSymbol || !normalized.collateralAmountRaw || !normalized.leverage) {
      throw new Error(
        "collateral_symbol, collateral_amount_raw, and leverage are required for open preview",
      );
    }
    if (normalized.collateralSymbol !== normalized.marketSymbol) {
      throw new Error(
        "Current bridge MVP supports only same-collateral opens where collateral_symbol matches market_symbol",
      );
    }
  }

  return jsonError(
    `Real Flash SDK builder for action '${normalized.action}' is not implemented yet`,
    {
      detail: {
        bridge_mode: "real",
        rpc_url: runtime.rpcUrl,
        pool_name: normalized.poolName,
        market_symbol: normalized.marketSymbol,
        network: normalized.network,
        token_decimals: targetToken.decimals ?? null,
        pool_address:
          runtime.poolConfig.poolAddress && typeof runtime.poolConfig.poolAddress.toBase58 === "function"
            ? runtime.poolConfig.poolAddress.toBase58()
            : null,
      },
    },
  );
}

async function readStdinJson() {
  const chunks = [];
  for await (const chunk of process.stdin) {
    chunks.push(chunk);
  }
  const raw = Buffer.concat(chunks).toString("utf8").trim();
  if (!raw) {
    return {};
  }
  return JSON.parse(raw);
}

async function main() {
  try {
    const payload = await readStdinJson();
    const normalized = normalizeActionInput(payload);
    const mode = (process.env.FLASH_SDK_BRIDGE_MODE || "mock").trim().toLowerCase();

    let response;
    if (mode === "mock") {
      response = mockPreview(normalized);
    } else if (mode === "real") {
      response = await realPreview(normalized);
    } else {
      response = jsonError(`Unsupported FLASH_SDK_BRIDGE_MODE: ${mode}`);
    }

    process.stdout.write(`${JSON.stringify(response)}\n`);
    process.exit(response.ok === false ? 1 : 0);
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    process.stdout.write(`${JSON.stringify(jsonError(message))}\n`);
    process.exit(1);
  }
}

await main();
