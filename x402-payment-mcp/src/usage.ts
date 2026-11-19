import type { Pool } from "pg";

export type UsageEvent = { kind: "tool" | "auth"; name: string; userId?: string | null; clientId?: string | null; ok: boolean; ms?: number | null; detail?: string | null };

// Error text can carry addresses, URLs, amounts or names; keep only its shape
// so identical failures group together and nothing user-specific is stored.
export function scrubDetail(value: string | null | undefined): string | null {
  if (!value) return null;
  return value
    .replace(/https?:\/\/\S+/g, "<url>")
    .replace(/0x[0-9a-fA-F]{8,}/g, "0x…")
    .replace(/[\w.+-]+@[\w-]+\.[\w.]+/g, "<email>")
    .replace(/\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b/gi, "<id>")
    .replace(/\b\d+(\.\d+)?\b/g, "#")
    .replace(/\s+/g, " ").trim().slice(0, 160) || null;
}

// Personal access tokens arrive as "pat:<id>"; one bucket for all of them.
export const clientBucket = (clientId: string | null | undefined) => !clientId ? null : clientId.startsWith("pat:") ? "pat" : clientId.slice(0, 200);

export class Usage {
  constructor(private readonly pool: Pool) {}

  // Fire and forget: statistics never slow down or fail a user request.
  record(e: UsageEvent) {
    this.pool.query(`INSERT INTO usage_events(kind,name,user_id,client_id,ok,ms,detail) VALUES ($1,$2,$3,$4,$5,$6,$7)`,
      [e.kind, e.name.slice(0, 80), e.userId ?? null, clientBucket(e.clientId), e.ok, e.ms == null ? null : Math.min(Math.round(e.ms), 2_147_483_647), e.detail === "new_user" ? "new_user" : scrubDetail(e.detail)])
      .catch(err => console.error(JSON.stringify({ level: "error", event: "usage_record_failed", message: err instanceof Error ? err.message : String(err) })));
  }

  async stats(days: number) {
    const w = `${days} days`, q = async (sql: string, args: unknown[] = [w]) => (await this.pool.query(sql, args)).rows;
    const num = (v: unknown) => v == null ? null : Number(v);
    const [[users], usersDaily, signInMethods, [wallets], [active], activeDaily, tools, errors, clients, auth, [funnel], operations, [signatures], payments] = await Promise.all([
      q(`SELECT count(*) total, count(*) FILTER (WHERE created_at>now()-$1::interval) new FROM users`),
      q(`SELECT to_char(date_trunc('day',created_at),'YYYY-MM-DD') AS day, count(*) new_users FROM users WHERE created_at>now()-$1::interval GROUP BY 1 ORDER BY 1`),
      q(`SELECT provider, count(DISTINCT user_id) users FROM oauth_identities GROUP BY 1 ORDER BY 2 DESC`, []),
      q(`SELECT count(*) total, count(*) FILTER (WHERE created_at>now()-$1::interval) new FROM smart_wallets`),
      q(`SELECT count(DISTINCT user_id) FILTER (WHERE at>now()-interval '1 day') dau, count(DISTINCT user_id) FILTER (WHERE at>now()-interval '7 days') wau, count(DISTINCT user_id) mau FROM usage_events WHERE kind='tool' AND at>now()-interval '30 days'`, []),
      q(`SELECT to_char(date_trunc('day',at),'YYYY-MM-DD') AS day, count(DISTINCT user_id) users, count(*) calls, count(*) FILTER (WHERE NOT ok) errors FROM usage_events WHERE kind='tool' AND at>now()-$1::interval GROUP BY 1 ORDER BY 1`),
      q(`SELECT name tool, count(*) calls, count(DISTINCT user_id) users, count(*) FILTER (WHERE NOT ok) errors, round(percentile_cont(0.5) WITHIN GROUP (ORDER BY ms)) p50_ms, round(percentile_cont(0.95) WITHIN GROUP (ORDER BY ms)) p95_ms, max(at) last_at FROM usage_events WHERE kind='tool' AND at>now()-$1::interval GROUP BY 1 ORDER BY 2 DESC`),
      q(`SELECT name tool, detail error, count(*) count, count(DISTINCT user_id) users, max(at) last_at FROM usage_events WHERE kind='tool' AND NOT ok AND at>now()-$1::interval GROUP BY 1,2 ORDER BY 3 DESC LIMIT 25`),
      q(`SELECT COALESCE(c.client_name, CASE WHEN e.client_id='pat' THEN 'personal access token' ELSE 'unknown client' END) client, count(*) calls, count(DISTINCT e.user_id) users FROM usage_events e LEFT JOIN oauth_clients c ON c.client_id=e.client_id WHERE e.kind='tool' AND e.at>now()-$1::interval GROUP BY 1 ORDER BY 2 DESC LIMIT 25`),
      q(`SELECT name event, count(*) count, count(DISTINCT user_id) users, count(*) FILTER (WHERE detail='new_user') new_users FROM usage_events WHERE kind='auth' AND at>now()-$1::interval GROUP BY 1 ORDER BY 2 DESC`),
      q(`SELECT count(*) new_users, count(*) FILTER (WHERE EXISTS(SELECT 1 FROM usage_events e WHERE e.kind='tool' AND e.user_id=u.id)) called_a_tool, count(*) FILTER (WHERE EXISTS(SELECT 1 FROM wallet_operations o WHERE o.user_id=u.id AND o.status='confirmed') OR EXISTS(SELECT 1 FROM payments p WHERE p.user_id=u.id AND p.status='settled')) transacted FROM users u WHERE u.created_at>now()-$1::interval`),
      q(`SELECT network, status, count(*) count, count(DISTINCT user_id) users FROM wallet_operations WHERE consumed_at>now()-$1::interval GROUP BY 1,2 ORDER BY 3 DESC`),
      q(`SELECT count(*) FILTER (WHERE status='signed') signed, count(*) FILTER (WHERE status='failed') failed FROM wallet_signatures WHERE consumed_at>now()-$1::interval`),
      q(`SELECT status, count(*) count, count(DISTINCT user_id) users, round(sum(COALESCE(settled_amount,amount))/1e6,6) usdc FROM payments WHERE created_at>now()-$1::interval GROUP BY 1 ORDER BY 2 DESC`),
    ]);
    const n = (rows: Record<string, unknown>[], keys: string[]) => rows.map(r => Object.fromEntries(Object.entries(r).map(([k, v]) => [k, keys.includes(k) ? num(v) : v])));
    return {
      window_days: days,
      generated_at: new Date().toISOString(),
      users: { total: num(users.total), new: num(users.new), new_by_day: n(usersDaily, ["new_users"]), by_sign_in_method: n(signInMethods, ["users"]) },
      wallets: { total: num(wallets.total), new: num(wallets.new) },
      active_users: { dau: num(active.dau), wau: num(active.wau), mau: num(active.mau), by_day: n(activeDaily, ["users", "calls", "errors"]) },
      funnel: { new_users: num(funnel.new_users), called_a_tool: num(funnel.called_a_tool), transacted: num(funnel.transacted) },
      tools: n(tools, ["calls", "users", "errors", "p50_ms", "p95_ms"]),
      top_errors: n(errors, ["count", "users"]),
      clients: n(clients, ["calls", "users"]),
      auth: n(auth, ["count", "users", "new_users"]),
      wallet_operations: n(operations, ["count", "users"]),
      signatures: { signed: num(signatures.signed), failed: num(signatures.failed) },
      x402_payments: n(payments, ["count", "users", "usdc"]),
      note: "Tool and sign-in events are recorded from this release on; users, wallets, operations and payments come from existing tables. Tool arguments are never stored.",
    };
  }
}
