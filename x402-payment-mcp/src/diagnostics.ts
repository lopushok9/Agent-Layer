import type { NextFunction, Request, Response } from "express";

// Logs one line per connector-facing request that did not succeed, so host
// integrations (e.g. Muse's custom connectors) can be debugged from service
// logs. Never logs credential values: only which auth headers were present
// and the shape of the Authorization scheme.
const WATCHED = /^\/(mcp|oauth\/|\.well-known\/)/;
const AUTH_HEADERS = ["authorization", "x-api-key", "api-key", "x-auth-token", "x-access-token"];

export function authScheme(value: string | undefined): string {
  if (!value) return "none";
  const [scheme, credential] = value.split(/\s+/, 2);
  if (!credential) return scheme?.startsWith("alx402_") ? "raw-pat" : "raw";
  if (scheme?.toLowerCase() !== "bearer") return `scheme:${scheme?.toLowerCase().slice(0, 16)}`;
  if (credential.startsWith("alx402_")) return "bearer-pat";
  return credential.split(".").length === 3 ? "bearer-jwt" : "bearer-other";
}

export function connectorDiagnostics(req: Request, res: Response, next: NextFunction) {
  if (!WATCHED.test(req.path)) return next();
  const started = Date.now();
  res.on("finish", () => {
    if (res.statusCode < 400 && !req.path.startsWith("/.well-known/")) return;
    console.warn(JSON.stringify({
      event: "connector_request",
      method: req.method,
      path: req.path,
      status: res.statusCode,
      ms: Date.now() - started,
      host: req.headers.host ?? null,
      ua: String(req.headers["user-agent"] ?? "").slice(0, 120),
      accept: String(req.headers.accept ?? "").slice(0, 80),
      auth: authScheme(req.headers.authorization),
      auth_headers: AUTH_HEADERS.filter((h) => req.headers[h] !== undefined),
    }));
  });
  next();
}
