import type { NextFunction, Request, Response } from "express";

// Logs one line per request (except health checks) so host integrations such
// as Muse's custom connectors can be debugged from service logs: which path
// they call, with which auth header shape, and what we answered. Never logs
// credential values or query values, only header and query parameter names
// and the shape of the Authorization scheme.
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
  if (req.path === "/healthz") return next();
  const started = Date.now();
  res.on("finish", () => {
    console.warn(JSON.stringify({
      event: "connector_request",
      method: req.method,
      path: req.path.slice(0, 120),
      query_keys: Object.keys(req.query).slice(0, 10),
      status: res.statusCode,
      ms: Date.now() - started,
      host: req.headers.host ?? null,
      ua: String(req.headers["user-agent"] ?? "").slice(0, 120),
      accept: String(req.headers.accept ?? "").slice(0, 80),
      content_type: String(req.headers["content-type"] ?? "").slice(0, 60),
      auth: authScheme(req.headers.authorization),
      auth_headers: AUTH_HEADERS.filter((h) => req.headers[h] !== undefined),
    }));
  });
  next();
}
