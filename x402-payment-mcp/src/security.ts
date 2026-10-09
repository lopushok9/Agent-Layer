import { createHash, randomBytes, timingSafeEqual } from "node:crypto";
import { calculateJwkThumbprint, decodeProtectedHeader, importJWK, jwtVerify, SignJWT } from "jose";
import type { Config } from "./config.js";

export const randomToken = (bytes = 32) => randomBytes(bytes).toString("base64url");

// Prefixed so secret scanners can recognize a leaked token.
export const PERSONAL_TOKEN_PREFIX = "alx402_";
export const newPersonalToken = () => `${PERSONAL_TOKEN_PREFIX}${randomToken(32)}`;
export const isPersonalToken = (value: string) => value.startsWith(PERSONAL_TOKEN_PREFIX);

const TOKEN_MANAGER_STATE_TYP = "token-manager-state+jwt";
export function isTokenManagerState(value: string): boolean {
  try { return decodeProtectedHeader(value).typ === TOKEN_MANAGER_STATE_TYP; } catch { return false; }
}
const LINK_CONNECT_STATE_TYP = "link-connect-state+jwt";
export function isLinkConnectState(value: string): boolean {
  try { return decodeProtectedHeader(value).typ === LINK_CONNECT_STATE_TYP; } catch { return false; }
}
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

  async providerState(loginStateId: string, provider: "google" | "github"): Promise<string> {
    return new SignJWT({ login_state: loginStateId, provider })
      .setProtectedHeader({ alg: "ES256", kid: this.kid, typ: "oauth-provider-state+jwt" })
      .setIssuer(this.config.issuer).setAudience("oauth-provider-callback")
      .setIssuedAt().setExpirationTime("10m").setJti(randomToken(16))
      .sign(this.privateKey);
  }

  async verifyProviderState(token: string, provider: "google" | "github"): Promise<string> {
    const { payload } = await jwtVerify(token, this.publicKey, {
      issuer: this.config.issuer,
      audience: "oauth-provider-callback",
      algorithms: ["ES256"],
      typ: "oauth-provider-state+jwt",
    });
    if (payload.provider !== provider || typeof payload.login_state !== "string") throw new Error("invalid OAuth provider state");
    return payload.login_state;
  }

  // Personal-token sign-in reuses the provider callback URLs registered with
  // Google/GitHub, so its state is a distinct JWT type the callback can tell
  // apart from an MCP client's OAuth login state.
  async tokenManagerState(loginStateId: string, provider: "google" | "github"): Promise<string> {
    return new SignJWT({ login_state: loginStateId, provider })
      .setProtectedHeader({ alg: "ES256", kid: this.kid, typ: TOKEN_MANAGER_STATE_TYP })
      .setIssuer(this.config.issuer).setAudience("token-manager-callback")
      .setIssuedAt().setExpirationTime("10m").setJti(randomToken(16))
      .sign(this.privateKey);
  }

  async verifyTokenManagerState(token: string, provider: "google" | "github"): Promise<string> {
    const { payload } = await jwtVerify(token, this.publicKey, {
      issuer: this.config.issuer,
      audience: "token-manager-callback",
      algorithms: ["ES256"],
      typ: TOKEN_MANAGER_STATE_TYP,
    });
    if (payload.provider !== provider || typeof payload.login_state !== "string") throw new Error("invalid token manager state");
    return payload.login_state;
  }

  // Connecting a Link wallet re-confirms the user's identity through the same
  // Google/GitHub callbacks, so this state is another distinct JWT type.
  // attemptId is null for the standing /link page, where the attempt is
  // created for whoever signs in.
  async linkConnectState(attemptId: string | null, provider: "google" | "github"): Promise<string> {
    return new SignJWT({ attempt: attemptId ?? "", provider })
      .setProtectedHeader({ alg: "ES256", kid: this.kid, typ: LINK_CONNECT_STATE_TYP })
      .setIssuer(this.config.issuer).setAudience("link-connect-callback")
      .setIssuedAt().setExpirationTime("10m").setJti(randomToken(16))
      .sign(this.privateKey);
  }

  async verifyLinkConnectState(token: string, provider: "google" | "github"): Promise<string | null> {
    const { payload } = await jwtVerify(token, this.publicKey, {
      issuer: this.config.issuer,
      audience: "link-connect-callback",
      algorithms: ["ES256"],
      typ: LINK_CONNECT_STATE_TYP,
    });
    if (payload.provider !== provider || typeof payload.attempt !== "string") throw new Error("invalid Link connect state");
    return payload.attempt || null;
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
