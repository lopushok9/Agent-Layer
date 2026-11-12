import { createHash } from "node:crypto";
import { z } from "zod";
import type { NearAccountService } from "./account.js";
import { NearPublicError, type NearOperations } from "./operations.js";
import type { NearOperation, NearStore } from "./store.js";
import { nearFingerprint, nearTransactionInput, normalizeNearTransaction, type NormalizedNearTransaction } from "./transaction.js";
import { canonicalJson } from "./solver-relay.js";
import { assertAccountId, formatNear } from "./units.js";

// near_plan: several NEAR transactions (each to one receiver, as NEAR requires)
// previewed and confirmed once, then executed strictly in order. Every step is
// its own near_tx operation going through NearOperations.execute, so signing,
// nonce handling, persistence before broadcast and unknown-outcome rules are
// unchanged. Before a step, its checks (view calls compared with a bound) must
// hold, otherwise the plan stops before signing that step. A plan is never
// re-run: after a stop the adapter is called again and plans only what is left.
const MAX_STEPS = 6;
const UINT = /^\d{1,40}$/;

export const planCheckInput = z.strictObject({
  label: z.string().min(3).max(160),
  contract_id: z.string().min(2).max(64),
  method_name: z.string().min(1).max(128).regex(/^[A-Za-z_][A-Za-z0-9_]*$/),
  args: z.record(z.string(), z.unknown()).default({}),
  path: z.array(z.union([z.string().max(128), z.number().int().min(0).max(64)])).max(6).default([]).describe("Keys/indexes into the JSON result"),
  op: z.enum(["gte", "lte", "eq"]),
  value: z.string().regex(UINT).describe("Unsigned integer the result at path is compared with"),
});
export type PlanCheck = z.infer<typeof planCheckInput>;

export const nearPlanInput = z.strictObject({
  title: z.string().min(3).max(160),
  steps: z.array(z.strictObject({
    title: z.string().min(3).max(160),
    transaction: nearTransactionInput,
    checks: z.array(planCheckInput).max(8).default([]).describe("Must all hold right before this step is signed"),
  })).min(1).max(MAX_STEPS),
});

type StoredStep = { title: string; receiverId: string; actions: NormalizedNearTransaction["actions"]; checks: PlanCheck[] };
type Progress = { step: number; child?: string; results: StepResult[] };
type StepResult = { step: number; title: string; operation_id: string; status: string; transaction_hash?: string | null; explorer_url?: string; failed_receipts?: number; return_value?: unknown };

export class NearPlans {
  constructor(private accounts: NearAccountService, private operations: NearOperations, private store: NearStore) {}
  private get rpc() { return this.accounts.rpc; }
  private get config() { return this.accounts.config; }

  // Generic entry (agent-built plans) and the adapters' entry.
  async prepare(userId: string, input: z.input<typeof nearPlanInput>, summary: Record<string, unknown> = {}) {
    const p = nearPlanInput.parse(input);
    const steps: StoredStep[] = p.steps.map(s => {
      const tx = normalizeNearTransaction(s.transaction);
      for (const c of s.checks) assertAccountId(c.contract_id, "contract_id");
      return { title: s.title, receiverId: tx.receiverId, actions: tx.actions, checks: s.checks };
    });
    const account = await this.accounts.account(userId);
    const est = await this.operations.estimate(account.accountId, steps.map(s => ({ receiverId: s.receiverId, actions: s.actions })));
    const missing = est.findIndex(e => e.creates);
    if (missing >= 0) throw new NearPublicError(`plan step ${missing + 1} sends to an account that does not exist; nothing was signed`);
    const deposit = est.reduce((t, e) => t + e.deposit, 0n), maxFee = est.reduce((t, e) => t + e.maxFee, 0n), prepay = est.reduce((t, e) => t + e.prepay, 0n);
    const available = est[0]!.available;
    if (deposit + prepay > available) throw new NearPublicError(`insufficient NEAR for the whole plan: needs ${formatNear(deposit + prepay)} NEAR up front (attached ${formatNear(deposit)} + max fees ${formatNear(maxFee)}), available ${formatNear(available > 0n ? available : 0n)}; nothing was signed`);
    const fingerprint = planFingerprint(this.config.network, account.accountId, account.publicKey, steps);
    const descriptions = steps.map((s, i) => ({
      step: i + 1, title: s.title, receiver_id: s.receiverId, actions: est[i]!.descriptions,
      attached_near: formatNear(est[i]!.deposit), max_network_fee_near: formatNear(est[i]!.maxFee),
      ...(s.checks.length ? { checks_before_signing: s.checks.map(c => c.label) } : {}),
      ...(est[i]!.warnings.length ? { warnings: est[i]!.warnings } : {}),
    }));
    const op = await this.store.createOperation({
      userId, network: this.config.network, accountId: account.accountId, publicKey: account.publicKey, kind: "near_plan",
      receiverId: steps[0]!.receiverId, actions: [], descriptions, plan: { title: p.title, steps, summary }, fingerprint,
    }, this.config.previewTtlSeconds);
    return {
      operation_id: op.id, kind: "near_plan", network: this.config.network, signer_id: account.accountId, title: p.title,
      ...summary, steps: descriptions,
      total_attached_near: formatNear(deposit), max_network_fee_near: formatNear(maxFee), available_near: formatNear(available),
      expires_at: op.expiresAt.toISOString(),
      confirmation: "Show the title, every step (receiver, actions with args, attached NEAR, checks) and the totals; after the user confirms this exact plan call near_plan_execute once. Steps run in order; a failed check or step stops the plan and later steps are not signed.",
    };
  }

  async execute(userId: string, id: string, purpose: string) {
    const op = await this.store.reserve(userId, id, "near_plan", purpose);
    const plan = op.plan as { title: string; steps: StoredStep[]; summary: Record<string, unknown> };
    const progress: Progress = { step: 0, results: [] };
    const stop = async (status: "failed" | "unknown", reason: string, extra: Record<string, unknown> = {}) => {
      await this.store.update(userId, id, { status, result: progress, error: reason });
      return this.report(op, plan, status, progress, { reason, ...extra });
    };
    try {
      const account = await this.accounts.account(userId);
      if (account.accountId !== op.accountId || account.publicKey !== op.publicKey) throw new Error("preview no longer matches this NEAR account");
      if (planFingerprint(op.network, op.accountId, op.publicKey, plan.steps) !== op.fingerprint) throw new Error("preview binding mismatch");
    } catch (e) {
      await this.store.update(userId, id, { status: "failed", error: "plan binding check failed before signing" });
      throw e;
    }
    await this.store.update(userId, id, { status: "submitted", result: progress });

    for (let i = 0; i < plan.steps.length; i++) {
      const s = plan.steps[i]!;
      progress.step = i + 1;
      delete progress.child;
      for (const c of s.checks) {
        const r = await this.check(c).catch(() => ({ ok: false, actual: "unreadable" }));
        if (!r.ok) return stop("failed", `stopped before step ${i + 1} (${s.title}): check failed: ${c.label} (got ${r.actual}, need ${c.op} ${c.value}); this step and later ones were not signed`);
      }
      const tx: NormalizedNearTransaction = { receiverId: s.receiverId, actions: s.actions };
      const child = await this.store.createOperation({
        userId, network: op.network, accountId: op.accountId, publicKey: op.publicKey, kind: "near_tx", receiverId: s.receiverId, actions: s.actions,
        descriptions: (op.descriptions[i] as any)?.actions ?? [], plan: { near_plan: id, step: i + 1 }, fingerprint: nearFingerprint(op.network, op.accountId, op.publicKey, tx),
      }, this.config.previewTtlSeconds);
      progress.child = child.id;
      await this.store.update(userId, id, { status: "submitted", result: progress });
      let r: any;
      try { r = await this.operations.execute(userId, child.id, `${purpose} [step ${i + 1}/${plan.steps.length}: ${s.title}]`.slice(0, 500), "near_tx", "FINAL", id); }
      catch (e) { return stop("failed", `step ${i + 1} (${s.title}) was not executed: ${(e as Error).message}`.slice(0, 400)); }
      progress.results.push(stepResult(i + 1, s.title, child.id, r));
      if (r.status === "unknown" || r.status === "submitted") return stop("unknown", `step ${i + 1} (${s.title}) outcome is not known yet; call near_plan_status. Later steps were not signed`);
      if (r.status !== "confirmed") return stop("failed", `step ${i + 1} (${s.title}) failed on chain; later steps were not signed`);
      if ((r.failed_receipts ?? 0) > 0) return stop("failed", `step ${i + 1} (${s.title}) had failed receipts (tokens may have been refunded); later steps were not signed`);
    }
    delete progress.child;
    await this.store.update(userId, id, { status: "confirmed", result: progress });
    return this.report(op, plan, "confirmed", progress, {});
  }

  // Reconciles a plan that stopped on an unknown step outcome (or was
  // interrupted while running) through that step's own operation.
  async status(userId: string, id: string) {
    const op = await this.store.operation(userId, id);
    if (!op || op.kind !== "near_plan") throw new NearPublicError("not a near_plan operation for this user");
    const plan = op.plan as { title: string; steps: StoredStep[] };
    const progress = (op.result as Progress | null) ?? { step: 0, results: [] };
    if ((op.status === "unknown" || op.status === "submitted") && progress.child) {
      const child = await this.operations.status(userId, progress.child) as any;
      if (child.status === "confirmed" || child.status === "failed") {
        const last = progress.results.find(r => r.operation_id === progress.child);
        if (last) Object.assign(last, stepResult(last.step, last.title, last.operation_id, child));
        else progress.results.push(stepResult(progress.step, plan.steps[progress.step - 1]?.title ?? "", progress.child, child));
        const done = child.status === "confirmed" && !(child.failed_receipts > 0) && progress.step === plan.steps.length;
        const reason = done ? null : `stopped at step ${progress.step}: ${child.status}; later steps were not signed. Prepare again: adapters plan only what is left`;
        delete progress.child;
        await this.store.update(userId, id, { status: done ? "confirmed" : "failed", result: progress, error: reason });
        return this.report(op, plan, done ? "confirmed" : "failed", progress, reason ? { reason } : {});
      }
      return this.report(op, plan, op.status, progress, { reason: "step outcome not known yet; check again shortly. Do not prepare a replacement." });
    }
    return this.report(op, plan, op.status, progress, op.error ? { reason: op.error } : {});
  }

  private report(op: NearOperation, plan: { title: string; steps: StoredStep[] }, status: string, p: Progress, extra: Record<string, unknown>) {
    return { operation_id: op.id, kind: "near_plan", title: plan.title, status, steps_total: plan.steps.length, steps_done: p.results.filter(r => r.status === "confirmed").length, results: p.results, ...extra };
  }

  private async check(c: PlanCheck): Promise<{ ok: boolean; actual: string }> {
    let v: any = (await this.rpc.callFunction(c.contract_id, c.method_name, c.args)).result;
    for (const k of c.path) v = v == null ? undefined : v[k as any];
    const s = typeof v === "number" && Number.isSafeInteger(v) && v >= 0 ? String(v) : v === null || v === undefined ? "0" : v;
    if (typeof s !== "string" || !UINT.test(s)) return { ok: false, actual: "not an unsigned integer" };
    const a = BigInt(s), b = BigInt(c.value);
    return { ok: c.op === "gte" ? a >= b : c.op === "lte" ? a <= b : a === b, actual: s };
  }
}

function stepResult(step: number, title: string, id: string, r: any): StepResult {
  return { step, title, operation_id: id, status: r.status, transaction_hash: r.transaction_hash ?? null, ...(r.explorer_url ? { explorer_url: r.explorer_url } : {}), ...(typeof r.failed_receipts === "number" ? { failed_receipts: r.failed_receipts } : {}), ...(r.return_value !== undefined ? { return_value: r.return_value } : {}) };
}

export function planFingerprint(network: string, accountId: string, publicKey: string, steps: StoredStep[]) {
  return createHash("sha256").update(canonicalJson(["near-plan:v1", network, accountId, publicKey, steps])).digest("hex");
}

// ---- Shared NEAR building blocks for adapters ------------------------------
export const ONE_YOCTO = "1";
export const TGAS = (n: number) => `${BigInt(n) * 10n ** 12n}`;
export type PlanAction = z.input<typeof nearTransactionInput>["actions"][number];
export const call = (method_name: string, args: Record<string, unknown>, deposit_yocto = "0", gasTgas = 30): PlanAction => ({ type: "function_call", method_name, args, deposit_yocto, gas: TGAS(gasTgas) });
// NEP-141 deposit into a contract (ft_on_transfer with msg).
export const ftTransferCall = (receiver_id: string, amount: bigint, msg = "") => call("ft_transfer_call", { receiver_id, amount: amount.toString(), msg }, ONE_YOCTO, 50);
// NEP-145: registration needed only when storage_balance_of is null.
export async function needsStorage(rpc: NearAccountService["rpc"], contract: string, accountId: string): Promise<bigint | null> {
  const [bal, bounds] = await Promise.all([rpc.callFunction(contract, "storage_balance_of", { account_id: accountId }), rpc.callFunction(contract, "storage_balance_bounds", {})]);
  if (bal.result) return null;
  const min = (bounds.result as any)?.min;
  if (typeof min !== "string" || !UINT.test(min)) throw new NearPublicError(`${contract} returned no storage bounds; nothing was signed`);
  return BigInt(min);
}
export const storageDeposit = (account_id: string, amount: bigint, registrationOnly = true) => call("storage_deposit", { account_id, registration_only: registrationOnly }, amount.toString(), 10);
