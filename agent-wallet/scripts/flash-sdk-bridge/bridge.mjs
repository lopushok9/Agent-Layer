import process from "node:process";
import { createRequire } from "node:module";
import util from "node:util";

const BRIDGE_NAME = "flash-sdk-bridge";
const USD_DECIMALS = 6;
const BPS_DECIMALS = 4;
const DEFAULT_COMPUTE_UNIT_LIMIT = 600_000;
// Flash docs use slippageBps = 800 with a 0.8% comment.
// The SDK uses BPS_DECIMALS=4, so 0.8% maps to raw 80.
const DEFAULT_SLIPPAGE_BPS_RAW = "80";
const require = createRequire(import.meta.url);

const forwardConsoleToStderr = (method) => {
  console[method] = (...args) => {
    const rendered = args
      .map((value) => (typeof value === "string" ? value : util.inspect(value, { depth: 5 })))
      .join(" ");
    process.stderr.write(`${rendered}\n`);
  };
};

forwardConsoleToStderr("log");
forwardConsoleToStderr("info");
forwardConsoleToStderr("warn");
forwardConsoleToStderr("debug");

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
  const owner =
    typeof payload.owner === "string" && payload.owner.trim() ? payload.owner.trim() : undefined;
  const poolName =
    typeof payload.pool_name === "string" && payload.pool_name.trim()
      ? payload.pool_name.trim()
      : undefined;
  const marketSymbol =
    typeof payload.market_symbol === "string" && payload.market_symbol.trim()
      ? payload.market_symbol.trim().toUpperCase()
      : undefined;
  const side = typeof payload.side === "string" && payload.side.trim() ? normalizeSide(payload.side) : undefined;
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

function mockResponse(normalized) {
  if (normalized.action === "get_markets") {
    return {
      ok: true,
      data: {
        bridge_mode: "mock",
        pool_name: normalized.poolName ?? null,
        pool_count: 1,
        market_count: 2,
        source: "flash-sdk-bridge",
        markets: [
          {
            pool_name: normalized.poolName ?? "Crypto.1",
            symbol: "SOL",
            market_symbol: "SOL",
            collateral_symbol: "SOL",
            side: "long",
            market_address: "MockFlashMarketLong11111111111111111111111111",
          },
          {
            pool_name: normalized.poolName ?? "Crypto.1",
            symbol: "SOL",
            market_symbol: "SOL",
            collateral_symbol: "USDC",
            side: "short",
            market_address: "MockFlashMarketShort1111111111111111111111111",
          },
        ],
      },
    };
  }

  if (normalized.action === "get_positions") {
    return {
      ok: true,
      data: {
        bridge_mode: "mock",
        owner: normalized.owner,
        pool_name: normalized.poolName ?? null,
        pool_count: 1,
        position_count: 1,
        source: "flash-sdk-bridge",
        positions: [
          {
            pool_name: normalized.poolName ?? "Crypto.1",
            symbol: "SOL",
            market_symbol: "SOL",
            collateral_symbol: "SOL",
            side: "long",
            is_active: true,
            position_address: "MockFlashPosition111111111111111111111111111",
            market_address: "MockFlashMarketLong11111111111111111111111111",
          },
        ],
      },
    };
  }

  if (
    normalized.action === "preview_open_position" ||
    normalized.action === "preview_open_position_same_collateral"
  ) {
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

  if (
    normalized.action === "prepare_open_position" ||
    normalized.action === "prepare_open_position_same_collateral"
  ) {
    return {
      ok: true,
      prepared: {
        bridge_mode: "mock",
        pool_name: normalized.poolName,
        market_symbol: normalized.marketSymbol,
        collateral_symbol: normalized.collateralSymbol,
        collateral_amount_raw: normalized.collateralAmountRaw,
        leverage: normalized.leverage,
        side: normalized.side,
        transaction_base64: "AQID",
        transaction_encoding: "base64",
        transaction_format: "versioned",
        latest_blockhash: "MockFlashBlockhash111111111111111111111111111",
        last_valid_block_height: 123456,
        market_address: "MockFlashMarket11111111111111111111111111111",
        position_address: "MockFlashPosition111111111111111111111111111",
        target_custody_address: "MockFlashTargetCustody1111111111111111111111111",
        collateral_custody_address: "MockFlashCollateralCustody1111111111111111111111",
        collateral_mint: "So11111111111111111111111111111111111111112",
        expected_program_ids: ["MockFlashProgram111111111111111111111111111111"],
      },
    };
  }

  if (normalized.action === "prepare_close_position_same_collateral") {
    return {
      ok: true,
      prepared: {
        bridge_mode: "mock",
        pool_name: normalized.poolName,
        market_symbol: normalized.marketSymbol,
        collateral_symbol: normalized.collateralSymbol ?? normalized.marketSymbol,
        side: normalized.side,
        transaction_base64: "AQID",
        transaction_encoding: "base64",
        transaction_format: "versioned",
        latest_blockhash: "MockFlashBlockhash111111111111111111111111111",
        last_valid_block_height: 123456,
        market_address: "MockFlashMarket11111111111111111111111111111",
        position_address: "MockFlashPosition111111111111111111111111111",
        target_custody_address: "MockFlashTargetCustody1111111111111111111111111",
        collateral_custody_address: "MockFlashCollateralCustody1111111111111111111111",
        collateral_mint: "So11111111111111111111111111111111111111112",
        expected_program_ids: ["MockFlashProgram111111111111111111111111111111"],
      },
    };
  }

  return jsonError(`Unsupported mock action: ${normalized.action}`);
}

async function loadRealModules() {
  if (!process.env.NEXT_PUBLIC_API_ENDPOINT && process.env.FLASH_API_ENDPOINT) {
    process.env.NEXT_PUBLIC_API_ENDPOINT = process.env.FLASH_API_ENDPOINT;
  }
  const poolConfigCatalog = require("flash-sdk/dist/PoolConfig.json");
  const [anchor, web3, flashSdk, bnModule] = await Promise.all([
    import("@coral-xyz/anchor"),
    import("@solana/web3.js"),
    import("flash-sdk"),
    import("bn.js"),
  ]);
  return { anchor, web3, flashSdk, poolConfigCatalog, BN: bnModule.default };
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
  return "mainnet-beta";
}

function defaultRpcUrlForNetwork(network) {
  if (network === "mainnet") {
    return "https://api.mainnet-beta.solana.com";
  }
  return "";
}

async function buildRuntimeContext(normalized, poolConfigOverride = null) {
  const rpcUrl =
    process.env.RPC_URL?.trim() ||
    process.env.SOLANA_RPC_URL?.trim() ||
    defaultRpcUrlForNetwork(normalized.network);
  if (!rpcUrl) {
    throw new Error("RPC_URL or SOLANA_RPC_URL is required in FLASH_SDK_BRIDGE_MODE=real");
  }

  const { anchor, web3, flashSdk, BN } = await loadRealModules();
  const wallet = createReadOnlyWallet(web3, normalized.owner);
  const connection = new web3.Connection(rpcUrl, {
    commitment: "confirmed",
  });
  const provider = new anchor.AnchorProvider(connection, wallet, {
    commitment: "confirmed",
    preflightCommitment: "confirmed",
    skipPreflight: true,
  });
  if (!normalized.owner) {
    throw new Error("owner is required");
  }
  if (!normalized.poolName) {
    throw new Error("pool_name is required");
  }
  const poolConfig =
    poolConfigOverride ||
    flashSdk.PoolConfig.fromIdsByName(normalized.poolName, resolveClusterName(normalized.network));
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
  return { anchor, web3, flashSdk, BN, provider, poolConfig, client, rpcUrl };
}

function listPoolConfigs(flashSdk, poolConfigCatalog, network, poolName) {
  const cluster = resolveClusterName(network);
  const pools = Array.isArray(poolConfigCatalog?.pools) ? poolConfigCatalog.pools : [];
  const matching = pools.filter(
    (pool) =>
      pool?.cluster === cluster &&
      (!poolName || String(pool.poolName || "").trim() === poolName),
  );
  if (matching.length === 0) {
    if (poolName) {
      throw new Error(`Pool ${poolName} is not available on ${network}`);
    }
    throw new Error(`No Flash pools are configured for ${network}`);
  }
  return matching.map((pool) => flashSdk.PoolConfig.buildPoolconfigFromJson(pool));
}

function variantToSide(sideVariant) {
  if (sideVariant && typeof sideVariant === "object") {
    if ("long" in sideVariant) {
      return "long";
    }
    if ("short" in sideVariant) {
      return "short";
    }
    if ("none" in sideVariant) {
      return "none";
    }
  }
  return String(sideVariant ?? "");
}

function safeTokenSymbol(poolConfig, mintPk) {
  try {
    return poolConfig.getTokenFromMintPk(mintPk)?.symbol ?? null;
  } catch {
    return null;
  }
}

function buildMarketSnapshot(poolConfig, marketConfig, deprecated = false) {
  const targetSymbol = safeTokenSymbol(poolConfig, marketConfig.targetMint);
  const collateralSymbol = safeTokenSymbol(poolConfig, marketConfig.collateralMint);
  return {
    pool_name: poolConfig.poolName,
    symbol: targetSymbol,
    market_symbol: targetSymbol,
    collateral_symbol: collateralSymbol,
    side: variantToSide(marketConfig.side),
    market_id: marketConfig.marketId,
    market_address: marketConfig.marketAccount.toBase58(),
    target_custody_address: marketConfig.targetCustody.toBase58(),
    collateral_custody_address: marketConfig.collateralCustody.toBase58(),
    target_mint: marketConfig.targetMint.toBase58(),
    collateral_mint: marketConfig.collateralMint.toBase58(),
    max_leverage: marketConfig.maxLev,
    degen_min_leverage: marketConfig.degenMinLev,
    degen_max_leverage: marketConfig.degenMaxLev,
    deprecated,
  };
}

function buildPositionSnapshot(poolConfig, positionAccount) {
  const marketConfig = poolConfig.getMarketConfigByPk(positionAccount.market);
  const targetSymbol = marketConfig ? safeTokenSymbol(poolConfig, marketConfig.targetMint) : null;
  const collateralSymbol = marketConfig
    ? safeTokenSymbol(poolConfig, marketConfig.collateralMint)
    : null;
  return {
    pool_name: poolConfig.poolName,
    symbol: targetSymbol,
    market_symbol: targetSymbol,
    collateral_symbol: collateralSymbol,
    side: variantToSide(marketConfig?.side),
    is_active: Boolean(positionAccount.isActive),
    position_address: positionAccount.pubkey.toBase58(),
    market_address: positionAccount.market.toBase58(),
    entry_price: serializeOraclePrice(positionAccount.entryPrice)?.ui_price ?? null,
    reference_price: serializeOraclePrice(positionAccount.referencePrice)?.ui_price ?? null,
    size_amount_raw: positionAccount.sizeAmount.toString(10),
    size_usd: integerExponentToDecimal(positionAccount.sizeUsd.toString(10), -USD_DECIMALS),
    collateral_usd: integerExponentToDecimal(
      positionAccount.collateralUsd.toString(10),
      -USD_DECIMALS,
    ),
    unsettled_value_usd: integerExponentToDecimal(
      positionAccount.unsettledValueUsd.toString(10),
      -USD_DECIMALS,
    ),
    unsettled_fees_usd: integerExponentToDecimal(
      positionAccount.unsettledFeesUsd.toString(10),
      -USD_DECIMALS,
    ),
    raw: serializeForJson(positionAccount),
  };
}

function integerExponentToDecimal(value, exponent) {
  const normalized = String(value);
  if (!/^[-]?\d+$/.test(normalized)) {
    return normalized;
  }
  if (!Number.isInteger(exponent)) {
    return normalized;
  }
  if (exponent === 0) {
    return normalized;
  }
  const negative = normalized.startsWith("-");
  const digits = negative ? normalized.slice(1) : normalized;
  if (exponent > 0) {
    return `${negative ? "-" : ""}${digits}${"0".repeat(exponent)}`;
  }
  const places = Math.abs(exponent);
  const padded = digits.padStart(places + 1, "0");
  const integerPart = padded.slice(0, -places) || "0";
  const fractionalPart = padded.slice(-places).replace(/0+$/, "");
  const unsigned = fractionalPart ? `${integerPart}.${fractionalPart}` : integerPart;
  return `${negative ? "-" : ""}${unsigned}`;
}

function serializeForJson(value) {
  if (
    value === null ||
    value === undefined ||
    typeof value === "string" ||
    typeof value === "number" ||
    typeof value === "boolean"
  ) {
    return value;
  }
  if (Array.isArray(value)) {
    return value.map((item) => serializeForJson(item));
  }
  if (Buffer.isBuffer(value)) {
    return value.toString("base64");
  }
  if (typeof value === "object" && typeof value.toBase58 === "function") {
    return value.toBase58();
  }
  if (typeof value === "object" && value.constructor?.name === "BN") {
    return value.toString(10);
  }
  if (typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value).map(([key, item]) => [key, serializeForJson(item)]),
    );
  }
  return String(value);
}

function serializeOraclePrice(oraclePrice) {
  if (!oraclePrice || typeof oraclePrice !== "object") {
    return null;
  }
  const rawPrice = oraclePrice.price?.toString?.(10) ?? null;
  const exponent = typeof oraclePrice.exponent === "number" ? oraclePrice.exponent : null;
  return {
    raw_price: rawPrice,
    exponent,
    ui_price:
      rawPrice !== null && exponent !== null
        ? integerExponentToDecimal(rawPrice, exponent)
        : null,
  };
}

function toSdkOraclePrice(runtime, oraclePriceLike) {
  if (!oraclePriceLike || typeof oraclePriceLike !== "object") {
    throw new Error("oracle price is required");
  }
  if (oraclePriceLike.exponent && typeof oraclePriceLike.exponent.toNumber === "function") {
    return oraclePriceLike;
  }
  const { BN } = runtime;
  return runtime.flashSdk.OraclePrice.from({
    price: new BN(oraclePriceLike.price?.toString?.(10) ?? String(oraclePriceLike.price ?? 0)),
    exponent: new BN(String(oraclePriceLike.exponent ?? 0)),
    confidence: new BN(String(oraclePriceLike.confidence ?? 0)),
    timestamp: new BN(String(oraclePriceLike.timestamp ?? 0)),
  });
}

function requireWholeNumberString(value, fieldName) {
  const normalized = requireString(value, fieldName);
  if (!/^\d+$/.test(normalized)) {
    throw new Error(`${fieldName} must be a whole-number string for the current Flash bridge MVP`);
  }
  return normalized;
}

function requirePositiveDecimalString(value, fieldName) {
  const normalized = requireString(value, fieldName);
  if (!/^\d+(\.\d+)?$/.test(normalized)) {
    throw new Error(`${fieldName} must be a positive decimal string`);
  }
  if (Number.parseFloat(normalized) <= 0) {
    throw new Error(`${fieldName} must be greater than zero`);
  }
  return normalized;
}

function decimalToScaledIntegerString(value, decimals, fieldName) {
  const normalized = requirePositiveDecimalString(value, fieldName);
  const [integerPart, fractionalPart = ""] = normalized.split(".");
  const paddedFraction = `${fractionalPart}${"0".repeat(decimals)}`.slice(0, decimals);
  const combined = `${integerPart}${paddedFraction}`.replace(/^0+(?=\d)/, "");
  if (!/^\d+$/.test(combined)) {
    throw new Error(`${fieldName} could not be converted to scaled integer form`);
  }
  return combined || "0";
}

function slippageTolerancePercent(slippageBpsRaw) {
  return integerExponentToDecimal(String(slippageBpsRaw), -BPS_DECIMALS + 2);
}

function getSideVariant(flashSdk, side) {
  return side === "long" ? flashSdk.Side.Long : flashSdk.Side.Short;
}

function getCustodyConfigBySymbol(poolConfig, symbol) {
  const allCustodies = [...(poolConfig.custodies || []), ...(poolConfig.custodiesDeprecated || [])];
  const custodyConfig = allCustodies.find(
    (custody) => String(custody.symbol || "").trim().toUpperCase() === symbol,
  );
  if (!custodyConfig) {
    throw new Error(`Custody ${symbol} is not available in pool ${poolConfig.poolName}`);
  }
  return custodyConfig;
}

function getMarketContext(runtime, normalized) {
  const sideVariant = getSideVariant(runtime.flashSdk, normalized.side);
  const marketToken = runtime.poolConfig.getTokenFromSymbol(normalized.marketSymbol);
  const collateralToken = runtime.poolConfig.getTokenFromSymbol(normalized.collateralSymbol);
  const targetCustodyConfig = getCustodyConfigBySymbol(runtime.poolConfig, normalized.marketSymbol);
  const collateralCustodyConfig = getCustodyConfigBySymbol(
    runtime.poolConfig,
    normalized.collateralSymbol,
  );
  const marketConfig = runtime.poolConfig.getMarketConfig(
    targetCustodyConfig.custodyAccount,
    collateralCustodyConfig.custodyAccount,
    sideVariant,
  );
  if (!marketConfig) {
    throw new Error(
      `Market ${normalized.marketSymbol}/${normalized.collateralSymbol}/${normalized.side} is not available in pool ${normalized.poolName}`,
    );
  }
  return { sideVariant, marketToken, collateralToken, marketConfig };
}

function getComputeUnitLimit() {
  const raw = process.env.FLASH_SDK_BRIDGE_COMPUTE_UNIT_LIMIT?.trim();
  if (!raw) {
    return DEFAULT_COMPUTE_UNIT_LIMIT;
  }
  const value = Number.parseInt(raw, 10);
  if (!Number.isFinite(value) || value <= 0) {
    throw new Error("FLASH_SDK_BRIDGE_COMPUTE_UNIT_LIMIT must be a positive integer");
  }
  return value;
}

async function buildVersionedTransaction(runtime, instructions, additionalSigners = []) {
  const [lookupTableState, latestBlockhash] = await Promise.all([
    runtime.client.getOrLoadAddressLookupTable(runtime.poolConfig),
    runtime.provider.connection.getLatestBlockhash("finalized"),
  ]);
  const message = runtime.web3.MessageV0.compile({
    payerKey: runtime.provider.wallet.publicKey,
    instructions,
    recentBlockhash: latestBlockhash.blockhash,
    addressLookupTableAccounts: lookupTableState.addressLookupTables,
  });
  const versionedTransaction = new runtime.web3.VersionedTransaction(message);
  if (additionalSigners.length > 0) {
    versionedTransaction.sign(additionalSigners);
  }
  return {
    transactionBase64: Buffer.from(versionedTransaction.serialize()).toString("base64"),
    latestBlockhash: latestBlockhash.blockhash,
    lastValidBlockHeight: latestBlockhash.lastValidBlockHeight,
  };
}

async function getOpenPositionPreview(runtime, normalized) {
  if (!normalized.owner) {
    throw new Error("owner is required");
  }
  if (!normalized.poolName) {
    throw new Error("pool_name is required");
  }
  if (!normalized.marketSymbol) {
    throw new Error("market_symbol is required");
  }
  if (!normalized.side) {
    throw new Error("side is required");
  }
  if (!normalized.collateralSymbol || !normalized.collateralAmountRaw || !normalized.leverage) {
    throw new Error(
      "collateral_symbol, collateral_amount_raw, and leverage are required for open preview",
    );
  }
  const { BN } = runtime;
  const privilege = runtime.flashSdk.Privilege.None;
  const ownerPublicKey = runtime.provider.wallet.publicKey;
  const { marketConfig, sideVariant } = getMarketContext(runtime, normalized);
  const leverage = requirePositiveDecimalString(normalized.leverage, "leverage");
  const leverageRaw = decimalToScaledIntegerString(leverage, BPS_DECIMALS, "leverage");
  const slippageBpsRaw = DEFAULT_SLIPPAGE_BPS_RAW;
  const slippageBps = new BN(slippageBpsRaw);
  const quote = await runtime.client.getOpenPositionQuote(
    new BN(normalized.collateralAmountRaw),
    new BN(leverageRaw),
    marketConfig,
    runtime.poolConfig,
    privilege,
    undefined,
    undefined,
    null,
    null,
    ownerPublicKey,
  );
  const priceAfterSlippage = runtime.client.getPriceAfterSlippage(
    true,
    slippageBps,
    toSdkOraclePrice(runtime, quote.entryPrice),
    sideVariant,
  );

  return {
    ok: true,
    preview: {
      bridge_mode: "real",
      requested_leverage: leverage,
      requested_leverage_raw: leverageRaw,
      pool_name: normalized.poolName,
      market_symbol: normalized.marketSymbol,
      collateral_symbol: normalized.collateralSymbol,
      collateral_amount_raw: normalized.collateralAmountRaw,
      side: normalized.side,
      slippage_bps_raw: slippageBpsRaw,
      slippage_tolerance_percent: slippageTolerancePercent(slippageBpsRaw),
      estimated_size_usd: integerExponentToDecimal(quote.sizeUsd.toString(10), -USD_DECIMALS),
      estimated_size_amount_raw: quote.sizeAmount.toString(10),
      estimated_collateral_usd: integerExponentToDecimal(
        quote.collateralUsd.toString(10),
        -USD_DECIMALS,
      ),
      estimated_collateral_amount_raw: quote.collateralAmount.toString(10),
      estimated_entry_price: serializeOraclePrice(quote.entryPrice)?.ui_price ?? null,
      estimated_liquidation_price: serializeOraclePrice(quote.liquidationPrice)?.ui_price ?? null,
      estimated_entry_fee_usd: integerExponentToDecimal(
        quote.entryFeeUsd.toString(10),
        -USD_DECIMALS,
      ),
      estimated_total_fee_usd: integerExponentToDecimal(
        quote.totalFeeUsd.toString(10),
        -USD_DECIMALS,
      ),
      estimated_entry_price_with_slippage: serializeOraclePrice(priceAfterSlippage)?.ui_price ?? null,
      estimated_fee_rate_bps: quote.feeRate.toString(10),
      estimated_available_liquidity_usd: integerExponentToDecimal(
        quote.availableLiquidityUsd.toString(10),
        -USD_DECIMALS,
      ),
      estimated_borrow_fee_rate: quote.borrowFeeRate.toString(10),
      quote: serializeForJson(quote),
    },
  };
}

async function getClosePositionPreview(runtime, normalized) {
  if (!normalized.owner) {
    throw new Error("owner is required");
  }
  if (!normalized.poolName) {
    throw new Error("pool_name is required");
  }
  if (!normalized.marketSymbol) {
    throw new Error("market_symbol is required");
  }
  if (!normalized.side) {
    throw new Error("side is required");
  }
  const { BN } = runtime;
  const privilege = runtime.flashSdk.Privilege.None;
  const ownerPublicKey = runtime.provider.wallet.publicKey;
  const sameCollateralNormalized = {
    ...normalized,
    collateralSymbol: normalized.collateralSymbol ?? normalized.marketSymbol,
  };
  const { marketConfig, sideVariant } = getMarketContext(runtime, sameCollateralNormalized);
  const slippageBpsRaw = DEFAULT_SLIPPAGE_BPS_RAW;
  const slippageBps = new BN(slippageBpsRaw);
  const positionPk = runtime.poolConfig.getPositionFromCustodyPk(
    ownerPublicKey,
    marketConfig.targetCustody,
    marketConfig.collateralCustody,
    sideVariant,
  );
  const positionAccount = await runtime.client.getPosition(positionPk);
  if (!positionAccount?.isActive) {
    throw new Error(
      `No active Flash position found for ${normalized.marketSymbol}/${normalized.side} in pool ${normalized.poolName}`,
    );
  }
  const quote = await runtime.client.getClosePositionQuote(
    positionPk,
    positionAccount,
    runtime.poolConfig,
    new BN(0),
    privilege,
    undefined,
    null,
    null,
    ownerPublicKey,
  );
  const priceAfterSlippage = runtime.client.getPriceAfterSlippage(
    false,
    slippageBps,
    toSdkOraclePrice(runtime, quote.markPrice),
    sideVariant,
  );

  return {
    ok: true,
    preview: {
      bridge_mode: "real",
      pool_name: normalized.poolName,
      market_symbol: normalized.marketSymbol,
      collateral_symbol: sameCollateralNormalized.collateralSymbol,
      side: normalized.side,
      slippage_bps_raw: slippageBpsRaw,
      slippage_tolerance_percent: slippageTolerancePercent(slippageBpsRaw),
      position_pubkey: positionPk.toBase58(),
      position_size_usd: integerExponentToDecimal(
        positionAccount.sizeUsd.toString(10),
        -USD_DECIMALS,
      ),
      position_size_amount_raw: quote.existingSize.toString(10),
      close_amount_raw: quote.receiveTokenAmount.toString(10),
      estimated_receive_amount_usd: integerExponentToDecimal(
        quote.receiveTokenAmountUsd.toString(10),
        -USD_DECIMALS,
      ),
      estimated_mark_price: serializeOraclePrice(quote.markPrice)?.ui_price ?? null,
      estimated_entry_price: serializeOraclePrice(quote.entryPrice)?.ui_price ?? null,
      estimated_existing_liquidation_price:
        serializeOraclePrice(quote.existingLiquidationPrice)?.ui_price ?? null,
      estimated_new_liquidation_price:
        serializeOraclePrice(quote.newLiquidationPrice)?.ui_price ?? null,
      estimated_profit_usd: integerExponentToDecimal(quote.profitUsd.toString(10), -USD_DECIMALS),
      estimated_loss_usd: integerExponentToDecimal(quote.lossUsd.toString(10), -USD_DECIMALS),
      estimated_settled_pnl_usd: integerExponentToDecimal(
        quote.settledPnlUsd.toString(10),
        -USD_DECIMALS,
      ),
      estimated_exit_price_with_slippage: serializeOraclePrice(priceAfterSlippage)?.ui_price ?? null,
      estimated_exit_fee_usd: integerExponentToDecimal(
        quote.exitFeeUsd.toString(10),
        -USD_DECIMALS,
      ),
      estimated_total_fees_usd: integerExponentToDecimal(quote.fees.toString(10), -USD_DECIMALS),
      estimated_existing_leverage: integerExponentToDecimal(
        quote.existingLeverage.toString(10),
        -BPS_DECIMALS,
      ),
      estimated_new_leverage: integerExponentToDecimal(
        quote.newLeverage.toString(10),
        -BPS_DECIMALS,
      ),
      is_profitable: Boolean(quote.isProfitable),
      is_solvent: Boolean(quote.isSolvent),
      is_partial_close: Boolean(quote.isPartialClose),
      quote: serializeForJson(quote),
      position: serializeForJson(positionAccount),
    },
  };
}

async function prepareOpenPosition(runtime, normalized) {
  if (!normalized.owner) {
    throw new Error("owner is required");
  }
  if (!normalized.poolName) {
    throw new Error("pool_name is required");
  }
  if (!normalized.marketSymbol) {
    throw new Error("market_symbol is required");
  }
  if (!normalized.side) {
    throw new Error("side is required");
  }
  if (!normalized.collateralSymbol || !normalized.collateralAmountRaw || !normalized.leverage) {
    throw new Error(
      "collateral_symbol, collateral_amount_raw, and leverage are required for open prepare",
    );
  }
  const { BN } = runtime;
  const privilege = runtime.flashSdk.Privilege.None;
  const ownerPublicKey = runtime.provider.wallet.publicKey;
  const { marketConfig, collateralToken, sideVariant } = getMarketContext(runtime, normalized);
  const leverage = requirePositiveDecimalString(normalized.leverage, "leverage");
  const leverageRaw = decimalToScaledIntegerString(leverage, BPS_DECIMALS, "leverage");
  const slippageBpsRaw = DEFAULT_SLIPPAGE_BPS_RAW;
  const slippageBps = new BN(slippageBpsRaw);
  const quote = await runtime.client.getOpenPositionQuote(
    new BN(normalized.collateralAmountRaw),
    new BN(leverageRaw),
    marketConfig,
    runtime.poolConfig,
    privilege,
    undefined,
    undefined,
    null,
    null,
    ownerPublicKey,
  );
  const priceAfterSlippage = runtime.client.getPriceAfterSlippage(
    true,
    slippageBps,
    toSdkOraclePrice(runtime, quote.entryPrice),
    sideVariant,
  );
  const backupOracleInstructions = await runtime.flashSdk.createBackupOracleInstruction(
    runtime.poolConfig.poolAddress.toBase58(),
  );
  const computeBudgetIx = runtime.web3.ComputeBudgetProgram.setComputeUnitLimit({
    units: getComputeUnitLimit(),
  });
  const { instructions, additionalSigners } = await runtime.client.openPosition(
    normalized.marketSymbol,
    normalized.collateralSymbol,
    priceAfterSlippage,
    new BN(normalized.collateralAmountRaw),
    quote.sizeAmount,
    sideVariant,
    runtime.poolConfig,
    privilege,
  );
  const fullInstructions = [computeBudgetIx, ...backupOracleInstructions, ...instructions];
  const builtTransaction = await buildVersionedTransaction(
    runtime,
    fullInstructions,
    additionalSigners,
  );
  return {
    ok: true,
    prepared: {
      bridge_mode: "real",
      pool_name: normalized.poolName,
      market_symbol: normalized.marketSymbol,
      collateral_symbol: normalized.collateralSymbol,
      collateral_amount_raw: normalized.collateralAmountRaw,
      leverage,
      leverage_raw: leverageRaw,
      side: normalized.side,
      slippage_bps_raw: slippageBpsRaw,
      slippage_tolerance_percent: slippageTolerancePercent(slippageBpsRaw),
      estimated_size_usd: integerExponentToDecimal(quote.sizeUsd.toString(10), -USD_DECIMALS),
      estimated_size_amount_raw: quote.sizeAmount.toString(10),
      estimated_entry_price: serializeOraclePrice(quote.entryPrice)?.ui_price ?? null,
      estimated_liquidation_price: serializeOraclePrice(quote.liquidationPrice)?.ui_price ?? null,
      estimated_entry_price_with_slippage: serializeOraclePrice(priceAfterSlippage)?.ui_price ?? null,
      transaction_base64: builtTransaction.transactionBase64,
      transaction_encoding: "base64",
      transaction_format: "versioned",
      latest_blockhash: builtTransaction.latestBlockhash,
      last_valid_block_height: builtTransaction.lastValidBlockHeight,
      market_address: marketConfig.marketAccount.toBase58(),
      position_address: runtime.poolConfig
        .getPositionFromMarketPk(ownerPublicKey, marketConfig.marketAccount)
        .toBase58(),
      target_custody_address: marketConfig.targetCustody.toBase58(),
      collateral_custody_address: marketConfig.collateralCustody.toBase58(),
      collateral_mint: collateralToken.mintKey.toBase58(),
      expected_program_ids: Array.from(
        new Set([
          runtime.poolConfig.programId.toBase58(),
          runtime.poolConfig.perpComposibilityProgramId.toBase58(),
          ...fullInstructions.map((instruction) => instruction.programId.toBase58()),
        ]),
      ),
      quote: serializeForJson(quote),
      instruction_count: fullInstructions.length,
      additional_signer_count: additionalSigners.length,
    },
  };
}

async function prepareClosePosition(runtime, normalized) {
  if (!normalized.owner) {
    throw new Error("owner is required");
  }
  if (!normalized.poolName) {
    throw new Error("pool_name is required");
  }
  if (!normalized.marketSymbol) {
    throw new Error("market_symbol is required");
  }
  if (!normalized.side) {
    throw new Error("side is required");
  }
  const { BN } = runtime;
  const privilege = runtime.flashSdk.Privilege.None;
  const ownerPublicKey = runtime.provider.wallet.publicKey;
  const sameCollateralNormalized = {
    ...normalized,
    collateralSymbol: normalized.collateralSymbol ?? normalized.marketSymbol,
  };
  const { marketConfig, collateralToken, sideVariant } = getMarketContext(runtime, sameCollateralNormalized);
  const slippageBpsRaw = DEFAULT_SLIPPAGE_BPS_RAW;
  const slippageBps = new BN(slippageBpsRaw);
  const positionPk = runtime.poolConfig.getPositionFromCustodyPk(
    ownerPublicKey,
    marketConfig.targetCustody,
    marketConfig.collateralCustody,
    sideVariant,
  );
  const positionAccount = await runtime.client.getPosition(positionPk);
  if (!positionAccount?.isActive) {
    throw new Error(
      `No active Flash position found for ${normalized.marketSymbol}/${normalized.side} in pool ${normalized.poolName}`,
    );
  }
  const quote = await runtime.client.getClosePositionQuote(
    positionPk,
    positionAccount,
    runtime.poolConfig,
    new BN(0),
    privilege,
    undefined,
    null,
    null,
    ownerPublicKey,
  );
  const priceAfterSlippage = runtime.client.getPriceAfterSlippage(
    false,
    slippageBps,
    toSdkOraclePrice(runtime, quote.markPrice),
    sideVariant,
  );
  const backupOracleInstructions = await runtime.flashSdk.createBackupOracleInstruction(
    runtime.poolConfig.poolAddress.toBase58(),
  );
  const computeBudgetIx = runtime.web3.ComputeBudgetProgram.setComputeUnitLimit({
    units: getComputeUnitLimit(),
  });
  const { instructions, additionalSigners } = await runtime.client.closePosition(
    normalized.marketSymbol,
    sameCollateralNormalized.collateralSymbol,
    priceAfterSlippage,
    sideVariant,
    runtime.poolConfig,
    privilege,
  );
  const fullInstructions = [computeBudgetIx, ...backupOracleInstructions, ...instructions];
  const builtTransaction = await buildVersionedTransaction(
    runtime,
    fullInstructions,
    additionalSigners,
  );
  return {
    ok: true,
    prepared: {
      bridge_mode: "real",
      pool_name: normalized.poolName,
      market_symbol: normalized.marketSymbol,
      collateral_symbol: sameCollateralNormalized.collateralSymbol,
      side: normalized.side,
      slippage_bps_raw: slippageBpsRaw,
      slippage_tolerance_percent: slippageTolerancePercent(slippageBpsRaw),
      position_pubkey: positionPk.toBase58(),
      position_size_usd: integerExponentToDecimal(
        positionAccount.sizeUsd.toString(10),
        -USD_DECIMALS,
      ),
      close_amount_raw: quote.receiveTokenAmount.toString(10),
      estimated_receive_amount_usd: integerExponentToDecimal(
        quote.receiveTokenAmountUsd.toString(10),
        -USD_DECIMALS,
      ),
      estimated_mark_price: serializeOraclePrice(quote.markPrice)?.ui_price ?? null,
      estimated_exit_price_with_slippage: serializeOraclePrice(priceAfterSlippage)?.ui_price ?? null,
      estimated_existing_liquidation_price:
        serializeOraclePrice(quote.existingLiquidationPrice)?.ui_price ?? null,
      transaction_base64: builtTransaction.transactionBase64,
      transaction_encoding: "base64",
      transaction_format: "versioned",
      latest_blockhash: builtTransaction.latestBlockhash,
      last_valid_block_height: builtTransaction.lastValidBlockHeight,
      market_address: marketConfig.marketAccount.toBase58(),
      position_address: positionPk.toBase58(),
      target_custody_address: marketConfig.targetCustody.toBase58(),
      collateral_custody_address: marketConfig.collateralCustody.toBase58(),
      collateral_mint: collateralToken.mintKey.toBase58(),
      expected_program_ids: Array.from(
        new Set([
          runtime.poolConfig.programId.toBase58(),
          runtime.poolConfig.perpComposibilityProgramId.toBase58(),
          ...fullInstructions.map((instruction) => instruction.programId.toBase58()),
        ]),
      ),
      quote: serializeForJson(quote),
      position: serializeForJson(positionAccount),
      instruction_count: fullInstructions.length,
      additional_signer_count: additionalSigners.length,
    },
  };
}

async function getMarketsReal(normalized) {
  const { flashSdk, poolConfigCatalog } = await loadRealModules();
  const poolConfigs = listPoolConfigs(
    flashSdk,
    poolConfigCatalog,
    normalized.network,
    normalized.poolName,
  );
  const markets = [];
  for (const poolConfig of poolConfigs) {
    for (const marketConfig of poolConfig.markets || []) {
      markets.push(buildMarketSnapshot(poolConfig, marketConfig, false));
    }
    for (const marketConfig of poolConfig.marketsDeprecated || []) {
      markets.push(buildMarketSnapshot(poolConfig, marketConfig, true));
    }
  }
  return {
    ok: true,
    data: {
      bridge_mode: "real",
      pool_name: normalized.poolName ?? null,
      pool_count: poolConfigs.length,
      market_count: markets.length,
      source: "flash-sdk-bridge",
      markets,
    },
  };
}

async function getPositionsReal(normalized) {
  if (!normalized.owner) {
    throw new Error("owner is required");
  }
  const modules = await loadRealModules();
  const poolConfigs = listPoolConfigs(
    modules.flashSdk,
    modules.poolConfigCatalog,
    normalized.network,
    normalized.poolName,
  );
  const positions = [];
  for (const poolConfig of poolConfigs) {
    const runtime = await buildRuntimeContext(
      {
        ...normalized,
        owner: normalized.owner,
        poolName: poolConfig.poolName,
      },
      poolConfig,
    );
    const poolPositions = await runtime.client.getUserPositions(
      runtime.provider.wallet.publicKey,
      poolConfig,
    );
    for (const positionAccount of poolPositions || []) {
      if (!positionAccount?.isActive) {
        continue;
      }
      positions.push(buildPositionSnapshot(poolConfig, positionAccount));
    }
  }
  return {
    ok: true,
    data: {
      bridge_mode: "real",
      owner: normalized.owner,
      pool_name: normalized.poolName ?? null,
      pool_count: poolConfigs.length,
      position_count: positions.length,
      source: "flash-sdk-bridge",
      positions,
    },
  };
}

async function realResponse(normalized) {
  if (normalized.action === "get_markets") {
    return getMarketsReal(normalized);
  }
  if (normalized.action === "get_positions") {
    return getPositionsReal(normalized);
  }
  const runtime = await buildRuntimeContext(normalized);
  if (
    normalized.action === "preview_open_position" ||
    normalized.action === "preview_open_position_same_collateral"
  ) {
    return getOpenPositionPreview(runtime, normalized);
  }
  if (normalized.action === "preview_close_position_same_collateral") {
    return getClosePositionPreview(runtime, normalized);
  }
  if (
    normalized.action === "prepare_open_position" ||
    normalized.action === "prepare_open_position_same_collateral"
  ) {
    return prepareOpenPosition(runtime, normalized);
  }
  if (normalized.action === "prepare_close_position_same_collateral") {
    return prepareClosePosition(runtime, normalized);
  }
  return jsonError(`Unsupported real action: ${normalized.action}`, {
    detail: {
      bridge_mode: "real",
      rpc_url: runtime.rpcUrl,
      pool_name: normalized.poolName,
      market_symbol: normalized.marketSymbol,
      network: normalized.network,
      pool_address:
        runtime.poolConfig.poolAddress && typeof runtime.poolConfig.poolAddress.toBase58 === "function"
          ? runtime.poolConfig.poolAddress.toBase58()
          : null,
    },
  });
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
      response = mockResponse(normalized);
    } else if (mode === "real") {
      response = await realResponse(normalized);
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
