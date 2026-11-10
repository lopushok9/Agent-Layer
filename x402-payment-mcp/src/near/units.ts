// NEAR amounts are u128 yoctoNEAR (10^24 per NEAR); gas is u64 in gas units
// (10^12 per TGas). Every amount crossing the MCP boundary is an integer string.
export const YOCTO_PER_NEAR = 10n ** 24n;
export const GAS_PER_TGAS = 10n ** 12n;
export const MAX_U128 = (1n << 128n) - 1n;
// Service cap on one transaction's total prepaid gas (the documented per-
// transaction maximum). Unused gas is refunded, but the cap bounds the preview.
export const MAX_TRANSACTION_GAS = 300n * GAS_PER_TGAS;

export function parseYocto(value: string, field = "amount"): bigint {
  if (!/^\d{1,40}$/.test(value)) throw new Error(`${field} must be an integer yoctoNEAR string`);
  const n = BigInt(value);
  if (n > MAX_U128) throw new Error(`${field} exceeds u128`);
  return n;
}

export function parseGas(value: string, field = "gas"): bigint {
  if (!/^\d{1,20}$/.test(value)) throw new Error(`${field} must be an integer gas string`);
  const n = BigInt(value);
  if (n <= 0n || n > MAX_TRANSACTION_GAS) throw new Error(`${field} must be between 1 and ${MAX_TRANSACTION_GAS} gas (300 TGas)`);
  return n;
}

// Human display only; never parsed back.
export function formatNear(yocto: bigint): string {
  const whole = yocto / YOCTO_PER_NEAR;
  const frac = (yocto % YOCTO_PER_NEAR).toString().padStart(24, "0").replace(/0+$/, "");
  return frac ? `${whole}.${frac}` : whole.toString();
}

export function formatTgas(gas: bigint): string {
  const whole = gas / GAS_PER_TGAS;
  const frac = (gas % GAS_PER_TGAS).toString().padStart(12, "0").replace(/0+$/, "");
  return frac ? `${whole}.${frac}` : whole.toString();
}

// NEAR account ID rules (nomicon): 2..64 chars, lowercase alphanumerics separated
// by single '-', '_' or '.'. Implicit accounts are 64 lowercase hex chars; ETH-
// implicit accounts are 0x + 40 hex.
const ACCOUNT_ID = /^(([a-z\d]+[-_])*[a-z\d]+\.)*([a-z\d]+[-_])*[a-z\d]+$/;
export function isValidAccountId(id: string): boolean {
  return id.length >= 2 && id.length <= 64 && ACCOUNT_ID.test(id);
}
export function assertAccountId(id: string, field = "account_id"): string {
  if (!isValidAccountId(id)) throw new Error(`${field} is not a valid NEAR account ID`);
  return id;
}
