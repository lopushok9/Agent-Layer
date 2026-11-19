import express, { type Router } from "express";
import type { Config } from "./config.js";
import { safeEqual, sha256 } from "./security.js";
import type { Usage } from "./usage.js";

// GET /v1/stats?days=30 with "Authorization: Bearer <STATS_TOKEN>". Off (404)
// unless STATS_TOKEN is set. Aggregates only: no addresses, emails or arguments.
export function statsRouter(config: Pick<Config, "STATS_TOKEN">, usage: Pick<Usage, "stats">): Router {
  const router = express.Router();
  router.get("/v1/stats", (req, res, next) => {
    res.set("Cache-Control", "no-store");
    if (!config.STATS_TOKEN) return res.status(404).end();
    const header = req.headers.authorization ?? "";
    const token = header.startsWith("Bearer ") ? header.slice(7) : "";
    if (!token || !safeEqual(sha256(token), sha256(config.STATS_TOKEN))) return res.status(401).set("WWW-Authenticate", "Bearer").json({ error: "unauthorized" });
    const days = Number(req.query.days ?? 30);
    if (!Number.isInteger(days) || days < 1 || days > 365) return res.status(400).json({ error: "days must be an integer from 1 to 365" });
    usage.stats(days).then(s => res.json(s), next);
  });
  return router;
}
