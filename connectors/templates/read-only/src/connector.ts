import { readFileSync } from "node:fs";

import {
  defineReadOnlyConnector,
  type ConnectorManifest,
  type JsonObject,
} from "@agentlayer.tech/connector-sdk";

const manifest = JSON.parse(
  readFileSync(new URL("../connector.json", import.meta.url), "utf8")
) as ConnectorManifest;

function numberOrNull(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function normalizePool(value: unknown): JsonObject | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const pool = value as Record<string, unknown>;
  if (typeof pool.id !== "string" || typeof pool.symbol !== "string") return null;
  return {
    id: pool.id,
    symbol: pool.symbol,
    apy: numberOrNull(pool.apy),
    tvl_usd: numberOrNull(pool.tvl_usd),
  };
}

async function getPools(arguments_: JsonObject): Promise<JsonObject> {
  const rawBaseUrl = process.env.UPSTREAM_API_URL ?? "https://api.example.com";
  const baseUrl = new URL(rawBaseUrl);
  if (
    baseUrl.protocol !== "https:" ||
    !manifest.permissions.network_hosts.includes(baseUrl.hostname)
  ) {
    throw new Error("UPSTREAM_API_URL must be HTTPS and declared in permissions.network_hosts.");
  }
  const url = new URL("/v1/pools", baseUrl);
  url.searchParams.set("chain", String(arguments_.chain));
  url.searchParams.set("limit", String(arguments_.limit ?? 20));
  const response = await fetch(url, {
    headers: { accept: "application/json" },
    redirect: "error",
    signal: AbortSignal.timeout(5000),
  });
  if (!response.ok) throw new Error(`Upstream returned HTTP ${response.status}.`);
  const payload: unknown = await response.json();
  const rawPools =
    payload && typeof payload === "object" && !Array.isArray(payload)
      ? (payload as Record<string, unknown>).pools
      : null;
  if (!Array.isArray(rawPools)) throw new Error("Upstream response is missing pools.");
  const limit = Number(arguments_.limit ?? 20);
  return { pools: rawPools.map(normalizePool).filter((pool) => pool !== null).slice(0, limit) };
}

export const connector = defineReadOnlyConnector({
  manifest,
  handlers: { get_pools: getPools },
  responseTtlSeconds: 60,
});
