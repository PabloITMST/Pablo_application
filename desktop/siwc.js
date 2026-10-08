// M4.1 Sign in with ChatGPT (token sharing for open-source local apps). Main process only: tokens never reach the renderer.
// https://developers.openai.com/siwc/token-sharing-open-source — no official helper library, so: PKCE + state + nonce,
// loopback callback on 127.0.0.1, ID token checked against OpenAI's JWKS. Node/Electron built-ins only.
// Files in `dir` (Electron userData): host.json (host id, issued client_id, account — not secret),
// credentials.bin (tokens, encrypted with Electron safeStorage = Windows DPAPI / macOS Keychain).
const crypto = require("crypto");
const fs = require("fs");
const http = require("http");
const path = require("path");

const ISSUER = "https://auth.openai.com", API = "https://api.openai.com/v1";
const EP = {  // from https://auth.openai.com/.well-known/openid-configuration; check.js points these at a local fake
  issuer: ISSUER, authorize: ISSUER + "/api/accounts/authorize", token: ISSUER + "/api/accounts/oauth/token",
  revoke: ISSUER + "/api/accounts/oauth/revoke", jwks: ISSUER + "/.well-known/jwks.json", api: API,
};
const SCOPE = "openid profile email offline_access resource.invoke chatgpt.tokens.use.direct";
const PLAN = "chatgpt.tokens.use.direct";

// short user-facing messages; raw OAuth/JSON stays in the console
const SAY = {
  cancelled: "로그인을 취소했습니다.", access_denied: "ChatGPT 권한 승인을 거절했습니다.",
  state_mismatch: "로그인 응답이 이 요청과 맞지 않습니다. 다시 시도하세요.", callback_failed: "로그인 응답을 받지 못했습니다.",
  timeout: "로그인 시간이 지났습니다. 다시 시도하세요.", exchange_failed: "로그인을 마치지 못했습니다. 다시 시도하세요.",
  bad_id_token: "로그인 응답을 검증하지 못했습니다.", no_plan_permission: "ChatGPT plan usage 권한이 없습니다. 로그인할 때 권한을 허용해야 합니다.",
  refresh_failed: "ChatGPT 연결이 만료되었습니다. 다시 로그인하세요.", network: "OpenAI에 연결하지 못했습니다. 네트워크를 확인하세요.",
  not_eligible: "이 계정이나 workspace에서는 ChatGPT plan usage를 쓸 수 없습니다.", usage_limit: "ChatGPT 사용 한도에 도달했습니다.",
  usage_unavailable: "ChatGPT 사용량 확인이 잠시 안 됩니다. 잠시 뒤 다시 시도하세요.", no_models: "이 계정에서 쓸 수 있는 모델이 없습니다.",
  unauthorized: "ChatGPT가 인증을 거부했습니다. 다시 로그인하세요.", inference_failed: "ChatGPT 응답 확인에 실패했습니다.",
  overloaded: "선택한 모델이 지금 붐빕니다. 다른 모델을 고르거나 잠시 뒤 다시 시도하세요.",
};
class AuthError extends Error {
  constructor(code, detail) { super(SAY[code] || code); this.code = code; this.detail = detail; }
}
// OpenAI error code / HTTP status -> one of SAY's keys
function classify(code, status) {
  if (/usage_limit|rate_limit/.test(code) || status === 429) return "usage_limit";
  if (/not_eligible|chatpass_v2|route_not_supported/.test(code)) return "not_eligible";
  if (/usage_unavailable|user_unavailable/.test(code) || status === 503) return "usage_unavailable";
  if (/invalid_user|invalid_api_key/.test(code) || status === 401) return "unauthorized";
  return status === 403 ? "not_eligible" : "inference_failed";
}

const b64u = buf => Buffer.from(buf).toString("base64url");
const rand = () => b64u(crypto.randomBytes(32));
let dir, safe, pending = null, refreshing = null;

function init(userData, safeStorage) { dir = userData; safe = safeStorage; fs.mkdirSync(dir, { recursive: true }); }
const file = n => path.join(dir, n);
function writeAtomic(name, data) {
  const tmp = file(name + ".tmp");
  fs.writeFileSync(tmp, data, { mode: 0o600 }); fs.renameSync(tmp, file(name));
}
function host() {  // stable per installation; the issued client_id is reused for every later sign-in
  try { return JSON.parse(fs.readFileSync(file("host.json"), "utf8")); }
  catch { const h = { ext_agent_host_id: "urn:uuid:" + crypto.randomUUID() }; writeAtomic("host.json", JSON.stringify(h)); return h; }
}
function creds() {
  try { return JSON.parse(safe.decryptString(fs.readFileSync(file("credentials.bin")))); } catch { return null; }
}
const saveCreds = c => writeAtomic("credentials.bin", safe.encryptString(JSON.stringify(c)));
const dropCreds = () => fs.rmSync(file("credentials.bin"), { force: true });

async function post(url, form) {
  let r;
  try { r = await fetch(url, { method: "POST", headers: { "content-type": "application/x-www-form-urlencoded" }, body: new URLSearchParams(form) }); }
  catch (e) { throw new AuthError("network", e.message); }
  const body = await r.json().catch(() => ({}));
  return { ok: r.ok, status: r.status, body };
}

// ---- ID token: RS256 signature against the JWKS, iss, aud = issued client_id, exp, nonce -------------------------
async function checkIdToken(jwt, clientId, nonce) {
  const [h, p, s] = String(jwt).split(".");
  const head = JSON.parse(Buffer.from(h, "base64url")), claims = JSON.parse(Buffer.from(p, "base64url"));
  const keys = (await (await fetch(EP.jwks)).json()).keys;
  const jwk = keys.find(k => k.kid === head.kid) || (keys.length === 1 && keys[0]);
  if (head.alg !== "RS256" || !jwk) throw new Error("unknown key " + head.kid);
  if (!crypto.verify("sha256", Buffer.from(h + "." + p), crypto.createPublicKey({ key: jwk, format: "jwk" }), Buffer.from(s, "base64url")))
    throw new Error("signature");
  const aud = [].concat(claims.aud);
  if (claims.iss !== EP.issuer) throw new Error("iss " + claims.iss);
  if (!aud.includes(clientId)) throw new Error("aud");
  if (!(claims.exp * 1000 > Date.now())) throw new Error("expired");
  if (claims.nonce !== nonce) throw new Error("nonce");
  return claims;
}

// ---- sign in: browser -> loopback callback -> code exchange -> validated, encrypted credentials --------------------
// openUrl: shell.openExternal. Resolves with the saved account; rejects with AuthError.
function login(openUrl, waitMs = 5 * 60 * 1000) {
  if (pending) pending.cancel();
  const h = host(), old = creds();
  const verifier = rand(), state = rand(), nonce = rand();
  let cancel;
  const done = new Promise((resolve, reject) => {
    const srv = http.createServer((q, s) => {
      const u = new URL(q.url, "http://127.0.0.1");
      if (u.pathname !== "/auth/callback") { s.writeHead(404); return s.end(); }
      const p = Object.fromEntries(u.searchParams);
      const ok = !p.error && p.state === state && p.code;
      s.writeHead(200, { "content-type": "text/html; charset=utf-8" });
      s.end(`<!doctype html><meta charset=utf-8><title>Pablo</title><body style="font:16px system-ui;margin:3em">${ok ? "로그인했습니다. Pablo로 돌아가세요." : "로그인하지 못했습니다. Pablo에서 다시 시도하세요."}</body>`);
      finish(p.error === "access_denied" ? new AuthError("access_denied", p.error_description)
        : p.error ? new AuthError("callback_failed", p.error + " " + (p.error_description || ""))
        : p.state !== state ? new AuthError("state_mismatch")
        : !p.code ? new AuthError("callback_failed", "no code") : null, p);
    });
    const timer = setTimeout(() => finish(new AuthError("timeout")), waitMs);
    let over = false;
    function finish(err, p) {
      if (over) return; over = true; clearTimeout(timer); srv.close(); pending = null;
      if (err) return reject(err);
      exchange(p).then(resolve, reject);
    }
    cancel = () => finish(new AuthError("cancelled"));
    srv.on("error", e => finish(new AuthError("callback_failed", e.message)));
    srv.listen(0, "127.0.0.1", () => {
      const redirect = `http://127.0.0.1:${srv.address().port}/auth/callback`;
      const q = { client_id: h.client_id || "dynamic_agent_client", response_type: "code", redirect_uri: redirect, scope: SCOPE,
        resource: API, state, nonce, code_challenge_method: "S256", code_challenge: b64u(crypto.createHash("sha256").update(verifier).digest()),
        ext_agent_host_id: h.ext_agent_host_id };
      if (!h.client_id) q.agent_name_hint = "Pablo";  // first registration only
      else if (old && old.id_token) q.id_token_hint = old.id_token;
      else if (h.email) q.login_hint = h.email;
      exchange.redirect = redirect;
      Promise.resolve(openUrl(EP.authorize + "?" + new URLSearchParams(q))).catch(e => finish(new AuthError("callback_failed", e.message)));
    });
  });

  async function exchange(p) {
    // a new registration names its client in the callback; a known client must not change
    if (h.client_id && p.client_id && p.client_id !== h.client_id) throw new AuthError("callback_failed", "client_id changed");
    const clientId = p.client_id || h.client_id;
    if (!clientId) throw new AuthError("callback_failed", "no client_id");
    const r = await post(EP.token, { grant_type: "authorization_code", client_id: clientId, code: p.code,
      code_verifier: verifier, redirect_uri: exchange.redirect, resource: API });
    if (!r.ok || !r.body.access_token) throw new AuthError("exchange_failed", `${r.status} ${r.body.error || ""}`);
    let id;
    try { id = await checkIdToken(r.body.id_token, clientId, nonce); } catch (e) { throw new AuthError("bad_id_token", e.message); }
    const scopes = String(r.body.scope || "").split(/\s+/).filter(Boolean);
    Object.assign(h, { client_id: clientId, subject: id.sub, email: id.email || h.email });
    writeAtomic("host.json", JSON.stringify(h));  // keep the issued client even if plan usage was refused
    if (!scopes.includes(PLAN)) throw new AuthError("no_plan_permission", scopes.join(" "));
    const c = { client_id: clientId, subject: id.sub, email: id.email, id_token: r.body.id_token, access_token: r.body.access_token,
      refresh_token: r.body.refresh_token, expires_at: Date.now() + (r.body.expires_in || 3600) * 1000, scopes, saved_at: new Date().toISOString() };
    saveCreds(c);
    return { subject: c.subject, changed: !!old && old.subject !== c.subject };
  }
  pending = { cancel };
  return done;
}
const cancelLogin = () => pending && pending.cancel();

// ---- access token: refreshed when < 5 min left (single flight: a reused refresh token is revoked) -------------------
async function token(force = false) {
  const c = creds();
  if (!c) return null;
  if (!force && c.expires_at - Date.now() > 5 * 60 * 1000) return c.access_token;
  refreshing = refreshing || (async () => {
    const r = await post(EP.token, { grant_type: "refresh_token", client_id: c.client_id, refresh_token: c.refresh_token });
    if (!r.ok || !r.body.access_token) {
      if (r.status >= 400 && r.status < 500) dropCreds();  // invalid_grant / expired / reused / invalidated: sign in again
      throw new AuthError("refresh_failed", `${r.status} ${r.body.error || ""}`);
    }
    Object.assign(c, { access_token: r.body.access_token, refresh_token: r.body.refresh_token || c.refresh_token,
      id_token: r.body.id_token || c.id_token, expires_at: Date.now() + (r.body.expires_in || 3600) * 1000, saved_at: new Date().toISOString() });
    saveCreds(c);
    return c.access_token;
  })().finally(() => { refreshing = null; });
  return refreshing;
}
const expiresAt = () => (creds() || {}).expires_at || 0;

// ---- plan usage: account model catalog + one tiny streamed inference must both succeed -----------------------------
async function models(access) {  // account-specific catalog (app-server's model/list may be a bundled/cached list)
  let r;
  try { r = await fetch(EP.api + "/models", { headers: { authorization: "Bearer " + access } }); } catch (e) { throw new AuthError("network", e.message); }
  const body = await r.json().catch(() => ({}));
  if (!r.ok) throw new AuthError(classify(body.error && body.error.code || "", r.status), JSON.stringify(body).slice(0, 300));
  const list = (body.models || body.data || []).filter(m => (m.visibility || "list") === "list").map(m => ({ slug: m.slug || m.id, name: m.display_name || m.slug || m.id })).filter(m => m.slug);
  if (!list.length) throw new AuthError("no_models");
  return list;
}
async function ping(access, model) {
  let r;
  try {
    r = await fetch(EP.api + "/responses", { method: "POST", headers: { authorization: "Bearer " + access, "content-type": "application/json" },
      body: JSON.stringify({ model, instructions: "Reply with OK.", input: [{ role: "user", content: [{ type: "input_text", text: "ping" }] }], store: false, stream: true }) });
  } catch (e) { throw new AuthError("network", e.message); }
  const text = await r.text();  // tiny response; read it whole
  if (!r.ok) { let e = {}; try { e = JSON.parse(text).error || {}; } catch {} throw new AuthError(classify(e.code || "", r.status), text.slice(0, 300)); }
  const events = text.split("\n").filter(l => l.startsWith("data:")).map(l => { try { return JSON.parse(l.slice(5)); } catch { return {}; } });
  if (events.some(e => e.type === "response.completed")) return true;
  const f = events.find(e => e.type === "response.failed" || e.type === "error" || e.type === "response.incomplete") || {};
  const err = (f.response && f.response.error) || f.error || {};
  throw new AuthError(classify(err.code || f.code || "", 0), JSON.stringify(f).slice(0, 300));
}
async function verify() {
  const access = await token();
  if (!access) return null;
  const list = await models(access);
  await ping(access, list[0].slug);
  return { access, models: list };
}

// ---- sign out: revoke the renewable session, then forget tokens (host id + issued client stay for the next sign-in) --
async function logout() {
  cancelLogin();
  const c = creds();
  let revoked = !c;
  if (c) {
    try { revoked = (await post(EP.revoke, { token: c.refresh_token, token_type_hint: "refresh_token", client_id: c.client_id })).ok; } catch { revoked = false; }
  }
  dropCreds();
  return { revoked };
}

module.exports = { EP, AuthError, SAY, classify, init, login, cancelLogin, token, expiresAt, models, verify, logout, has: () => !!creds() };
