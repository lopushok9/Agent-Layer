import { createServer, type IncomingMessage, type Server, type ServerResponse } from "node:http";

import { ConnectorSdkError } from "./errors.js";
import type { ConnectorInvocationRequest, ReadOnlyConnector } from "./types.js";

const DEFAULT_MAX_BODY_BYTES = 1024 * 1024;

export interface ConnectorHttpOptions {
  maxBodyBytes?: number;
}

export interface StartConnectorServerOptions extends ConnectorHttpOptions {
  host?: string;
  port?: number;
}

function sendJson(response: ServerResponse, statusCode: number, payload: unknown): void {
  const body = JSON.stringify(payload);
  response.writeHead(statusCode, {
    "content-type": "application/json; charset=utf-8",
    "content-length": Buffer.byteLength(body),
    "cache-control": "no-store",
    "x-content-type-options": "nosniff",
  });
  response.end(body);
}

async function readJson(request: IncomingMessage, maxBodyBytes: number): Promise<unknown> {
  const contentLength = Number(request.headers["content-length"] ?? 0);
  if (Number.isFinite(contentLength) && contentLength > maxBodyBytes) {
    throw new ConnectorSdkError("request_too_large", "Request body exceeds the size limit.", 413);
  }
  const chunks: Buffer[] = [];
  let size = 0;
  for await (const chunk of request) {
    const buffer = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk);
    size += buffer.length;
    if (size > maxBodyBytes) {
      throw new ConnectorSdkError("request_too_large", "Request body exceeds the size limit.", 413);
    }
    chunks.push(buffer);
  }
  try {
    return JSON.parse(Buffer.concat(chunks).toString("utf8"));
  } catch {
    throw new ConnectorSdkError("invalid_json", "Request body must be valid JSON.");
  }
}

export function createConnectorHttpHandler(
  connector: ReadOnlyConnector,
  options: ConnectorHttpOptions = {}
): (request: IncomingMessage, response: ServerResponse) => Promise<void> {
  const maxBodyBytes = options.maxBodyBytes ?? DEFAULT_MAX_BODY_BYTES;
  if (!Number.isInteger(maxBodyBytes) || maxBodyBytes < 1024) {
    throw new ConnectorSdkError("invalid_http_options", "maxBodyBytes must be at least 1024.");
  }
  return async (request, response) => {
    try {
      if (request.method === "GET" && request.url === "/healthz") {
        sendJson(response, 200, {
          ok: true,
          connector: {
            id: connector.manifest.id,
            version: connector.manifest.version,
          },
        });
        return;
      }
      if (request.method !== "POST" || request.url !== "/invoke") {
        sendJson(response, 404, { ok: false, error: { code: "not_found", message: "Not found." } });
        return;
      }
      if (!String(request.headers["content-type"] ?? "").toLowerCase().startsWith("application/json")) {
        throw new ConnectorSdkError("unsupported_media_type", "Content-Type must be application/json.", 415);
      }
      const payload = await readJson(request, maxBodyBytes);
      const result = await connector.invoke(payload as ConnectorInvocationRequest);
      sendJson(response, 200, result);
    } catch (error) {
      const sdkError =
        error instanceof ConnectorSdkError
          ? error
          : new ConnectorSdkError("internal_error", "Connector invocation failed.", 500);
      sendJson(response, sdkError.statusCode, {
        ok: false,
        error: { code: sdkError.code, message: sdkError.message },
      });
    }
  };
}

export async function startConnectorServer(
  connector: ReadOnlyConnector,
  options: StartConnectorServerOptions = {}
): Promise<Server> {
  const handler = createConnectorHttpHandler(connector, options);
  const host = options.host ?? "0.0.0.0";
  const port = options.port ?? Number(process.env.PORT ?? 3000);
  if (!Number.isInteger(port) || port < 1 || port > 65535) {
    throw new ConnectorSdkError("invalid_http_options", "port must be between 1 and 65535.");
  }
  const server = createServer((request, response) => void handler(request, response));
  await new Promise<void>((resolve, reject) => {
    server.once("error", reject);
    server.listen(port, host, () => {
      server.off("error", reject);
      resolve();
    });
  });
  return server;
}
