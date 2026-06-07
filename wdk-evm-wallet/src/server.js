import "dotenv/config";

import crypto from "node:crypto";
import { createServer } from "node:http";

import { loadConfig } from "./config.js";
import { readJsonBody, sendJson } from "./json.js";
import { LocalEvmVault } from "./local_vault.js";
import { EvmNetworkState } from "./network_state.js";
import { WdkEvmWalletService } from "./wdk_evm_wallet.js";

const config = loadConfig();
const service = new WdkEvmWalletService(config);
const vault = new LocalEvmVault(config);
const networkState = new EvmNetworkState(config);

function normalizeErrorCode(errorCode, pathname, message) {
  const code = String(errorCode || "").trim().toLowerCase();
  const lower = String(message || "").toLowerCase();
  const isTokenPath = pathname.includes("/token");
  const isTokenReadPath =
    pathname.includes("/token-balance/") || pathname.includes("/token-metadata/");

  if (code === "insufficient_funds") {
    return "insufficient_funds";
  }
  if (code === "network_unavailable") {
    return "network_unavailable";
  }
  if (
    code === "swap_quote_changed" ||
    code === "swap_simulation_failed" ||
    code === "swap_approval_required" ||
    code === "swap_approval_failed" ||
    code === "swap_approval_timeout" ||
    code === "swap_cleanup_failed" ||
    code === "aave_quote_changed" ||
    code === "aave_approval_required" ||
    code === "aave_fee_unavailable" ||
    code === "aave_cleanup_failed" ||
    code === "token_transfer_failed" ||
    code === "fee_limit_exceeded" ||
    code === "token_read_failed" ||
    code === "uniswap_api_key_missing" ||
    code === "uniswap_unsupported_route" ||
    code === "uniswap_unexpected_router"
  ) {
    return code;
  }
  if (
    code === "call_exception" ||
    code === "bad_data" ||
    code === "execution_reverted" ||
    code === "contract_not_found"
  ) {
    if (isTokenReadPath) {
      return "token_not_found";
    }
  }
  if (
    code === "econnrefused" ||
    code === "enotfound" ||
    code === "etimedout" ||
    code === "fetch_failed"
  ) {
    return "network_unavailable";
  }

  if (lower.includes("wallet is locked")) {
    return "wallet_locked";
  }
  if (lower.includes("insufficient funds")) {
    return "insufficient_funds";
  }
  if (
    lower.includes("recipient must be a valid") ||
    lower.includes("recipient must not be the zero address") ||
    lower.includes("to must be a valid") ||
    lower.includes("to must not be the zero address") ||
    lower.includes("invalid address") ||
    lower.includes("bad address checksum")
  ) {
    return "recipient_invalid";
  }
  if (
    isTokenReadPath &&
    (lower.includes("missing revert data") ||
      lower.includes("call exception") ||
      lower.includes("could not decode result data") ||
      lower.includes("no contract code") ||
      lower.includes("execution reverted"))
  ) {
    return "token_not_found";
  }
  if (
    lower.includes("rpc network unavailable") ||
    lower.includes("rpc request failed") ||
    lower.includes("rpc returned invalid json") ||
    lower.includes("fetch failed") ||
    lower.includes("network unavailable") ||
    lower.includes("timeout")
  ) {
    return "network_unavailable";
  }
  if (lower.includes("unknown walletid")) {
    return "wallet_not_found";
  }
  if (lower.includes("invalid password")) {
    return "invalid_password";
  }

  return null;
}

function errorStatusCode(errorCode, fallback = 400) {
  if (errorCode === "wallet_locked" || errorCode === "insufficient_funds") {
    return 409;
  }
  if (errorCode === "swap_quote_changed") {
    return 409;
  }
  if (errorCode === "aave_quote_changed") {
    return 409;
  }
  if (
    errorCode === "swap_simulation_failed" ||
    errorCode === "swap_approval_required" ||
    errorCode === "swap_approval_failed" ||
    errorCode === "swap_approval_timeout" ||
    errorCode === "swap_cleanup_failed" ||
    errorCode === "aave_approval_required" ||
    errorCode === "aave_fee_unavailable" ||
    errorCode === "aave_cleanup_failed" ||
    errorCode === "token_transfer_failed" ||
    errorCode === "fee_limit_exceeded" ||
    errorCode === "uniswap_api_key_missing"
  ) {
    return 400;
  }
  if (errorCode === "uniswap_unsupported_route") {
    return 422;
  }
  if (errorCode === "uniswap_unexpected_router") {
    return 502;
  }
  if (errorCode === "token_read_failed") {
    return 502;
  }
  if (errorCode === "network_unavailable") {
    return 503;
  }
  if (errorCode === "wallet_not_found" || errorCode === "token_not_found") {
    return 404;
  }
  return fallback;
}

function sanitizeProviderUrl(value) {
  const raw = String(value || "").trim();
  if (!raw) {
    return raw;
  }
  try {
    const url = new URL(raw);
    if (url.searchParams.has("token")) {
      url.searchParams.set("token", "***");
    }
    return url.toString();
  } catch {
    return raw;
  }
}

function sanitizeProfiles(profiles = {}) {
  return Object.fromEntries(
    Object.entries(profiles).map(([network, profile]) => [
      network,
      {
        ...profile,
        providerUrl: sanitizeProviderUrl(profile?.providerUrl),
      },
    ])
  );
}

function toErrorResponse(error, pathname, fallbackStatus = 400) {
  const message = error instanceof Error ? error.message : String(error);
  const explicitCode =
    (typeof error?.errorCode === "string" && error.errorCode.trim()) ||
    (typeof error?.code === "string" && error.code.trim()) ||
    "";
  const errorCode = normalizeErrorCode(explicitCode, pathname, message);
  const details =
    error && typeof error === "object" && error.errorDetails && typeof error.errorDetails === "object"
      ? { ...error.errorDetails }
      : {};
  details.source = "wdk-evm-wallet";
  details.path = pathname;
  return {
    statusCode: errorStatusCode(errorCode, fallbackStatus),
    payload: {
      ok: false,
      error: message,
      ...(errorCode ? { error_code: errorCode } : {}),
      error_details: details,
    },
  };
}

function notFound(response) {
  sendJson(response, 404, { ok: false, error: "Not Found" });
}

function unauthorized(response) {
  response.setHeader("WWW-Authenticate", 'Bearer realm="wdk-evm-wallet"');
  sendJson(response, 401, { ok: false, error: "Unauthorized." });
}

function pathRequiresAuth(pathname) {
  return pathname !== "/health";
}

function isAuthorized(request) {
  const header = String(request.headers.authorization || "").trim();
  if (!header.startsWith("Bearer ")) {
    return false;
  }
  const provided = Buffer.from(header.slice("Bearer ".length).trim(), "utf8");
  const expected = Buffer.from(String(config.authToken || ""), "utf8");
  if (provided.length === 0 || provided.length !== expected.length) {
    return false;
  }
  return crypto.timingSafeEqual(provided, expected);
}

async function withResolvedSeed(body = {}) {
  const resolved = await vault.resolveSeedPhrase({
    walletId: body.walletId,
    seedPhrase: body.seedPhrase,
    password: body.password,
  });
  return {
    ...body,
    seedPhrase: resolved.seedPhrase,
    walletId: resolved.walletId ?? body.walletId ?? null,
    credentialSource: resolved.source,
    unlockExpiresAt: resolved.unlockExpiresAt ?? null,
  };
}

async function withResolvedSeedOrAddress(body = {}) {
  const address = typeof body.address === "string" ? body.address.trim() : "";
  if (address) {
    return {
      ...body,
      address,
    };
  }
  return withResolvedSeed(body);
}

async function withResolvedNetwork(body = {}) {
  const runtimeConfig = await networkState.resolveRuntimeConfig(body.network);
  return {
    ...body,
    network: runtimeConfig.network,
  };
}

async function handleRequest(request, response) {
  try {
    const url = new URL(request.url || "/", "http://localhost");
    const { method = "GET" } = request;

    if (pathRequiresAuth(url.pathname) && !isAuthorized(request)) {
      return unauthorized(response);
    }

    if (method === "GET" && url.pathname === "/health") {
      const runtimeConfig = await networkState.resolveRuntimeConfig();
      const networkInfo = await networkState.getNetworkInfo();
      return sendJson(response, 200, {
        ok: true,
        service: "wdk-evm-wallet",
        version: config.version,
        wallet: "evm",
        network: runtimeConfig.network,
        chainId: runtimeConfig.chainId,
        host: config.host,
        dataDir: config.dataDir,
        authRequired: config.authRequired,
        unlockTimeoutSeconds: config.unlockTimeoutSeconds,
        availableNetworks: Object.keys(config.networkProfiles),
        provider: sanitizeProviderUrl(runtimeConfig.providerUrl),
        networkProfiles: sanitizeProfiles(networkInfo.profiles),
        source: "wdk",
      });
    }

    if (method === "POST" && url.pathname === "/v1/evm/seed-phrase/generate") {
      const body = await readJsonBody(request);
      return sendJson(response, 200, {
        ok: true,
        data: service.generateSeedPhrase(body.words ?? 12),
      });
    }

    if (method === "GET" && url.pathname === "/v1/evm/wallets") {
      const activeNetwork = await networkState.getActiveNetwork();
      return sendJson(response, 200, {
        ok: true,
        data: (await vault.listWallets()).map((wallet) => ({
          ...wallet,
          activeNetwork,
        })),
      });
    }

    if (method === "GET" && url.pathname === "/v1/evm/network") {
      return sendJson(response, 200, {
        ok: true,
        data: await networkState.getNetworkInfo(),
      });
    }

    if (method === "POST" && url.pathname === "/v1/evm/network/set") {
      const body = await readJsonBody(request);
      return sendJson(response, 200, {
        ok: true,
        data: await networkState.setActiveNetwork(body),
      });
    }

    if (method === "POST" && url.pathname === "/v1/evm/wallets/get") {
      const body = await readJsonBody(request);
      const activeNetwork = await networkState.getActiveNetwork();
      return sendJson(response, 200, {
        ok: true,
        data: {
          ...(await vault.getWallet(body)),
          activeNetwork,
        },
      });
    }

    if (method === "POST" && url.pathname === "/v1/evm/wallets/create") {
      const body = await withResolvedNetwork(await readJsonBody(request));
      return sendJson(response, 200, {
        ok: true,
        data: await vault.createWallet(body),
      });
    }

    if (method === "POST" && url.pathname === "/v1/evm/wallets/import") {
      const body = await withResolvedNetwork(await readJsonBody(request));
      return sendJson(response, 200, {
        ok: true,
        data: await vault.importWallet(body),
      });
    }

    if (method === "POST" && url.pathname === "/v1/evm/wallets/unlock") {
      const body = await readJsonBody(request);
      return sendJson(response, 200, {
        ok: true,
        data: await vault.unlockWallet(body),
      });
    }

    if (method === "POST" && url.pathname === "/v1/evm/wallets/lock") {
      const body = await readJsonBody(request);
      return sendJson(response, 200, {
        ok: true,
        data: await vault.lockWallet(body),
      });
    }

    if (method === "POST" && url.pathname === "/v1/evm/wallets/reveal-seed") {
      const body = await readJsonBody(request);
      return sendJson(response, 200, {
        ok: true,
        data: await vault.revealSeedPhrase(body),
      });
    }

    if (method === "POST" && url.pathname === "/v1/evm/wallets/change-password") {
      const body = await readJsonBody(request);
      return sendJson(response, 200, {
        ok: true,
        data: await vault.changePassword(body),
      });
    }

    if (method === "POST" && url.pathname === "/v1/evm/address/resolve") {
      const body = await withResolvedNetwork(await withResolvedSeed(await readJsonBody(request)));
      const data = await service.resolveAddress(body);
      return sendJson(response, 200, { ok: true, data });
    }

    if (method === "POST" && url.pathname === "/v1/evm/balance/get") {
      const body = await withResolvedNetwork(await withResolvedSeedOrAddress(await readJsonBody(request)));
      const data = await service.getBalance(body);
      return sendJson(response, 200, { ok: true, data });
    }

    if (method === "POST" && url.pathname === "/v1/evm/token-balance/get") {
      const body = await withResolvedNetwork(await withResolvedSeedOrAddress(await readJsonBody(request)));
      const data = await service.getTokenBalance(body);
      return sendJson(response, 200, { ok: true, data });
    }

    if (method === "POST" && url.pathname === "/v1/evm/token-metadata/get") {
      const body = await withResolvedNetwork(await readJsonBody(request));
      const data = await service.getTokenMetadata(body);
      return sendJson(response, 200, { ok: true, data });
    }

    if (method === "POST" && url.pathname === "/v1/evm/fee-rates/get") {
      const body = await withResolvedNetwork(await readJsonBody(request));
      const data = await service.getFeeRates(body);
      return sendJson(response, 200, { ok: true, data });
    }

    if (method === "POST" && url.pathname === "/v1/evm/transaction/receipt/get") {
      const body = await withResolvedNetwork(await readJsonBody(request));
      const data = await service.getTransactionReceipt(body);
      return sendJson(response, 200, { ok: true, data });
    }

    if (method === "POST" && url.pathname === "/v1/evm/aave/account/get") {
      const body = await withResolvedNetwork(await withResolvedSeedOrAddress(await readJsonBody(request)));
      const data = await service.getAaveAccountData(body);
      return sendJson(response, 200, { ok: true, data });
    }

    if (method === "POST" && url.pathname === "/v1/evm/aave/reserves/get") {
      const body = await withResolvedNetwork(await withResolvedSeedOrAddress(await readJsonBody(request)));
      const data = await service.getAaveReserves(body);
      return sendJson(response, 200, { ok: true, data });
    }

    if (method === "POST" && url.pathname === "/v1/evm/aave/positions/get") {
      const body = await withResolvedNetwork(await withResolvedSeedOrAddress(await readJsonBody(request)));
      const data = await service.getAavePositions(body);
      return sendJson(response, 200, { ok: true, data });
    }

    if (method === "POST" && url.pathname === "/v1/evm/lido/overview/get") {
      const body = await withResolvedNetwork(await withResolvedSeedOrAddress(await readJsonBody(request)));
      const data = await service.getLidoOverview(body);
      return sendJson(response, 200, { ok: true, data });
    }

    if (method === "POST" && url.pathname === "/v1/evm/lido/positions/get") {
      const body = await withResolvedNetwork(await withResolvedSeedOrAddress(await readJsonBody(request)));
      const data = await service.getLidoPositions(body);
      return sendJson(response, 200, { ok: true, data });
    }

    if (method === "POST" && url.pathname === "/v1/evm/lido/withdrawals/get") {
      const body = await withResolvedNetwork(await withResolvedSeedOrAddress(await readJsonBody(request)));
      const data = await service.getLidoWithdrawalRequests(body);
      return sendJson(response, 200, { ok: true, data });
    }

    const aaveOperationMatch = url.pathname.match(
      /^\/v1\/evm\/aave\/(supply|withdraw|borrow|repay)\/(quote|send)$/
    );
    if (method === "POST" && aaveOperationMatch) {
      const operation = aaveOperationMatch[1];
      const action = aaveOperationMatch[2];
      const rawBody = await readJsonBody(request);
      const body =
        action === "quote"
          ? await withResolvedNetwork(await withResolvedSeedOrAddress(rawBody))
          : await withResolvedNetwork(await withResolvedSeed(rawBody));
      const data =
        action === "quote"
          ? await service.quoteAaveOperation({ ...body, operation })
          : await service.sendAaveOperation({ ...body, operation });
      return sendJson(response, 200, { ok: true, data });
    }

    const lidoOperationMatch = url.pathname.match(
      /^\/v1\/evm\/lido\/(stake_eth_for_wsteth|wrap_steth|unwrap_wsteth)\/(quote|send)$/
    );
    if (method === "POST" && lidoOperationMatch) {
      const operation = lidoOperationMatch[1];
      const action = lidoOperationMatch[2];
      const rawBody = await readJsonBody(request);
      const body =
        action === "quote"
          ? await withResolvedNetwork(await withResolvedSeedOrAddress(rawBody))
          : await withResolvedNetwork(await withResolvedSeed(rawBody));
      const data =
        action === "quote"
          ? await service.quoteLidoOperation({ ...body, operation })
          : await service.sendLidoOperation({ ...body, operation });
      return sendJson(response, 200, { ok: true, data });
    }

    const lidoWithdrawalOperationMatch = url.pathname.match(
      /^\/v1\/evm\/lido\/(request_withdrawal_steth|request_withdrawal_wsteth|claim_withdrawal)\/(quote|send)$/
    );
    if (method === "POST" && lidoWithdrawalOperationMatch) {
      const operation = lidoWithdrawalOperationMatch[1];
      const action = lidoWithdrawalOperationMatch[2];
      const rawBody = await readJsonBody(request);
      const body =
        action === "quote"
          ? await withResolvedNetwork(await withResolvedSeedOrAddress(rawBody))
          : await withResolvedNetwork(await withResolvedSeed(rawBody));
      const data =
        action === "quote"
          ? await service.quoteLidoWithdrawalOperation({ ...body, operation })
          : await service.sendLidoWithdrawalOperation({ ...body, operation });
      return sendJson(response, 200, { ok: true, data });
    }

    if (method === "POST" && url.pathname === "/v1/evm/swap/quote") {
      const body = await withResolvedNetwork(await withResolvedSeedOrAddress(await readJsonBody(request)));
      const data = await service.quoteSwap(body);
      return sendJson(response, 200, { ok: true, data });
    }

    if (method === "POST" && url.pathname === "/v1/evm/swap/send") {
      const body = await withResolvedNetwork(await withResolvedSeed(await readJsonBody(request)));
      const data = await service.swap(body);
      return sendJson(response, 200, { ok: true, data });
    }

    if (method === "POST" && url.pathname === "/v1/evm/lifi/quote") {
      const body = await withResolvedNetwork(await withResolvedSeedOrAddress(await readJsonBody(request)));
      const data = await service.quoteLifiSwap(body);
      return sendJson(response, 200, { ok: true, data });
    }

    if (method === "POST" && url.pathname === "/v1/evm/lifi/send") {
      const body = await withResolvedNetwork(await withResolvedSeed(await readJsonBody(request)));
      const data = await service.sendLifiSwap(body);
      return sendJson(response, 200, { ok: true, data });
    }

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

    if (method === "POST" && url.pathname === "/v1/evm/transfer/quote") {
      const body = await withResolvedNetwork(await withResolvedSeed(await readJsonBody(request)));
      const data = await service.quoteNativeTransfer(body);
      return sendJson(response, 200, { ok: true, data });
    }

    if (method === "POST" && url.pathname === "/v1/evm/transfer/send") {
      const body = await withResolvedNetwork(await withResolvedSeed(await readJsonBody(request)));
      const data = await service.sendNativeTransfer(body);
      return sendJson(response, 200, { ok: true, data });
    }

    if (method === "POST" && url.pathname === "/v1/evm/token-transfer/quote") {
      const body = await withResolvedNetwork(await withResolvedSeed(await readJsonBody(request)));
      const data = await service.quoteTokenTransfer(body);
      return sendJson(response, 200, { ok: true, data });
    }

    if (method === "POST" && url.pathname === "/v1/evm/token-transfer/send") {
      const body = await withResolvedNetwork(await withResolvedSeed(await readJsonBody(request)));
      const data = await service.sendTokenTransfer(body);
      return sendJson(response, 200, { ok: true, data });
    }

    if (method === "POST" && url.pathname === "/v1/evm/x402/exact/sign") {
      const body = await withResolvedNetwork(await withResolvedSeed(await readJsonBody(request)));
      const data = await service.signX402ExactTypedData(body);
      return sendJson(response, 200, { ok: true, data });
    }

    return notFound(response);
  } catch (error) {
    const shaped = toErrorResponse(error, new URL(request.url || "/", "http://localhost").pathname, 400);
    return sendJson(response, shaped.statusCode, shaped.payload);
  }
}

const server = createServer((request, response) => {
  handleRequest(request, response).catch((error) => {
    const shaped = toErrorResponse(error, new URL(request.url || "/", "http://localhost").pathname, 500);
    sendJson(response, shaped.statusCode, shaped.payload);
  });
});

server.listen(config.port, config.host, () => {
  console.log(
    `wdk-evm-wallet listening on ${config.host}:${config.port} (${config.network})`
  );
});
