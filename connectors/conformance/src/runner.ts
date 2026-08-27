import { readFile } from "node:fs/promises";

import { createRequire } from "node:module";
import { Ajv2020, type ValidateFunction } from "ajv/dist/2020.js";
import type { FormatsPlugin } from "ajv-formats";

import type {
  ConformanceCheck,
  ConformanceFixture,
  ConformanceOptions,
  ConformanceReport,
} from "./types.js";

const require = createRequire(import.meta.url);
const addFormats = require("ajv-formats") as FormatsPlugin;
const MAX_RESPONSE_TTL_MS = 300_000;
const RESERVED_WRITE_RESULT_KEYS = new Set([
  "approval_token",
  "broadcast_request",
  "evm_transaction_intent",
  "payment_intent",
  "raw_transaction",
  "signed_transaction",
  "signing_request",
  "solana_transaction_intent",
  "transaction_intent",
]);

function object(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

async function defaultManifestSchema(): Promise<Record<string, unknown>> {
  const url = new URL("../spec/connector-manifest.schema.json", import.meta.url);
  return JSON.parse(await readFile(url, "utf8")) as Record<string, unknown>;
}

function buildAjv(): Ajv2020 {
  const ajv = new Ajv2020({ allErrors: true, strict: true });
  addFormats(ajv);
  return ajv;
}

function identity(manifest: Record<string, unknown>): Record<string, string> {
  return {
    id: String(manifest.id),
    version: String(manifest.version),
    ...(manifest.artifact_digest ? { artifact_digest: String(manifest.artifact_digest) } : {}),
  };
}

function assertNoWritePayload(value: unknown): void {
  const pending: unknown[] = [value];
  while (pending.length > 0) {
    const current = pending.pop();
    if (Array.isArray(current)) {
      pending.push(...current);
    } else if (current && typeof current === "object") {
      for (const [key, item] of Object.entries(current)) {
        if (RESERVED_WRITE_RESULT_KEYS.has(key.toLowerCase())) {
          throw new Error(`Read result contains reserved write field: ${key}.`);
        }
        pending.push(item);
      }
    }
  }
}

function checkResponseBinding(
  payload: unknown,
  manifest: Record<string, unknown>,
  requestId: string,
  toolName: string,
  validateOutput: ValidateFunction
): void {
  const response = object(payload);
  if (!response) throw new Error("Response root must be an object.");
  if (response.protocol_version !== 1 || response.request_id !== requestId) {
    throw new Error("Response protocol/request binding does not match.");
  }
  const responseIdentity = object(response.connector);
  const expectedIdentity = identity(manifest);
  if (
    !responseIdentity ||
    responseIdentity.id !== expectedIdentity.id ||
    responseIdentity.version !== expectedIdentity.version ||
    responseIdentity.artifact_digest !== expectedIdentity.artifact_digest
  ) {
    throw new Error("Response connector identity does not match.");
  }
  if (response.tool !== toolName || response.kind !== "read_result") {
    throw new Error("Response tool or kind does not match the read request.");
  }
  const expiresAt = Date.parse(String(response.expires_at ?? ""));
  const remaining = expiresAt - Date.now();
  if (!Number.isFinite(expiresAt) || remaining <= 0 || remaining > MAX_RESPONSE_TTL_MS) {
    throw new Error("Response expiry must be in the next 300 seconds.");
  }
  assertNoWritePayload(response.result);
  if (!validateOutput(response.result)) {
    throw new Error("Response result does not match the declared output_schema.");
  }
}

async function post(
  fetchImpl: typeof fetch,
  endpoint: string,
  payload: Record<string, unknown>,
  timeoutMs: number
): Promise<Response> {
  return fetchImpl(`${endpoint}/invoke`, {
    method: "POST",
    headers: { accept: "application/json", "content-type": "application/json" },
    body: JSON.stringify(payload),
    redirect: "error",
    signal: AbortSignal.timeout(timeoutMs),
  });
}

export async function runConformance(options: ConformanceOptions): Promise<ConformanceReport> {
  const endpoint = String(
    options.endpoint ?? object(options.manifest.transport)?.url ?? ""
  ).replace(/\/$/, "");
  if (!/^https?:\/\//.test(endpoint)) throw new Error("A connector endpoint URL is required.");
  const timeoutMs = options.timeoutMs ?? 10_000;
  const fetchImpl = options.fetchImpl ?? fetch;
  const checks: ConformanceCheck[] = [];
  const runCheck = async (name: string, callback: () => void | Promise<void>): Promise<void> => {
    try {
      await callback();
      checks.push({ name, ok: true });
    } catch (error) {
      checks.push({ name, ok: false, error: String(error instanceof Error ? error.message : error) });
    }
  };

  const ajv = buildAjv();
  const manifestSchema = options.manifestSchema ?? (await defaultManifestSchema());
  const validateManifest = ajv.compile(manifestSchema);
  await runCheck("manifest_schema", () => {
    if (!validateManifest(options.manifest)) throw new Error("Manifest does not match Protocol v1 schema.");
  });

  const tools = Array.isArray(options.manifest.tools)
    ? options.manifest.tools.map(object).filter((tool): tool is Record<string, unknown> => tool !== null)
    : [];
  const readTools = tools.filter((tool) => tool.read_only === true);
  await runCheck("fixture_coverage", () => {
    const declared = new Set(readTools.map((tool) => String(tool.name)));
    for (const name of declared) {
      if (!object(options.fixture.tools?.[name])?.arguments) {
        throw new Error(`Missing fixture arguments for ${name}.`);
      }
    }
    for (const name of Object.keys(options.fixture.tools ?? {})) {
      if (!declared.has(name)) throw new Error(`Fixture names an undeclared read tool: ${name}.`);
    }
  });

  await runCheck("healthz", async () => {
    const response = await fetchImpl(`${endpoint}/healthz`, {
      headers: { accept: "application/json" },
      redirect: "error",
      signal: AbortSignal.timeout(timeoutMs),
    });
    if (response.status !== 200) throw new Error(`Health endpoint returned HTTP ${response.status}.`);
    const payload = object(await response.json());
    const connector = object(payload?.connector);
    if (
      payload?.ok !== true ||
      connector?.id !== options.manifest.id ||
      connector?.version !== options.manifest.version
    ) {
      throw new Error("Health endpoint identity does not match the manifest.");
    }
  });

  for (const tool of readTools) {
    const toolName = String(tool.name);
    const fixture = options.fixture.tools[toolName];
    if (!fixture) continue;
    let validateInput: ValidateFunction;
    let validateOutput: ValidateFunction;
    try {
      validateInput = ajv.compile(tool.input_schema as Record<string, unknown>);
      validateOutput = ajv.compile(tool.output_schema as Record<string, unknown>);
    } catch (error) {
      checks.push({ name: `tool:${toolName}:schemas`, ok: false, error: String(error) });
      continue;
    }
    await runCheck(`tool:${toolName}:invoke`, async () => {
      if (!validateInput(fixture.arguments)) throw new Error("Fixture arguments violate input_schema.");
      const requestId = `conformance-${toolName}-${Date.now()}`;
      const response = await post(
        fetchImpl,
        endpoint,
        {
          protocol_version: 1,
          request_id: requestId,
          connector: identity(options.manifest),
          tool: toolName,
          arguments: fixture.arguments,
          context: {},
        },
        timeoutMs
      );
      if (response.status !== 200) throw new Error(`Invoke returned HTTP ${response.status}.`);
      checkResponseBinding(await response.json(), options.manifest, requestId, toolName, validateOutput);
    });
  }

  await runCheck("reject_wrong_identity", async () => {
    const response = await post(
      fetchImpl,
      endpoint,
      {
        protocol_version: 1,
        request_id: `conformance-wrong-id-${Date.now()}`,
        connector: { id: "com.agentlayer.conformance.invalid", version: "0.0.0" },
        tool: String(readTools[0]?.name ?? "unknown"),
        arguments: options.fixture.tools[String(readTools[0]?.name ?? "")]?.arguments ?? {},
        context: {},
      },
      timeoutMs
    );
    if (response.status >= 200 && response.status < 300) {
      throw new Error("Connector accepted a request for a different identity.");
    }
  });

  await runCheck("reject_unknown_tool", async () => {
    const response = await post(
      fetchImpl,
      endpoint,
      {
        protocol_version: 1,
        request_id: `conformance-unknown-tool-${Date.now()}`,
        connector: identity(options.manifest),
        tool: "__conformance_unknown_tool__",
        arguments: {},
        context: {},
      },
      timeoutMs
    );
    if (response.status >= 200 && response.status < 300) {
      throw new Error("Connector accepted an undeclared tool.");
    }
  });

  return {
    ok: checks.every((check) => check.ok),
    connector_id: String(options.manifest.id ?? ""),
    connector_version: String(options.manifest.version ?? ""),
    endpoint,
    checks,
  };
}

export function assertFixture(value: unknown): asserts value is ConformanceFixture {
  const fixture = object(value);
  if (fixture?.schema_version !== 1 || !object(fixture.tools)) {
    throw new Error("Conformance fixture must use schema_version 1 and contain a tools object.");
  }
}
