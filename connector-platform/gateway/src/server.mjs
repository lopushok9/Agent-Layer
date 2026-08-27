import http from "node:http";
import { createGateway, GatewayError, MAX_GATEWAY_BODY_BYTES } from "./gateway.mjs";

function readBody(request) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    let size = 0;
    request.on("data", (chunk) => {
      size += chunk.length;
      if (size > MAX_GATEWAY_BODY_BYTES) {
        reject(new GatewayError("Request body exceeds the gateway size limit.", { status: 413 }));
        request.destroy();
        return;
      }
      chunks.push(chunk);
    });
    request.on("end", () => {
      try {
        resolve(JSON.parse(Buffer.concat(chunks).toString("utf8")));
      } catch {
        reject(new GatewayError("Request body is not valid JSON."));
      }
    });
    request.on("error", reject);
  });
}

function sendJson(response, status, payload) {
  const body = Buffer.from(`${JSON.stringify(payload)}\n`);
  response.writeHead(status, {
    "content-type": "application/json",
    "content-length": body.length,
    "cache-control": "no-store",
  });
  response.end(body);
}

const routes = process.env.CONNECTOR_ROUTES_JSON || "{}";
const privateKey = process.env.CONNECTOR_GATEWAY_SIGNING_PRIVATE_KEY_PEM || "";
const keyId = process.env.CONNECTOR_GATEWAY_SIGNING_KEY_ID || "";
const gateway = createGateway({ routes, privateKey, keyId });
const port = Number(process.env.PORT || 3000);

const server = http.createServer(async (request, response) => {
  if (request.method === "GET" && request.url === "/healthz") {
    sendJson(response, 200, { ok: true, service: "agentlayer-connector-gateway" });
    return;
  }
  const match = String(request.url || "").match(
    /^\/v1\/connectors\/([a-z0-9._-]+)\/([^/]+)\/invoke$/,
  );
  if (request.method !== "POST" || !match) {
    sendJson(response, 404, { ok: false, error: "not_found" });
    return;
  }
  try {
    const body = await readBody(request);
    const payload = await gateway.invoke({
      connectorId: match[1],
      version: decodeURIComponent(match[2]),
      body,
    });
    sendJson(response, 200, payload);
  } catch (error) {
    const status = error instanceof GatewayError ? error.status : 500;
    sendJson(response, status, {
      ok: false,
      error: error instanceof GatewayError ? error.code : "gateway_internal_error",
      message: error instanceof GatewayError ? error.message : "Connector gateway failed.",
    });
  }
});

server.listen(port, "0.0.0.0", () => {
  console.log(JSON.stringify({ event: "connector_gateway_started", port }));
});

function shutdown() {
  server.close(() => process.exit(0));
  setTimeout(() => process.exit(1), 10000).unref();
}

process.on("SIGTERM", shutdown);
process.on("SIGINT", shutdown);

