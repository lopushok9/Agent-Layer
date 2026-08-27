import { readFileSync } from "node:fs";

import {
  ConnectorSdkError,
  defineReadOnlyConnector,
  type ConnectorManifest,
  type JsonObject,
} from "@agentlayer.tech/connector-sdk";

const manifest = JSON.parse(
  readFileSync(new URL("../connector.json", import.meta.url), "utf8")
) as ConnectorManifest;
const UPSTREAM_ORIGIN = "https://api.exchange.coinbase.com";
const MAX_UPSTREAM_BYTES = 256 * 1024;
const ASSET_PATTERN = /^[A-Z0-9]{2,12}$/;

function assetCode(value: unknown, field: string): string {
  const normalized = String(value ?? "").trim().toUpperCase();
  if (!ASSET_PATTERN.test(normalized)) {
    throw new ConnectorSdkError("invalid_arguments", `${field} must be a 2-12 character asset code.`);
  }
  return normalized;
}

function requiredString(value: unknown, field: string, maxLength = 120): string {
  if (typeof value !== "string" || value.length === 0 || value.length > maxLength) {
    throw new ConnectorSdkError("invalid_upstream", `Upstream ${field} is invalid.`, 502);
  }
  return value;
}

function optionalString(value: unknown, maxLength = 80): string | null {
  return typeof value === "string" && value.length > 0 && value.length <= maxLength ? value : null;
}

async function readObject(response: Response): Promise<Record<string, unknown>> {
  const contentLength = Number(response.headers.get("content-length") ?? 0);
  if (Number.isFinite(contentLength) && contentLength > MAX_UPSTREAM_BYTES) {
    throw new ConnectorSdkError("upstream_too_large", "Upstream response exceeds the size limit.", 502);
  }
  if (!response.body) {
    throw new ConnectorSdkError("invalid_upstream", "Upstream response body is missing.", 502);
  }
  const reader = response.body.getReader();
  const chunks: Uint8Array[] = [];
  let size = 0;
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    size += value.byteLength;
    if (size > MAX_UPSTREAM_BYTES) {
      await reader.cancel();
      throw new ConnectorSdkError("upstream_too_large", "Upstream response exceeds the size limit.", 502);
    }
    chunks.push(value);
  }
  let payload: unknown;
  try {
    payload = JSON.parse(Buffer.concat(chunks).toString("utf8"));
  } catch {
    throw new ConnectorSdkError("invalid_upstream", "Upstream response is not valid JSON.", 502);
  }
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
    throw new ConnectorSdkError("invalid_upstream", "Upstream response root is invalid.", 502);
  }
  return payload as Record<string, unknown>;
}

async function fetchObject(
  path: string,
  fetchImpl: typeof fetch
): Promise<Record<string, unknown>> {
  const url = new URL(path, UPSTREAM_ORIGIN);
  if (url.origin !== UPSTREAM_ORIGIN || !manifest.permissions.network_hosts.includes(url.hostname)) {
    throw new ConnectorSdkError("upstream_not_allowed", "Upstream host is not allowlisted.", 500);
  }
  const response = await fetchImpl(url, {
    headers: {
      accept: "application/json",
      "cache-control": "no-cache",
      "user-agent": "AgentLayer-Reference-Connector/0.1",
    },
    redirect: "error",
    signal: AbortSignal.timeout(5000),
  });
  if (!response.ok) {
    throw new ConnectorSdkError("upstream_http_error", `Upstream returned HTTP ${response.status}.`, 502);
  }
  return readObject(response);
}

export function createCryptoDataConnector(fetchImpl: typeof fetch = fetch) {
  return defineReadOnlyConnector({
    manifest,
    responseTtlSeconds: 30,
    handlers: {
      async get_spot_price(arguments_: JsonObject): Promise<JsonObject> {
        const base = assetCode(arguments_.base, "base");
        const quote = assetCode(arguments_.quote, "quote");
        const productId = `${base}-${quote}`;
        const ticker = await fetchObject(`/products/${encodeURIComponent(productId)}/ticker`, fetchImpl);
        return {
          product_id: productId,
          base_currency: base,
          quote_currency: quote,
          price: requiredString(ticker.price, "price", 80),
          bid: requiredString(ticker.bid, "bid", 80),
          ask: requiredString(ticker.ask, "ask", 80),
          last_size: requiredString(ticker.size, "size", 80),
          volume_24h: requiredString(ticker.volume, "volume", 80),
          observed_at: requiredString(ticker.time, "time", 64),
          source: "coinbase_exchange",
        };
      },
      async get_asset_metadata(arguments_: JsonObject): Promise<JsonObject> {
        const asset = assetCode(arguments_.asset, "asset");
        const currency = await fetchObject(`/currencies/${encodeURIComponent(asset)}`, fetchImpl);
        const details =
          currency.details && typeof currency.details === "object" && !Array.isArray(currency.details)
            ? (currency.details as Record<string, unknown>)
            : {};
        return {
          asset: requiredString(currency.id, "id", 12),
          name: requiredString(currency.name, "name"),
          status: requiredString(currency.status, "status", 40),
          type: optionalString(details.type, 40),
          min_size: requiredString(currency.min_size, "min_size", 80),
          max_precision: requiredString(currency.max_precision, "max_precision", 80),
          default_network: optionalString(currency.default_network, 80),
          source: "coinbase_exchange",
        };
      },
    },
  });
}

export const connector = createCryptoDataConnector();
