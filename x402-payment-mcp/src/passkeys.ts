import express, { type Request, type Response, type Router } from "express";
import { generateAuthenticationOptions, generateRegistrationOptions, verifyAuthenticationResponse, verifyRegistrationResponse, type AuthenticationResponseJSON, type RegistrationResponseJSON } from "@simplewebauthn/server";
import type { Config } from "./config.js";
import { safeEqual, sha256 } from "./security.js";
import type { LoginState, Store } from "./store.js";

type ShowConsent = (res: Response, state: LoginState, userId: string, offerPasskey: boolean) => Promise<void>;
type Helpers = {
  asyncRoute: (fn: (req: Request, res: Response) => Promise<unknown>) => express.RequestHandler;
  limits: (req: Request, store: Store, bucket: string, perIp: number, windowSeconds: number, global: number) => Promise<boolean>;
  jsonError: (res: Response, status: number, error: string, description: string) => Response;
  errorPage: (res: Response, message: string) => void;
};

// Passkey (WebAuthn) sign-in as one more identity provider: a verified passkey
// yields a user id exactly like a Google or GitHub callback, then the usual
// consent page follows. Wallet keys are untouched. User verification (Face ID,
// fingerprint, device PIN) is required for every ceremony.
export function passkeyRoutes(router: Router, config: Config, store: Store, showConsent: ShowConsent, h: Helpers) {
  const rpID = config.passkeyRpId, origin = new URL(config.issuer).origin;

  router.post("/auth/passkey/options", express.json({ limit: "4kb" }), h.asyncRoute(async (req, res) => {
    res.set("Cache-Control", "no-store");
    const body = (req.body ?? {}) as Record<string, unknown>;
    const mode = body.mode;
    if (mode === "login" || mode === "register") {
      if (!await h.limits(req, store, `passkey_${mode}`, mode === "register" ? 10 : 60, 3600, mode === "register" ? 500 : 5000)) return h.jsonError(res, 429, "temporarily_unavailable", "too many passkey requests");
      const loginState = typeof body.login_state === "string" ? body.login_state : "";
      if (!/^[0-9a-f-]{36}$/i.test(loginState) || !await store.hasLoginState(loginState)) return h.jsonError(res, 400, "invalid_request", "authorization request is invalid or expired");
      // No allowCredentials: the browser offers the passkeys it holds for this
      // site and returns which one was used.
      const options = mode === "login"
        ? await generateAuthenticationOptions({ rpID, userVerification: "required" })
        : await generateRegistrationOptions({ rpName: "AgentLayer", rpID, userName: `AgentLayer ${new Date().toISOString().slice(0, 10)}`, userDisplayName: "AgentLayer wallet", attestationType: "none", authenticatorSelection: { residentKey: "required", userVerification: "required" }, supportedAlgorithmIDs: [-7, -257] });
      const challengeId = await store.createPasskeyChallenge({ purpose: mode, challenge: options.challenge, loginState });
      return res.json({ challenge_id: challengeId, options });
    }
    if (mode === "add") {
      if (!await h.limits(req, store, "passkey_add", 20, 3600, 2000)) return h.jsonError(res, 429, "temporarily_unavailable", "too many passkey requests");
      const consentToken = typeof body.consent_token === "string" ? body.consent_token : "";
      const user = consentToken ? await store.pendingConsentUser(consentToken) : null;
      if (!user) return h.jsonError(res, 400, "invalid_request", "sign in again to add a passkey");
      const existing = await store.passkeyIds(user.userId);
      const options = await generateRegistrationOptions({ rpName: "AgentLayer", rpID, userName: user.name ?? "AgentLayer account", userDisplayName: user.name ?? "AgentLayer wallet", attestationType: "none", authenticatorSelection: { residentKey: "required", userVerification: "required" }, supportedAlgorithmIDs: [-7, -257], excludeCredentials: existing.map(c => ({ id: c.id, transports: c.transports as any })) });
      const challengeId = await store.createPasskeyChallenge({ purpose: "add", challenge: options.challenge, consentToken });
      return res.json({ challenge_id: challengeId, options });
    }
    return h.jsonError(res, 400, "invalid_request", "mode must be login, register or add");
  }));

  // Sign-in and sign-up finish as a form post, so the response is the consent
  // page itself, as after a Google or GitHub callback.
  router.post("/auth/passkey/finish", express.urlencoded({ extended: false, limit: "16kb" }), h.asyncRoute(async (req, res) => {
    const purpose = req.body?.purpose === "register" ? "register" : "login";
    const challenge = await store.consumePasskeyChallenge(String(req.body?.challenge_id ?? ""), purpose);
    if (!challenge?.loginState) return h.errorPage(res, "This passkey request expired. Go back and try again.");
    const credential = parseCredential(req.body?.credential);
    if (!credential) return h.errorPage(res, "The browser returned an invalid passkey response.");
    let userId: string;
    if (purpose === "login") {
      const stored = await store.passkeyCredential(credential.id);
      if (!stored) return h.errorPage(res, "This passkey is not registered with AgentLayer. Create an account with it, or sign in another way.");
      const v = await verifyAuthenticationResponse({ response: credential as unknown as AuthenticationResponseJSON, expectedChallenge: challenge.challenge, expectedOrigin: origin, expectedRPID: rpID, credential: { id: stored.id, publicKey: stored.publicKey as any, counter: stored.counter, transports: stored.transports as any }, requireUserVerification: true }).catch(() => null);
      if (!v?.verified) return h.errorPage(res, "The passkey could not be verified.");
      await store.markPasskeyUsed(stored.id, v.authenticationInfo.newCounter, v.authenticationInfo.credentialBackedUp);
      userId = stored.userId;
    } else {
      const saved = await register(credential, challenge.challenge);
      if (!saved) return h.errorPage(res, "The passkey could not be verified.");
      if (await store.passkeyCredential(saved.id)) return h.errorPage(res, "This passkey is already registered. Sign in with it instead.");
      userId = await store.savePasskey(saved);
    }
    const state = await store.consumeLoginState(challenge.loginState);
    if (!state) return h.errorPage(res, "This sign-in request expired. Start again from your MCP client.");
    await showConsent(res, state, userId, false);
  }));

  // Adds a passkey to the account that is signing in (pending consent token
  // proves it), from the consent page; answers JSON and the page stays.
  router.post("/auth/passkey/add", express.json({ limit: "16kb" }), h.asyncRoute(async (req, res) => {
    res.set("Cache-Control", "no-store");
    const body = (req.body ?? {}) as Record<string, unknown>;
    const challenge = await store.consumePasskeyChallenge(String(body.challenge_id ?? ""), "add");
    const consentToken = typeof body.consent_token === "string" ? body.consent_token : "";
    if (!challenge?.consentTokenHash || !consentToken || !safeEqual(sha256(consentToken), challenge.consentTokenHash)) return h.jsonError(res, 400, "invalid_request", "this passkey request expired; try again");
    const user = await store.pendingConsentUser(consentToken);
    if (!user) return h.jsonError(res, 400, "invalid_request", "sign in again to add a passkey");
    const credential = parseCredential(body.credential);
    const saved = credential ? await register(credential, challenge.challenge) : null;
    if (!saved) return h.jsonError(res, 400, "invalid_request", "the passkey could not be verified");
    if (await store.passkeyCredential(saved.id)) return h.jsonError(res, 409, "invalid_request", "this passkey is already registered");
    await store.savePasskey(saved, user.userId);
    return res.json({ ok: true, backed_up: saved.backedUp });
  }));

  async function register(credential: Record<string, unknown>, expectedChallenge: string) {
    const v = await verifyRegistrationResponse({ response: credential as unknown as RegistrationResponseJSON, expectedChallenge, expectedOrigin: origin, expectedRPID: rpID, requireUserVerification: true }).catch(() => null);
    if (!v?.verified) return null;
    const { credential: c, credentialDeviceType, credentialBackedUp } = v.registrationInfo;
    return { id: c.id, publicKey: c.publicKey as Uint8Array, counter: c.counter, transports: (c.transports ?? []).filter(t => typeof t === "string").slice(0, 8), deviceType: credentialDeviceType, backedUp: credentialBackedUp };
  }
}

function parseCredential(raw: unknown): Record<string, unknown> & { id: string } | null {
  if (typeof raw === "string") { try { raw = JSON.parse(raw); } catch { return null; } }
  if (!raw || typeof raw !== "object") return null;
  const c = raw as Record<string, unknown>;
  if (typeof c.id !== "string" || !/^[A-Za-z0-9_-]{16,1366}$/.test(c.id) || c.type !== "public-key" || !c.response || typeof c.response !== "object") return null;
  return c as Record<string, unknown> & { id: string };
}


// Browser side, inlined under the page's CSP nonce: base64url <-> ArrayBuffer
// around navigator.credentials, returning the JSON the server verifies.
export function passkeyBrowserScript() {
  return `var b64=function(v){var a=new Uint8Array(v),s="";for(var i=0;i<a.length;i++)s+=String.fromCharCode(a[i]);return btoa(s).replace(/\\+/g,"-").replace(/\\//g,"_").replace(/=+$/,"");};
var bin=function(s){s=s.replace(/-/g,"+").replace(/_/g,"/");while(s.length%4)s+="=";var r=atob(s),a=new Uint8Array(r.length);for(var i=0;i<r.length;i++)a[i]=r.charCodeAt(i);return a.buffer;};
var ids=function(l){return(l||[]).map(function(c){return{type:c.type,id:bin(c.id),transports:c.transports};});};
var passkey=async function(body){
if(!window.PublicKeyCredential||!navigator.credentials)throw new Error("This browser does not support passkeys.");
var r=await fetch("/auth/passkey/options",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)}),j=await r.json();
if(!r.ok)throw new Error(j.error_description||"Passkeys are unavailable right now.");
var o=j.options,c,resp;o.challenge=bin(o.challenge);
if(body.mode==="login"){o.allowCredentials=ids(o.allowCredentials);c=await navigator.credentials.get({publicKey:o});resp={authenticatorData:b64(c.response.authenticatorData),clientDataJSON:b64(c.response.clientDataJSON),signature:b64(c.response.signature)};if(c.response.userHandle)resp.userHandle=b64(c.response.userHandle);}
else{o.user.id=bin(o.user.id);o.excludeCredentials=ids(o.excludeCredentials);c=await navigator.credentials.create({publicKey:o});resp={clientDataJSON:b64(c.response.clientDataJSON),attestationObject:b64(c.response.attestationObject),transports:c.response.getTransports?c.response.getTransports():[]};}
return{challenge_id:j.challenge_id,credential:JSON.stringify({id:c.id,rawId:b64(c.rawId),type:c.type,response:resp,clientExtensionResults:c.getClientExtensionResults?c.getClientExtensionResults():{},authenticatorAttachment:c.authenticatorAttachment||undefined})};};
var passkeyError=function(e){return e&&e.name==="NotAllowedError"?"Passkey request was cancelled or timed out.":e&&e.name==="InvalidStateError"?"This passkey is already registered here.":(e&&e.message)||"Passkey failed.";};`;
}
