import { createHash, randomBytes, timingSafeEqual } from "node:crypto";
import { calculateJwkThumbprint, importJWK, jwtVerify, SignJWT } from "jose";
import type { Config } from "./config.js";

export const randomToken = (bytes = 32) => randomBytes(bytes).toString("base64url");
export const sha256 = (value: string) => createHash("sha256").update(value).digest("base64url");
export const pkceChallenge = sha256;

export function safeEqual(a: string, b: string): boolean {
  const left = Buffer.from(a);
  const right = Buffer.from(b);
  return left.length === right.length && timingSafeEqual(left, right);
}

export class TokenService {
  private constructor(
    private readonly config: Config,
    private readonly privateKey: CryptoKey,
    private readonly publicKey: CryptoKey,
    readonly publicJwk: Record<string, unknown>,
    readonly kid: string,
  ) {}

  static async create(config: Config): Promise<TokenService> {
    const privateKey = (await importJWK(config.privateJwk, "ES256")) as CryptoKey;
    const publicJwk={...config.privateJwk};
    delete publicJwk.d;
    const kid = await calculateJwkThumbprint(publicJwk);
    const publicKey=(await importJWK(publicJwk,"ES256")) as CryptoKey;
    return new TokenService(config, privateKey, publicKey, { ...publicJwk, use: "sig", alg: "ES256", kid }, kid);
  }

  async accessToken(userId: string, clientId: string, scopes: string[]): Promise<string> {
    return new SignJWT({ client_id: clientId, scope: scopes.join(" ") })
      .setProtectedHeader({ alg: "ES256", kid: this.kid, typ: "at+jwt" })
      .setIssuer(this.config.issuer).setSubject(userId).setAudience(this.config.resource)
      .setIssuedAt().setExpirationTime(`${this.config.ACCESS_TOKEN_TTL_SECONDS}s`).setJti(randomToken(16))
      .sign(this.privateKey);
  }

  async verifyAccessToken(token: string) {
    const { payload } = await jwtVerify(token, this.publicKey, {
      issuer: this.config.issuer,
      audience: this.config.resource,
      algorithms: ["ES256"],
      typ: "at+jwt",
    });
    if (!payload.sub || typeof payload.client_id !== "string" || typeof payload.exp !== "number") throw new Error("invalid access token");
    return {
      userId: payload.sub,
      clientId: payload.client_id,
      scopes: typeof payload.scope === "string" ? payload.scope.split(" ").filter(Boolean) : [],
      expiresAt: payload.exp,
    };
  }

  async serviceRef(resource: string): Promise<string> {
    return new SignJWT({ resource })
      .setProtectedHeader({ alg: "ES256", kid: this.kid, typ: "bazaar-resource+jwt" })
      .setIssuer(this.config.issuer).setAudience("x402-bazaar-resource").setIssuedAt().setExpirationTime("1h")
      .sign(this.privateKey);
  }

  async verifyServiceRef(token: string): Promise<string> {
    const { payload } = await jwtVerify(token, this.publicKey, {
      issuer: this.config.issuer,
      audience: "x402-bazaar-resource",
      algorithms: ["ES256"],
      typ: "bazaar-resource+jwt",
    });
    if (typeof payload.resource !== "string") throw new Error("invalid service_ref");
    return payload.resource;
  }
}
