import { readFile } from "node:fs/promises";
import { Pool, type PoolClient } from "pg";
import { randomUUID } from "node:crypto";
import { sha256 } from "./security.js";

export type OAuthClient = { clientId: string; clientName: string; redirectUris: string[] };
export type LoginState = { id: string; clientId: string; redirectUri: string; state: string; codeChallenge: string; resource: string; scope: string };
export type AuthorizationCode = LoginState & { userId: string };
export type Preview = { id: string; userId: string; method: string; url: string; body: unknown; fingerprint: string; amount: string; payTo: string; expiresAt: Date };

export class Store {
  readonly pool: Pool;
  constructor(databaseUrl: string) { this.pool = new Pool({ connectionString: databaseUrl, ssl: databaseTls(databaseUrl) }); }
  async close() { await this.pool.end(); }
  async migrate() {
    const sql=await readFile(new URL("../migrations/001_initial.sql",import.meta.url),"utf8");
    await this.pool.query(sql);
  }

  async registerClient(clientName: string, redirectUris: string[]): Promise<OAuthClient> {
    const clientId = `mcp_${randomUUID()}`;
    const row = await this.pool.query(`INSERT INTO oauth_clients (client_id,client_name,redirect_uris) VALUES ($1,$2,$3) RETURNING client_id,client_name,redirect_uris`, [clientId, clientName, JSON.stringify(redirectUris)]);
    return mapClient(row.rows[0]);
  }
  async getClient(clientId: string): Promise<OAuthClient | null> {
    const row = await this.pool.query(`SELECT client_id,client_name,redirect_uris FROM oauth_clients WHERE client_id=$1`, [clientId]);
    return row.rowCount ? mapClient(row.rows[0]) : null;
  }
  async createLoginState(data: Omit<LoginState, "id">, browserSessionHash:string, csrfTokenHash:string): Promise<string> {
    const id = randomUUID();
    await this.pool.query(`INSERT INTO oauth_login_states (id,client_id,redirect_uri,oauth_state,code_challenge,resource,scope,browser_session_hash,csrf_token_hash,expires_at) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,now()+interval '10 minutes')`, [id,data.clientId,data.redirectUri,data.state,data.codeChallenge,data.resource,data.scope,browserSessionHash,csrfTokenHash]);
    return id;
  }
  async approveLoginState(id:string,browserSessionHash:string,csrfTokenHash:string,provider:"google"|"github"):Promise<boolean>{
    const r=await this.pool.query(`UPDATE oauth_login_states SET approved_at=now(),provider=$4 WHERE id=$1 AND browser_session_hash=$2 AND csrf_token_hash=$3 AND approved_at IS NULL AND expires_at>now()`,[id,browserSessionHash,csrfTokenHash,provider]);
    return Boolean(r.rowCount);
  }
  async consumeLoginState(id: string, browserSessionHash:string, provider:"google"|"github"): Promise<LoginState | null> {
    const r = await this.pool.query(`DELETE FROM oauth_login_states WHERE id=$1 AND browser_session_hash=$2 AND provider=$3 AND approved_at IS NOT NULL AND expires_at>now() RETURNING *`, [id,browserSessionHash,provider]);
    if (!r.rowCount) return null;
    const x = r.rows[0]; return { id:x.id, clientId:x.client_id, redirectUri:x.redirect_uri, state:x.oauth_state, codeChallenge:x.code_challenge, resource:x.resource, scope:x.scope };
  }
  async upsertIdentity(provider: string, providerSubject: string, displayName: string | null, email: string | null): Promise<string> {
    const c = await this.pool.connect();
    try { await c.query("BEGIN");
      let r = await c.query(`SELECT user_id FROM oauth_identities WHERE provider=$1 AND provider_subject=$2 FOR UPDATE`, [provider, providerSubject]);
      let userId: string;
      if (r.rowCount) userId = r.rows[0].user_id;
      else { userId=randomUUID(); await c.query(`INSERT INTO users(id,display_name,email) VALUES ($1,$2,$3)`,[userId,displayName,email]); await c.query(`INSERT INTO oauth_identities(provider,provider_subject,user_id) VALUES ($1,$2,$3)`,[provider,providerSubject,userId]); }
      await c.query("COMMIT"); return userId;
    } catch(e) { await c.query("ROLLBACK"); throw e; } finally { c.release(); }
  }
  async createAuthorizationCode(state: LoginState, userId: string, ttlSeconds: number): Promise<string> {
    const code=randomTokenCompat(); await this.pool.query(`INSERT INTO oauth_codes(code_hash,user_id,client_id,redirect_uri,code_challenge,resource,scope,expires_at) VALUES ($1,$2,$3,$4,$5,$6,$7,now()+($8*interval '1 second'))`,[sha256(code),userId,state.clientId,state.redirectUri,state.codeChallenge,state.resource,state.scope,ttlSeconds]); return code;
  }
  async consumeAuthorizationCode(code: string): Promise<AuthorizationCode | null> {
    const r=await this.pool.query(`DELETE FROM oauth_codes WHERE code_hash=$1 AND expires_at>now() RETURNING *`,[sha256(code)]); if(!r.rowCount)return null; const x=r.rows[0]; return {id:"",userId:x.user_id,clientId:x.client_id,redirectUri:x.redirect_uri,state:"",codeChallenge:x.code_challenge,resource:x.resource,scope:x.scope};
  }
  async createRefreshToken(userId:string,clientId:string,scope:string,ttlSeconds:number):Promise<string>{const t=randomTokenCompat();await this.pool.query(`INSERT INTO refresh_tokens(token_hash,user_id,client_id,scope,expires_at) VALUES($1,$2,$3,$4,now()+($5*interval '1 second'))`,[sha256(t),userId,clientId,scope,ttlSeconds]);return t;}
  async rotateRefreshToken(token:string,clientId:string,ttlSeconds:number){const c=await this.pool.connect();try{await c.query("BEGIN");const r=await c.query(`DELETE FROM refresh_tokens WHERE token_hash=$1 AND client_id=$2 AND revoked_at IS NULL AND expires_at>now() RETURNING user_id,scope`,[sha256(token),clientId]);if(!r.rowCount){await c.query("ROLLBACK");return null;}const next=randomTokenCompat();await c.query(`INSERT INTO refresh_tokens(token_hash,user_id,client_id,scope,expires_at) VALUES($1,$2,$3,$4,now()+($5*interval '1 second'))`,[sha256(next),r.rows[0].user_id,clientId,r.rows[0].scope,ttlSeconds]);await c.query("COMMIT");return{token:next,userId:r.rows[0].user_id as string,scope:r.rows[0].scope as string};}catch(e){await c.query("ROLLBACK");throw e;}finally{c.release();}}
  async revokeRefreshToken(token:string){await this.pool.query(`UPDATE refresh_tokens SET revoked_at=now() WHERE token_hash=$1`,[sha256(token)]);}
  async getWallet(userId:string){const r=await this.pool.query(`SELECT cdp_account_name,address FROM wallets WHERE user_id=$1`,[userId]);return r.rowCount?{accountName:r.rows[0].cdp_account_name as string,address:r.rows[0].address as string|null}:null;}
  async saveWallet(userId:string,accountName:string,address:string){await this.pool.query(`INSERT INTO wallets(user_id,cdp_account_name,address) VALUES($1,$2,$3) ON CONFLICT(user_id) DO UPDATE SET address=excluded.address`,[userId,accountName,address]);}
  async createPreview(p:Omit<Preview,"id"|"expiresAt">,ttlSeconds:number){const id=randomUUID();const r=await this.pool.query(`INSERT INTO payment_previews(id,user_id,method,url,request_body,fingerprint,amount,pay_to,expires_at) VALUES($1,$2,$3,$4,$5,$6,$7,$8,now()+($9*interval '1 second')) RETURNING expires_at`,[id,p.userId,p.method,p.url,JSON.stringify(p.body),p.fingerprint,p.amount,p.payTo,ttlSeconds]);return{id,expiresAt:r.rows[0].expires_at as Date};}
  async reservePayment(userId:string,previewId:string,dailyLimit:bigint,purpose:string){const c=await this.pool.connect();try{await c.query("BEGIN");await c.query(`SELECT pg_advisory_xact_lock(hashtext($1))`,[userId]);const p=await c.query(`UPDATE payment_previews SET used_at=now() WHERE id=$1 AND user_id=$2 AND used_at IS NULL AND expires_at>now() RETURNING *`,[previewId,userId]);if(!p.rowCount){await c.query("ROLLBACK");return null;}const spent=await c.query(`SELECT COALESCE(sum(amount::numeric),0)::text total FROM payments WHERE user_id=$1 AND created_at>now()-interval '24 hours' AND status IN ('reserved','settled','unknown')`,[userId]);const amount=BigInt(p.rows[0].amount);if(BigInt(spent.rows[0].total)+amount>dailyLimit){await c.query("ROLLBACK");throw new Error("daily spend limit exceeded");}const paymentId=randomUUID();await c.query(`INSERT INTO payments(id,user_id,preview_id,amount,purpose,status) VALUES($1,$2,$3,$4,$5,'reserved')`,[paymentId,userId,previewId,amount.toString(),purpose]);await c.query("COMMIT");const x=p.rows[0];return{paymentId,preview:{id:x.id,userId:x.user_id,method:x.method,url:x.url,body:x.request_body,fingerprint:x.fingerprint,amount:x.amount,payTo:x.pay_to,expiresAt:x.expires_at} as Preview};}catch(e){await c.query("ROLLBACK");throw e;}finally{c.release();}}
  async finishPayment(id:string,status:"settled"|"failed"|"unknown",transaction:string|null,responseStatus:number|null,error:string|null){await this.pool.query(`UPDATE payments SET status=$2,transaction_hash=$3,response_status=$4,error=$5,completed_at=now() WHERE id=$1`,[id,status,transaction,responseStatus,error]);}
}

function mapClient(x:any):OAuthClient{return{clientId:x.client_id,clientName:x.client_name,redirectUris:x.redirect_uris};}
function randomTokenCompat(){return randomUUID()+randomUUID().replaceAll("-","");}
export function databaseTls(databaseUrl:string){const url=new URL(databaseUrl);if(url.searchParams.get("sslmode")==="disable"||url.hostname==="localhost"||url.hostname==="127.0.0.1"||url.hostname.endsWith(".railway.internal"))return undefined;return{rejectUnauthorized:false};}
