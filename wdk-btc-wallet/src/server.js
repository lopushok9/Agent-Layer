import "dotenv/config";

import crypto from "node:crypto";
import { createServer } from "node:http";

import { loadConfig } from "./config.js";
import { jsonSafe, readJsonBody, sendJson } from "./json.js";
import { LocalBtcVault } from "./local_vault.js";
import { BtcNetworkState } from "./network_state.js";
import { WdkBtcWalletService } from "./wdk_btc_wallet.js";

const config = loadConfig();
const service = new WdkBtcWalletService(config);
const vault = new LocalBtcVault(config);
const networkState = new BtcNetworkState(config);

function notFound(response) {
  sendJson(response, 404, { ok: false, error: "Not Found" });
}

function unauthorized(response) {
  response.setHeader("WWW-Authenticate", 'Bearer realm="wdk-btc-wallet"');
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
        service: "wdk-btc-wallet",
        version: "0.1.0",
        wallet: "bitcoin",
        network: runtimeConfig.network,
        bip: config.bip,
        host: config.host,
        dataDir: config.dataDir,
        authRequired: config.authRequired,
        unlockTimeoutSeconds: config.unlockTimeoutSeconds,
        availableNetworks: Object.keys(config.networkProfiles),
        electrum: {
          protocol: runtimeConfig.electrumProtocol,
          host: runtimeConfig.electrumHost,
          port: runtimeConfig.electrumPort,
        },
        networkProfiles: networkInfo.profiles,
        source: "wdk",
      });
    }

    if (method === "POST" && url.pathname === "/v1/btc/seed-phrase/generate") {
      const body = await readJsonBody(request);
      return sendJson(response, 200, {
        ok: true,
        data: service.generateSeedPhrase(body.words ?? 12),
      });
    }

    if (method === "GET" && url.pathname === "/v1/btc/wallets") {
      const activeNetwork = await networkState.getActiveNetwork();
      return sendJson(response, 200, {
        ok: true,
        data: (await vault.listWallets()).map((wallet) => ({
          ...wallet,
          activeNetwork,
        })),
      });
    }

    if (method === "GET" && url.pathname === "/v1/btc/network") {
      return sendJson(response, 200, {
        ok: true,
        data: await networkState.getNetworkInfo(),
      });
    }

    if (method === "POST" && url.pathname === "/v1/btc/network/set") {
      const body = await readJsonBody(request);
      return sendJson(response, 200, {
        ok: true,
        data: await networkState.setActiveNetwork(body),
      });
    }

    if (method === "POST" && url.pathname === "/v1/btc/wallets/get") {
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

    if (method === "POST" && url.pathname === "/v1/btc/wallets/create") {
      const body = await withResolvedNetwork(await readJsonBody(request));
      return sendJson(response, 200, {
        ok: true,
        data: await vault.createWallet(body),
      });
    }

    if (method === "POST" && url.pathname === "/v1/btc/wallets/import") {
      const body = await withResolvedNetwork(await readJsonBody(request));
      return sendJson(response, 200, {
        ok: true,
        data: await vault.importWallet(body),
      });
    }

    if (method === "POST" && url.pathname === "/v1/btc/wallets/unlock") {
      const body = await readJsonBody(request);
      return sendJson(response, 200, {
        ok: true,
        data: await vault.unlockWallet(body),
      });
    }

    if (method === "POST" && url.pathname === "/v1/btc/wallets/lock") {
      const body = await readJsonBody(request);
      return sendJson(response, 200, {
        ok: true,
        data: await vault.lockWallet(body),
      });
    }

    if (method === "POST" && url.pathname === "/v1/btc/wallets/reveal-seed") {
      const body = await readJsonBody(request);
      return sendJson(response, 200, {
        ok: true,
        data: await vault.revealSeedPhrase(body),
      });
    }

    if (method === "POST" && url.pathname === "/v1/btc/wallets/change-password") {
      const body = await readJsonBody(request);
      return sendJson(response, 200, {
        ok: true,
        data: await vault.changePassword(body),
      });
    }

    if (method === "POST" && url.pathname === "/v1/btc/address/resolve") {
      const body = await withResolvedNetwork(await withResolvedSeed(await readJsonBody(request)));
      const data = await service.resolveAddress(body);
      return sendJson(response, 200, { ok: true, data });
    }

    if (method === "POST" && url.pathname === "/v1/btc/balance/get") {
      const body = await withResolvedNetwork(await withResolvedSeed(await readJsonBody(request)));
      const data = await service.getBalance(body);
      return sendJson(response, 200, { ok: true, data });
    }

    if (method === "POST" && url.pathname === "/v1/btc/transfers/get") {
      const body = await withResolvedNetwork(await withResolvedSeed(await readJsonBody(request)));
      const data = await service.getTransfers(body);
      return sendJson(response, 200, { ok: true, data });
    }

    if (method === "POST" && url.pathname === "/v1/btc/max-spendable/get") {
      const body = await withResolvedNetwork(await withResolvedSeed(await readJsonBody(request)));
      const data = await service.getMaxSpendable(body);
      return sendJson(response, 200, { ok: true, data });
    }

    if (method === "POST" && url.pathname === "/v1/btc/fee-rates/get") {
      const body = await withResolvedNetwork(await readJsonBody(request));
      const data = await service.getFeeRates(body);
      return sendJson(response, 200, { ok: true, data });
    }

    if (method === "POST" && url.pathname === "/v1/btc/transfer/quote") {
      const body = await withResolvedNetwork(await withResolvedSeed(await readJsonBody(request)));
      const data = await service.quoteTransfer(body);
      return sendJson(response, 200, { ok: true, data: jsonSafe(data) });
    }

    if (method === "POST" && url.pathname === "/v1/btc/transfer/send") {
      const body = await withResolvedNetwork(await withResolvedSeed(await readJsonBody(request)));
      const data = await service.sendTransfer(body);
      return sendJson(response, 200, { ok: true, data: jsonSafe(data) });
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
    `wdk-btc-wallet listening on ${config.host}:${config.port} (${config.network}, bip${config.bip})`
  );
});
