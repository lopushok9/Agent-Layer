import { createCipheriv, createDecipheriv, randomBytes } from "node:crypto";
import type { Pool } from "pg";

// WalletConnect's IKeyValueStorage (getKeys/getEntries/getItem/setItem/removeItem)
// backed by Postgres, so pairings and sessions survive deploys instead of
// living in the container's file system. The values include pairing and session
// symmetric keys: each is sealed with AES-256-GCM, bound to its key by the AAD.
// Reads come from memory after load; the WalletConnect core issues many of them.
export class PgKeyValueStorage {
  private cache?: Promise<Map<string, unknown>>;
  constructor(private pool: Pool, private secret: string) {
    if (Buffer.from(secret, "base64").length !== 32) throw new Error("WalletConnect storage key must be 32 bytes");
  }
  private entries() {
    this.cache ??= this.pool.query<{ key: string; value: string }>("SELECT key,value FROM walletconnect_storage").then(r => new Map(r.rows.map(x => [x.key, this.open(x.key, x.value)])));
    return this.cache;
  }
  async getKeys() { return [...(await this.entries()).keys()]; }
  async getEntries<T = unknown>() { return [...(await this.entries()).entries()] as [string, T][]; }
  async getItem<T = unknown>(key: string) { return (await this.entries()).get(key) as T | undefined; }
  async setItem<T = unknown>(key: string, value: T) {
    const map = await this.entries();
    await this.pool.query("INSERT INTO walletconnect_storage(key,value) VALUES($1,$2) ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value,updated_at=now()", [key, this.seal(key, value)]);
    map.set(key, value);
  }
  async removeItem(key: string) {
    const map = await this.entries();
    await this.pool.query("DELETE FROM walletconnect_storage WHERE key=$1", [key]);
    map.delete(key);
  }
  private seal(key: string, value: unknown) {
    const iv = randomBytes(12), cipher = createCipheriv("aes-256-gcm", Buffer.from(this.secret, "base64"), iv);
    cipher.setAAD(Buffer.from(`walletconnect:v1:${key}`));
    const body = Buffer.concat([cipher.update(JSON.stringify(value) ?? "null", "utf8"), cipher.final()]);
    return ["v1", iv.toString("base64"), body.toString("base64"), cipher.getAuthTag().toString("base64")].join(".");
  }
  private open(key: string, sealed: string): unknown {
    const [v, iv, body, tag] = sealed.split(".");
    if (v !== "v1" || !iv || !body || !tag) throw new Error("invalid WalletConnect storage entry");
    const decipher = createDecipheriv("aes-256-gcm", Buffer.from(this.secret, "base64"), Buffer.from(iv, "base64"));
    decipher.setAAD(Buffer.from(`walletconnect:v1:${key}`)); decipher.setAuthTag(Buffer.from(tag, "base64"));
    return JSON.parse(Buffer.concat([decipher.update(Buffer.from(body, "base64")), decipher.final()]).toString("utf8"));
  }
}
