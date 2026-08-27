import { createRequire } from "node:module";

import { Ajv, type ValidateFunction } from "ajv";
import type { FormatsPlugin } from "ajv-formats";

import { ConnectorSdkError } from "./errors.js";
import type {
  ConnectorInvocationRequest,
  ConnectorManifest,
  ConnectorReadResponse,
  ConnectorToolManifest,
  JsonValue,
  ReadOnlyConnector,
  ReadOnlyConnectorDefinition,
} from "./types.js";

const TOOL_NAME_PATTERN = /^[a-z][a-z0-9_]{0,63}$/;
const MAX_RESPONSE_BYTES = 1024 * 1024;
const MAX_RESPONSE_TTL_SECONDS = 300;
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
const READ_ONLY_TRUST = new Set([
  "community_read_only",
  "verified_read_only",
  "local_development",
]);
const require = createRequire(import.meta.url);
const addFormats = require("ajv-formats") as FormatsPlugin;

interface CompiledTool {
  manifest: ConnectorToolManifest;
  validateInput: ValidateFunction;
  validateOutput: ValidateFunction;
}

function fail(code: string, message: string, statusCode = 400): never {
  throw new ConnectorSdkError(code, message, statusCode);
}

function assertJsonValue(value: unknown, path = "result"): asserts value is JsonValue {
  if (value === null || ["string", "number", "boolean"].includes(typeof value)) {
    if (typeof value === "number" && !Number.isFinite(value)) {
      fail("invalid_json", `${path} contains a non-finite number.`, 500);
    }
    return;
  }
  if (Array.isArray(value)) {
    value.forEach((item, index) => assertJsonValue(item, `${path}[${index}]`));
    return;
  }
  if (typeof value === "object") {
    for (const [key, item] of Object.entries(value)) {
      if (RESERVED_WRITE_RESULT_KEYS.has(key.toLowerCase())) {
        fail("write_not_supported", `${path} contains reserved write field: ${key}.`, 500);
      }
      assertJsonValue(item, `${path}.${key}`);
    }
    return;
  }
  fail("invalid_json", `${path} is not JSON-serializable.`, 500);
}

function assertManifest(definition: ReadOnlyConnectorDefinition): void {
  const { manifest, handlers } = definition;
  if (manifest.schema_version !== 1 || manifest.agentlayer?.protocol_version !== 1) {
    fail("invalid_manifest", "Connector must use manifest and protocol version 1.");
  }
  if (!READ_ONLY_TRUST.has(manifest.trust)) {
    fail("write_not_supported", "The TypeScript SDK currently accepts read-only connectors only.");
  }
  if (manifest.permissions?.transaction_intents !== false) {
    fail("write_not_supported", "Read-only connectors must disable transaction_intents.");
  }
  if (!Array.isArray(manifest.tools) || manifest.tools.length === 0) {
    fail("invalid_manifest", "Connector manifest must declare at least one tool.");
  }
  const names = new Set<string>();
  for (const tool of manifest.tools) {
    if (!TOOL_NAME_PATTERN.test(tool.name)) {
      fail("invalid_manifest", `Invalid connector tool name: ${tool.name}.`);
    }
    if (names.has(tool.name)) {
      fail("invalid_manifest", `Duplicate connector tool name: ${tool.name}.`);
    }
    names.add(tool.name);
    if (tool.read_only !== true) {
      fail("write_not_supported", `Tool ${tool.name} is not read-only.`);
    }
    if (typeof handlers[tool.name] !== "function") {
      fail("missing_handler", `Missing handler for connector tool: ${tool.name}.`);
    }
  }
  for (const handlerName of Object.keys(handlers)) {
    if (!names.has(handlerName)) {
      fail("unknown_handler", `Handler is not declared in the manifest: ${handlerName}.`);
    }
  }
}

function assertRequestIdentity(
  request: ConnectorInvocationRequest,
  manifest: ConnectorManifest
): void {
  if (request.protocol_version !== 1) {
    fail("protocol_mismatch", "Unsupported connector protocol version.");
  }
  if (typeof request.request_id !== "string" || request.request_id.length < 8) {
    fail("invalid_request", "request_id is required.");
  }
  if (
    request.connector?.id !== manifest.id ||
    request.connector?.version !== manifest.version ||
    request.connector?.artifact_digest !== manifest.artifact_digest
  ) {
    fail("identity_mismatch", "Connector request identity does not match this deployment.", 409);
  }
  if (!request.arguments || Array.isArray(request.arguments) || typeof request.arguments !== "object") {
    fail("invalid_request", "Connector arguments must be an object.");
  }
  if (!request.context || Array.isArray(request.context) || typeof request.context !== "object") {
    fail("invalid_request", "Connector context must be an object.");
  }
  if (request.expires_at) {
    const expiry = Date.parse(request.expires_at);
    if (!Number.isFinite(expiry) || expiry <= Date.now()) {
      fail("expired_request", "Connector request is expired.");
    }
  }
}

export function defineReadOnlyConnector(
  definition: ReadOnlyConnectorDefinition
): ReadOnlyConnector {
  assertManifest(definition);
  const ttlSeconds = definition.responseTtlSeconds ?? 60;
  if (!Number.isInteger(ttlSeconds) || ttlSeconds < 1 || ttlSeconds > MAX_RESPONSE_TTL_SECONDS) {
    fail("invalid_ttl", `responseTtlSeconds must be between 1 and ${MAX_RESPONSE_TTL_SECONDS}.`);
  }

  const ajv = new Ajv({ allErrors: true, strict: true });
  addFormats(ajv);
  const tools = new Map<string, CompiledTool>();
  try {
    for (const tool of definition.manifest.tools) {
      tools.set(tool.name, {
        manifest: tool,
        validateInput: ajv.compile(tool.input_schema),
        validateOutput: ajv.compile(tool.output_schema),
      });
    }
  } catch (error) {
    fail("invalid_schema", `Connector tool schema is invalid: ${String(error)}`);
  }

  const manifest = structuredClone(definition.manifest);
  return Object.freeze({
    manifest: Object.freeze(manifest),
    async invoke(request: ConnectorInvocationRequest): Promise<ConnectorReadResponse> {
      assertRequestIdentity(request, manifest);
      const tool = tools.get(request.tool);
      if (!tool) {
        fail("unknown_tool", `Connector tool is not declared: ${request.tool}.`, 404);
      }
      if (!tool.validateInput(request.arguments)) {
        fail("invalid_arguments", `Arguments do not match the schema for ${request.tool}.`);
      }
      const result: unknown = await definition.handlers[request.tool]!(
        request.arguments,
        Object.freeze({ ...request.context })
      );
      assertJsonValue(result);
      if (!tool.validateOutput(result)) {
        fail("invalid_result", `Result does not match the schema for ${request.tool}.`, 500);
      }
      const connector = {
        id: manifest.id,
        version: manifest.version,
        ...(manifest.artifact_digest ? { artifact_digest: manifest.artifact_digest } : {}),
      };
      const response: ConnectorReadResponse = {
        protocol_version: 1,
        request_id: request.request_id,
        connector,
        tool: request.tool,
        kind: "read_result",
        result,
        expires_at: new Date(Date.now() + ttlSeconds * 1000).toISOString(),
      };
      if (Buffer.byteLength(JSON.stringify(response)) > MAX_RESPONSE_BYTES) {
        fail("response_too_large", "Connector response exceeds the 1 MiB protocol limit.", 500);
      }
      return response;
    },
  });
}
