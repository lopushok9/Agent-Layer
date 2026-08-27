import crypto from "node:crypto";

export const MAX_GATEWAY_BODY_BYTES = 1024 * 1024;
export const INVOCATION_TTL_SECONDS = 30;

const CONNECTOR_ID_PATTERN = /^[a-z0-9]+(?:[._-][a-z0-9]+)+$/;
const SEMVER_PATTERN = /^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$/;
const TOOL_PATTERN = /^[a-z][a-z0-9_]{1,63}$/;
const DIGEST_PATTERN = /^sha256:[0-9a-f]{64}$/;

export class GatewayError extends Error {
  constructor(message, { status = 400, code = "gateway_invalid_request" } = {}) {
    super(message);
    this.name = "GatewayError";
    this.status = status;
    this.code = code;
  }
}

function isObject(value) {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function canonicalValue(value) {
  if (Array.isArray(value)) return value.map(canonicalValue);
  if (!isObject(value)) return value;
  return Object.fromEntries(
    Object.keys(value)
      .sort()
      .map((key) => [key, canonicalValue(value[key])]),
  );
}

export function canonicalJson(value) {
  return JSON.stringify(canonicalValue(value));
}

export function routeKey(connectorId, version) {
  return `${connectorId}@${version}`;
}

function validateHttpsEndpoint(value) {
  let parsed;
  try {
    parsed = new URL(value);
  } catch {
    throw new GatewayError("Connector route endpoint must be a valid URL.");
  }
  if (
    parsed.protocol !== "https:" ||
    !parsed.hostname ||
    parsed.username ||
    parsed.password ||
    parsed.hash
  ) {
    throw new GatewayError("Connector route endpoint must be HTTPS without credentials or fragments.");
  }
  return parsed.toString();
}

function validateRoute(rawRoute, key) {
  if (!isObject(rawRoute)) throw new GatewayError(`Connector route ${key} must be an object.`);
  const connectorId = String(rawRoute.connector_id || "");
  const version = String(rawRoute.version || "");
  if (!CONNECTOR_ID_PATTERN.test(connectorId) || !SEMVER_PATTERN.test(version)) {
    throw new GatewayError(`Connector route ${key} has an invalid identity.`);
  }
  if (routeKey(connectorId, version) !== key) {
    throw new GatewayError(`Connector route ${key} does not match its identity.`);
  }
  if (!DIGEST_PATTERN.test(String(rawRoute.artifact_digest || ""))) {
    throw new GatewayError(`Connector route ${key} has an invalid artifact digest.`);
  }
  if (!["verified_read_only", "verified_write"].includes(rawRoute.trust)) {
    throw new GatewayError(`Connector route ${key} has an unsupported trust class.`);
  }
  if (typeof rawRoute.enabled !== "boolean") {
    throw new GatewayError(`Connector route ${key} must declare enabled.`);
  }
  const tools = rawRoute.tools;
  if (!isObject(tools) || Object.keys(tools).length === 0) {
    throw new GatewayError(`Connector route ${key} must declare tools.`);
  }
  const normalizedTools = {};
  for (const [toolName, tool] of Object.entries(tools)) {
    if (!TOOL_PATTERN.test(toolName) || !isObject(tool) || typeof tool.read_only !== "boolean") {
      throw new GatewayError(`Connector route ${key} has an invalid tool: ${toolName}.`);
    }
    if (rawRoute.trust === "verified_read_only" && tool.read_only !== true) {
      throw new GatewayError(`Read-only route ${key} cannot expose write tool ${toolName}.`);
    }
    normalizedTools[toolName] = { read_only: tool.read_only };
  }
  return {
    connector_id: connectorId,
    version,
    artifact_digest: rawRoute.artifact_digest,
    trust: rawRoute.trust,
    enabled: rawRoute.enabled,
    endpoint: validateHttpsEndpoint(rawRoute.endpoint),
    tools: normalizedTools,
  };
}

export function parseRoutes(value) {
  let payload;
  try {
    payload = typeof value === "string" ? JSON.parse(value) : value;
  } catch (error) {
    throw new GatewayError(`CONNECTOR_ROUTES_JSON is invalid JSON: ${error.message}.`);
  }
  if (!isObject(payload)) throw new GatewayError("Connector routes must be an object.");
  return Object.fromEntries(
    Object.entries(payload).map(([key, route]) => [key, validateRoute(route, key)]),
  );
}

export function signPayload(payload, { privateKey, keyId }) {
  if (!privateKey || !keyId) throw new GatewayError("Gateway signing configuration is missing.", { status: 500 });
  const signature = crypto.sign(null, Buffer.from(canonicalJson(payload)), privateKey);
  return {
    alg: "EdDSA",
    key_id: keyId,
    signature: signature.toString("base64url"),
  };
}

export function verifyPayload(payload, attestation, publicKey) {
  if (!isObject(attestation) || attestation.alg !== "EdDSA" || !attestation.signature) return false;
  return crypto.verify(
    null,
    Buffer.from(canonicalJson(payload)),
    publicKey,
    Buffer.from(String(attestation.signature), "base64url"),
  );
}

function validatedContext(value) {
  if (value === undefined) return {};
  if (!isObject(value)) throw new GatewayError("context must be an object.");
  const allowed = new Set(["chain", "network", "chain_id", "wallet_address"]);
  for (const key of Object.keys(value)) {
    if (!allowed.has(key)) throw new GatewayError(`Unsupported connector context field: ${key}.`);
  }
  return value;
}

function expectedResponseKinds(route, tool) {
  if (route.tools[tool].read_only) return new Set(["read_result"]);
  return new Set(["evm_transaction_intent", "solana_transaction_intent"]);
}

export function createGateway({ routes, privateKey, keyId, fetchImpl = fetch, clock = () => new Date() }) {
  const routeTable = parseRoutes(routes);

  async function invoke({ connectorId, version, body }) {
    if (!CONNECTOR_ID_PATTERN.test(connectorId) || !SEMVER_PATTERN.test(version)) {
      throw new GatewayError("Connector path identity is invalid.");
    }
    if (!isObject(body)) throw new GatewayError("Invocation body must be an object.");
    const route = routeTable[routeKey(connectorId, version)];
    if (!route || !route.enabled) {
      throw new GatewayError("Connector version is unavailable.", {
        status: 404,
        code: "connector_unavailable",
      });
    }
    if (body.artifact_digest !== route.artifact_digest) {
      throw new GatewayError("Invocation artifact digest does not match the registry route.");
    }
    const tool = String(body.tool || "");
    if (!TOOL_PATTERN.test(tool) || !route.tools[tool]) {
      throw new GatewayError("Connector tool is not allowed by the registry route.");
    }
    if (!isObject(body.arguments)) throw new GatewayError("arguments must be an object.");
    const context = validatedContext(body.context);
    const now = clock();
    const issuedAt = now.toISOString();
    const expiresAt = new Date(now.getTime() + INVOCATION_TTL_SECONDS * 1000).toISOString();
    const envelope = {
      protocol_version: 1,
      request_id: crypto.randomUUID(),
      connector: {
        id: route.connector_id,
        version: route.version,
        artifact_digest: route.artifact_digest,
      },
      tool,
      arguments: body.arguments,
      context,
      issued_at: issuedAt,
      expires_at: expiresAt,
      nonce: crypto.randomBytes(18).toString("base64url"),
    };
    const signedEnvelope = {
      ...envelope,
      gateway_attestation: signPayload(envelope, { privateKey, keyId }),
    };

    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 15000);
    let response;
    try {
      response = await fetchImpl(route.endpoint, {
        method: "POST",
        redirect: "manual",
        signal: controller.signal,
        headers: {
          accept: "application/json",
          "content-type": "application/json",
        },
        body: JSON.stringify(signedEnvelope),
      });
    } catch (error) {
      throw new GatewayError(`Connector invocation failed: ${error.message}.`, {
        status: 502,
        code: "connector_transport_failed",
      });
    } finally {
      clearTimeout(timeout);
    }
    if (response.status >= 300 && response.status < 400) {
      throw new GatewayError("Connector redirects are prohibited.", {
        status: 502,
        code: "connector_redirect_rejected",
      });
    }
    if (response.status !== 200) {
      throw new GatewayError(`Connector returned HTTP ${response.status}.`, {
        status: 502,
        code: "connector_bad_status",
      });
    }
    const rawResponse = Buffer.from(await response.arrayBuffer());
    if (rawResponse.length > MAX_GATEWAY_BODY_BYTES) {
      throw new GatewayError("Connector response exceeds the gateway size limit.", {
        status: 502,
        code: "connector_response_too_large",
      });
    }
    let connectorResponse;
    try {
      connectorResponse = JSON.parse(rawResponse.toString("utf8"));
    } catch {
      throw new GatewayError("Connector response is not valid JSON.", {
        status: 502,
        code: "connector_invalid_json",
      });
    }
    if (!isObject(connectorResponse) || connectorResponse.protocol_version !== 1) {
      throw new GatewayError("Connector response protocol is invalid.", { status: 502 });
    }
    if (connectorResponse.request_id !== envelope.request_id || connectorResponse.tool !== tool) {
      throw new GatewayError("Connector response request binding is invalid.", { status: 502 });
    }
    const identity = connectorResponse.connector;
    if (
      !isObject(identity) ||
      identity.id !== route.connector_id ||
      identity.version !== route.version ||
      identity.artifact_digest !== route.artifact_digest
    ) {
      throw new GatewayError("Connector response identity is invalid.", { status: 502 });
    }
    if (!expectedResponseKinds(route, tool).has(connectorResponse.kind)) {
      throw new GatewayError("Connector response kind is not allowed for this tool.", { status: 502 });
    }
    return {
      ...connectorResponse,
      gateway_attestation: signPayload(connectorResponse, { privateKey, keyId }),
    };
  }

  return { invoke, routes: routeTable };
}

