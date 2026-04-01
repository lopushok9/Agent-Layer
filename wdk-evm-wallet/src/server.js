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
  });
  return {
    ...body,
    seedPhrase: resolved.seedPhrase,
    walletId: resolved.walletId ?? body.walletId ?? null,
    credentialSource: resolved.source,
    unlockExpiresAt: resolved.unlockExpiresAt ?? null,
  };
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
        version: "0.1.0",
        wallet: "evm",
        network: runtimeConfig.network,
        chainId: runtimeConfig.chainId,
        host: config.host,
        dataDir: config.dataDir,
        authRequired: config.authRequired,
        unlockTimeoutSeconds: config.unlockTimeoutSeconds,
        availableNetworks: Object.keys(config.networkProfiles),
        provider: runtimeConfig.providerUrl,
        networkProfiles: networkInfo.profiles,
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
      const body = await withResolvedNetwork(await withResolvedSeed(await readJsonBody(request)));
      const data = await service.getBalance(body);
      return sendJson(response, 200, { ok: true, data });
    }

    if (method === "POST" && url.pathname === "/v1/evm/token-balance/get") {
      const body = await withResolvedNetwork(await withResolvedSeed(await readJsonBody(request)));
      const data = await service.getTokenBalance(body);
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

    return notFound(response);
  } catch (error) {
    return sendJson(response, 400, {
      ok: false,
      error: error instanceof Error ? error.message : String(error),
    });
  }
}

const server = createServer((request, response) => {
  handleRequest(request, response).catch((error) => {
    sendJson(response, 500, {
      ok: false,
      error: error instanceof Error ? error.message : String(error),
    });
  });
});

server.listen(config.port, config.host, () => {
  console.log(
    `wdk-evm-wallet listening on ${config.host}:${config.port} (${config.network})`
  );
});
