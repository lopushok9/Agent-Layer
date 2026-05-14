import process from "node:process";

const BRIDGE_NAME = "flash-sdk-bridge";
const USD_DECIMALS = 6;
const BPS_DECIMALS = 4;
const DEFAULT_COMPUTE_UNIT_LIMIT = 600_000;

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

function mockResponse(normalized) {
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

  if (normalized.action === "prepare_open_position_same_collateral") {
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
  const [anchor, web3, flashSdk] = await Promise.all([
    import("@coral-xyz/anchor"),
    import("@solana/web3.js"),
    import("flash-sdk"),
  ]);
  return { anchor, web3, flashSdk };
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

  const { anchor, web3, flashSdk } = await loadRealModules();
  const wallet = createReadOnlyWallet(web3, normalized.owner);
  const connection = new web3.Connection(rpcUrl, {
    commitment: "confirmed",
  });
  const provider = new anchor.AnchorProvider(connection, wallet, {
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
  return { anchor, web3, flashSdk, provider, poolConfig, client, rpcUrl };
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

function requireWholeNumberString(value, fieldName) {
  const normalized = requireString(value, fieldName);
  if (!/^\d+$/.test(normalized)) {
    throw new Error(`${fieldName} must be a whole-number string for the current Flash bridge MVP`);
  }
  return normalized;
}

function getSideVariant(flashSdk, side) {
  return side === "long" ? flashSdk.Side.Long : flashSdk.Side.Short;
}

function getMarketContext(runtime, normalized) {
  const sideVariant = getSideVariant(runtime.flashSdk, normalized.side);
  const marketToken = runtime.poolConfig.getTokenFromSymbol(normalized.marketSymbol);
  const collateralToken = runtime.poolConfig.getTokenFromSymbol(normalized.collateralSymbol);
  const marketConfig = runtime.poolConfig.getMarketConfig(
    marketToken.mintKey,
    collateralToken.mintKey,
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

  const { BN } = runtime.anchor;
  const privilege = runtime.flashSdk.Privilege.None;
  const ownerPublicKey = runtime.provider.wallet.publicKey;
  const { marketConfig } = getMarketContext(runtime, normalized);
  const leverage = requireWholeNumberString(normalized.leverage, "leverage");
  const quote = await runtime.client.getOpenPositionQuote(
    new BN(normalized.collateralAmountRaw),
    new BN(leverage),
    marketConfig,
    runtime.poolConfig,
    privilege,
    undefined,
    undefined,
    null,
    null,
    ownerPublicKey,
  );

  return {
    ok: true,
    preview: {
      bridge_mode: "real",
      requested_leverage: leverage,
      pool_name: normalized.poolName,
      market_symbol: normalized.marketSymbol,
      collateral_symbol: normalized.collateralSymbol,
      collateral_amount_raw: normalized.collateralAmountRaw,
      side: normalized.side,
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
  const { BN } = runtime.anchor;
  const privilege = runtime.flashSdk.Privilege.None;
  const ownerPublicKey = runtime.provider.wallet.publicKey;
  const sameCollateralNormalized = {
    ...normalized,
    collateralSymbol: normalized.collateralSymbol ?? normalized.marketSymbol,
  };
  const { marketConfig } = getMarketContext(runtime, sameCollateralNormalized);
  const positionPk = runtime.poolConfig.getPositionFromCustodyPk(
    ownerPublicKey,
    marketConfig.targetCustody,
    marketConfig.collateralCustody,
    getSideVariant(runtime.flashSdk, normalized.side),
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

  return {
    ok: true,
    preview: {
      bridge_mode: "real",
      pool_name: normalized.poolName,
      market_symbol: normalized.marketSymbol,
      collateral_symbol: sameCollateralNormalized.collateralSymbol,
      side: normalized.side,
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
  if (!normalized.collateralSymbol || !normalized.collateralAmountRaw || !normalized.leverage) {
    throw new Error(
      "collateral_symbol, collateral_amount_raw, and leverage are required for open prepare",
    );
  }
  if (normalized.collateralSymbol !== normalized.marketSymbol) {
    throw new Error(
      "Current bridge MVP supports only same-collateral opens where collateral_symbol matches market_symbol",
    );
  }

  const { BN } = runtime.anchor;
  const privilege = runtime.flashSdk.Privilege.None;
  const ownerPublicKey = runtime.provider.wallet.publicKey;
  const { marketConfig, collateralToken } = getMarketContext(runtime, normalized);
  const leverage = requireWholeNumberString(normalized.leverage, "leverage");
  const quote = await runtime.client.getOpenPositionQuote(
    new BN(normalized.collateralAmountRaw),
    new BN(leverage),
    marketConfig,
    runtime.poolConfig,
    privilege,
    undefined,
    undefined,
    null,
    null,
    ownerPublicKey,
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
    quote.entryPrice,
    new BN(normalized.collateralAmountRaw),
    quote.sizeAmount,
    getSideVariant(runtime.flashSdk, normalized.side),
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
      side: normalized.side,
      estimated_size_usd: integerExponentToDecimal(quote.sizeUsd.toString(10), -USD_DECIMALS),
      estimated_size_amount_raw: quote.sizeAmount.toString(10),
      estimated_entry_price: serializeOraclePrice(quote.entryPrice)?.ui_price ?? null,
      estimated_liquidation_price: serializeOraclePrice(quote.liquidationPrice)?.ui_price ?? null,
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
  const { BN } = runtime.anchor;
  const privilege = runtime.flashSdk.Privilege.None;
  const ownerPublicKey = runtime.provider.wallet.publicKey;
  const sameCollateralNormalized = {
    ...normalized,
    collateralSymbol: normalized.collateralSymbol ?? normalized.marketSymbol,
  };
  const { marketConfig, collateralToken } = getMarketContext(runtime, sameCollateralNormalized);
  const positionPk = runtime.poolConfig.getPositionFromCustodyPk(
    ownerPublicKey,
    marketConfig.targetCustody,
    marketConfig.collateralCustody,
    getSideVariant(runtime.flashSdk, normalized.side),
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
  const backupOracleInstructions = await runtime.flashSdk.createBackupOracleInstruction(
    runtime.poolConfig.poolAddress.toBase58(),
  );
  const computeBudgetIx = runtime.web3.ComputeBudgetProgram.setComputeUnitLimit({
    units: getComputeUnitLimit(),
  });
  const { instructions, additionalSigners } = await runtime.client.closePosition(
    normalized.marketSymbol,
    sameCollateralNormalized.collateralSymbol,
    quote.markPrice,
    getSideVariant(runtime.flashSdk, normalized.side),
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

async function realResponse(normalized) {
  const runtime = await buildRuntimeContext(normalized);
  if (normalized.action === "preview_open_position_same_collateral") {
    return getOpenPositionPreview(runtime, normalized);
  }
  if (normalized.action === "preview_close_position_same_collateral") {
    return getClosePositionPreview(runtime, normalized);
  }
  if (normalized.action === "prepare_open_position_same_collateral") {
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
