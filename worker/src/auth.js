// Verify Telegram Mini App initData (https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app)
// so the API knows which Telegram user is calling, without any login.

const enc = new TextEncoder();

async function hmac(key, data) {
  const k = await crypto.subtle.importKey("raw", typeof key === "string" ? enc.encode(key) : key,
    { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  return new Uint8Array(await crypto.subtle.sign("HMAC", k, enc.encode(data)));
}

const hex = (bytes) => [...bytes].map((b) => b.toString(16).padStart(2, "0")).join("");

function timingSafeEqual(a, b) {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

export async function signInitData(fields, botToken) {
  // Used by tests to build valid initData.
  const check = Object.keys(fields).sort().map((k) => `${k}=${fields[k]}`).join("\n");
  const secret = await hmac("WebAppData", botToken);
  return hex(await hmac(secret, check));
}

/** Returns the Telegram user object, or null if initData is missing, forged or too old. */
export async function verifyInitData(initData, botToken, { maxAgeSec = 86400, now = Date.now() } = {}) {
  if (!initData || !botToken) return null;
  const params = new URLSearchParams(initData);
  const hash = params.get("hash");
  if (!hash) return null;
  params.delete("hash");
  const fields = {};
  for (const [k, v] of params) fields[k] = v;
  const expected = await signInitData(fields, botToken);
  if (!timingSafeEqual(expected, hash)) return null;
  const authDate = Number(fields.auth_date || 0);
  if (!authDate || now / 1000 - authDate > maxAgeSec) return null;
  try {
    const user = JSON.parse(fields.user || "null");
    return user && typeof user.id === "number" ? user : null;
  } catch {
    return null;
  }
}

export async function sha256Hex(text) {
  return hex(new Uint8Array(await crypto.subtle.digest("SHA-256", enc.encode(text))));
}
