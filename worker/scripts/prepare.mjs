// Deploy helper (run in GitHub Actions):
//   node scripts/prepare.mjs kv       -> find or create the KV namespace, write wrangler.toml
//   node scripts/prepare.mjs secrets  -> print the worker secrets as JSON for `wrangler secret bulk`
import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { readFileSync, writeFileSync } from "node:fs";

const TITLE = "jobbot-users";
const wrangler = (...args) => execFileSync("npx", ["wrangler", ...args], { encoding: "utf8" });

function findNamespace() {
  const out = wrangler("kv", "namespace", "list");
  const list = JSON.parse(out.slice(out.indexOf("[")));
  return list.find((n) => n.title === TITLE || n.title.endsWith(`-${TITLE}`));
}

export function webhookSecret(botToken) {
  return createHash("sha256").update(`${botToken}:jobbot-webhook`).digest("hex");
}

const mode = process.argv[2];
if (mode === "kv") {
  let ns = findNamespace();
  if (!ns) {
    wrangler("kv", "namespace", "create", TITLE);
    ns = findNamespace();
  }
  if (!ns) throw new Error("could not create the KV namespace");
  const toml = readFileSync("wrangler.toml.template", "utf8").replace("__KV_ID__", ns.id);
  writeFileSync("wrangler.toml", toml);
  console.log(`KV namespace ${ns.title} (${ns.id})`);
} else if (mode === "secrets") {
  const { TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, GEMINI_API_KEY } = process.env;
  process.stdout.write(JSON.stringify({
    TELEGRAM_BOT_TOKEN, GEMINI_API_KEY,
    OWNER_ID: TELEGRAM_CHAT_ID,
    WEBHOOK_SECRET: webhookSecret(TELEGRAM_BOT_TOKEN),
  }));
} else if (mode === "hook-secret") {
  process.stdout.write(webhookSecret(process.env.TELEGRAM_BOT_TOKEN));
} else {
  console.error("usage: prepare.mjs kv|secrets|hook-secret");
  process.exit(2);
}
