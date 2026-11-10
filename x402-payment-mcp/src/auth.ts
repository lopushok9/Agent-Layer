import { OAuthError, OAuthErrorCode, type OAuthTokenVerifier } from "@modelcontextprotocol/server";
import type { Config } from "./config.js";
import { isPersonalToken, type TokenService } from "./security.js";
import type { Store } from "./store.js";

// Accepts both short-lived OAuth access tokens (JWT) and personal access
// tokens. Either way the result carries the user id the MCP session is bound
// to; personal tokens are looked up by hash and must be unrevoked and unexpired.
export function createTokenVerifier(config: Config, tokens: TokenService, store: Pick<Store, "verifyPersonalToken">, resource: string = config.resource): OAuthTokenVerifier {
  return {
    async verifyAccessToken(token) {
      if (isPersonalToken(token)) {
        // Personal tokens are issued for the x402 resource only.
        if (resource !== config.resource) throw new OAuthError(OAuthErrorCode.InvalidToken, "personal access tokens are not accepted by this resource");
        const pat = await store.verifyPersonalToken(token);
        if (!pat) throw new OAuthError(OAuthErrorCode.InvalidToken, "invalid, expired or revoked personal access token");
        return { token, clientId: `pat:${pat.id}`, scopes: pat.scope.split(" ").filter(Boolean), expiresAt: Math.floor(pat.expiresAt.getTime() / 1000), resource: new URL(config.resource), extra: { userId: pat.userId } };
      }
      try {
        const v = await tokens.verifyAccessToken(token, resource);
        return { token, clientId: v.clientId, scopes: v.scopes, expiresAt: v.expiresAt, resource: new URL(resource), extra: { userId: v.userId } };
      } catch {
        throw new OAuthError(OAuthErrorCode.InvalidToken, "invalid or expired access token");
      }
    },
  };
}
