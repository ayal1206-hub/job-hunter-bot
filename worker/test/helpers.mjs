// Test doubles: in-memory KV and a scripted fetch that records every call.
import { signInitData } from "../src/auth.js";

export class FakeKV {
  constructor() { this.map = new Map(); }
  async get(k) { return this.map.has(k) ? this.map.get(k) : null; }
  async put(k, v) { this.map.set(k, String(v)); }
  async delete(k) { this.map.delete(k); }
  async list({ prefix = "", cursor } = {}) {
    const keys = [...this.map.keys()].filter((k) => k.startsWith(prefix)).sort().map((name) => ({ name }));
    return { keys, list_complete: true, cursor: undefined };
  }
}

export const TOKEN = "123456:TEST-token";
export const OWNER = 276824695;

export function makeEnv(extra = {}) {
  return {
    USERS: new FakeKV(),
    TELEGRAM_BOT_TOKEN: TOKEN,
    GEMINI_API_KEY: "gem-key",
    GEMINI_MODELS: "gone-model,good-model",
    WEBHOOK_SECRET: "hook-secret",
    OWNER_ID: String(OWNER),
    JOBS_URL: "https://pages.example/jobs.json",
    ...extra,
  };
}

const res = (body, status = 200) => new Response(typeof body === "string" ? body : JSON.stringify(body), { status });

/** routes: { jobs, gemini: object|fn|status, file: Uint8Array } */
export function makeFetch(routes = {}) {
  const calls = [];
  const fn = async (url, init = {}) => {
    const u = String(url);
    const body = init.body ? (() => { try { return JSON.parse(init.body); } catch { return init.body; } })() : undefined;
    calls.push({ url: u, body, headers: init.headers });
    if (u === "https://pages.example/jobs.json") return res(routes.jobs || { jobs: [], fields: [] });
    if (u.includes("generativelanguage.googleapis.com")) {
      if (u.includes("gone-model")) return res({ error: "not found" }, 404);
      if (typeof routes.gemini === "number") return res({ error: "x" }, routes.gemini);
      const answer = typeof routes.gemini === "function" ? routes.gemini(body) : routes.gemini;
      return res({ candidates: [{ content: { parts: [{ text: JSON.stringify(answer) }] } }] });
    }
    if (u.includes("/file/bot")) return new Response(routes.file || new Uint8Array([37, 80, 68, 70]));
    if (u.includes("api.telegram.org")) {
      const method = u.split("/").pop();
      if (method === "getFile") return res({ ok: true, result: { file_path: "documents/cv.pdf" } });
      if (method === "sendMessage" && routes.blocked) return res({ ok: false, error_code: 403, description: "blocked" });
      return res({ ok: true, result: {} });
    }
    throw new Error("unexpected fetch " + u);
  };
  fn.calls = calls;
  fn.sent = () => calls.filter((c) => c.url.endsWith("/sendMessage")).map((c) => c.body);
  return fn;
}

export async function initData(user, authDate = Math.floor(Date.now() / 1000)) {
  const fields = { auth_date: String(authDate), query_id: "q1", user: JSON.stringify(user) };
  const hash = await signInitData(fields, TOKEN);
  return new URLSearchParams({ ...fields, hash }).toString();
}

export function job(over = {}) {
  return {
    key: "comeet:Acme:1", source: "comeet", origin: "board", company: "Acme", title: "QA Student",
    location: "Tel Aviv", region: "center", url: "https://jobs/1", field: "qa", field_label: "QA",
    level: "student", employment: "student", years: null, hybrid: false, first_seen: "2026-10-30",
    owner_only: false, ...over,
  };
}
