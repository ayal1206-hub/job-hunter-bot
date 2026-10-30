import assert from "node:assert/strict";
import test from "node:test";
import { handleApi, handleUpdate, loadProfile, runAlerts, setup } from "../src/handlers.js";
import { OWNER, initData, job, makeEnv, makeFetch } from "./helpers.mjs";

const ORIGIN = "https://jobbot.example.workers.dev";
const NOW = Date.parse("2026-10-30T10:00:00Z");
const msg = (from, extra) => ({ message: { chat: { id: from, type: "private" }, from: { id: from, first_name: "N" }, ...extra } });
const gemini = {
  fields: ["support"], level: "student", years_experience: 0, regions: ["south"],
  employment: ["student", "part"], skills: ["Python"], summary_he: "סטודנט למדעי המחשב",
};

test("/start explains the bot, privacy, and offers the app", async () => {
  const env = makeEnv(); const f = makeFetch();
  await handleUpdate(msg(1, { text: "/start" }), env, { origin: ORIGIN, fetchImpl: f, now: NOW });
  const [m] = f.sent();
  assert.ok(m.text.includes("Gemini") && m.text.includes("/delete"));
  assert.equal(m.reply_markup.inline_keyboard[0][0].web_app.url, `${ORIGIN}/app`);
});

test("a PDF CV becomes a stored profile and the CV itself is not kept", async () => {
  const env = makeEnv(); const f = makeFetch({ gemini });
  await handleUpdate(msg(7, { document: { file_id: "F1", mime_type: "application/pdf", file_name: "cv.pdf", file_size: 1000 } }),
    env, { origin: ORIGIN, fetchImpl: f, now: NOW });
  const p = await loadProfile(env, 7);
  assert.deepEqual(p.fields, ["support"]);
  assert.deepEqual(p.regions, ["south"]);
  assert.equal(p.created, "2026-10-30");
  assert.equal(p.alert_mode, "hot");
  const stored = [...env.USERS.map.values()].join(" ");
  assert.ok(!stored.includes("JVBER") && !stored.includes("%PDF"), "CV bytes must not be stored");
  const last = f.sent().at(-1);
  assert.ok(last.text.includes("בניתי לך פרופיל") && last.text.includes("תמיכה / IT"));
});

test("Word files are refused with a hint, without calling Gemini", async () => {
  const env = makeEnv(); const f = makeFetch({ gemini });
  await handleUpdate(msg(7, { document: { file_id: "F", mime_type: "application/msword", file_name: "cv.doc" } }), env, { origin: ORIGIN, fetchImpl: f, now: NOW });
  assert.ok(f.sent()[0].text.includes("PDF"));
  assert.ok(!f.calls.some((c) => c.url.includes("generativelanguage")));
});

test("CV reading is limited per day", async () => {
  const env = makeEnv(); const f = makeFetch({ gemini });
  const cv = msg(8, { text: "QA student, Java, Python, Sapir college. ".repeat(12) });
  for (let i = 0; i < 4; i++) await handleUpdate(cv, env, { origin: ORIGIN, fetchImpl: f, now: NOW });
  assert.equal(f.calls.filter((c) => c.url.includes("generativelanguage") && c.url.includes("good-model")).length, 3);
  assert.ok(f.sent().at(-1).text.includes("עד 3"));
});

test("/alerts offers the four modes and a button press saves the choice", async () => {
  const env = makeEnv(); const f = makeFetch();
  await handleUpdate(msg(9, { text: "/alerts" }), env, { origin: ORIGIN, fetchImpl: f, now: NOW });
  const buttons = f.sent()[0].reply_markup.inline_keyboard.map((row) => row[0].callback_data);
  assert.deepEqual(buttons, ["alert:hot", "alert:all", "alert:daily", "alert:off"]);
  await handleUpdate({ callback_query: { id: "cq1", from: { id: 9 }, data: "alert:daily", message: { chat: { id: 9 }, message_id: 77 } } },
    env, { origin: ORIGIN, fetchImpl: f, now: NOW });
  assert.equal((await loadProfile(env, 9)).alert_mode, "daily");
  const methods = f.calls.map((c) => c.url.split("/").pop());
  assert.ok(methods.includes("answerCallbackQuery") && methods.includes("editMessageText"));
});

test("/delete wipes everything", async () => {
  const env = makeEnv(); const f = makeFetch({ gemini });
  await handleUpdate(msg(9, { text: "/alerts" }), env, { origin: ORIGIN, fetchImpl: f, now: NOW });
  await handleUpdate({ callback_query: { id: "c", from: { id: 9 }, data: "alert:off" } }, env, { fetchImpl: f, now: NOW });
  await env.USERS.put("sent:9", "[]");
  await handleUpdate(msg(9, { text: "/delete" }), env, { origin: ORIGIN, fetchImpl: f, now: NOW });
  assert.equal(env.USERS.map.size, 0);
});

test("group chats are ignored", async () => {
  const env = makeEnv(); const f = makeFetch();
  await handleUpdate({ message: { chat: { id: -5, type: "group" }, from: { id: 1 }, text: "/start" } }, env, { origin: ORIGIN, fetchImpl: f });
  assert.equal(f.calls.length, 0);
});

const jobs = {
  generated_at: "2026-10-30T08:00:00Z",
  fields: [["qa", "QA"], ["support", "תמיכה / IT"], ["security", "אבטחה"]],
  jobs: [
    job({ key: "a", title: "Support Student", field: "support", region: "south" }),
    job({ key: "b", title: "Senior-ish QA", level: "possible", employment: "full", years: 4 }),
    job({ key: "email:c", title: "מאבטח", field: "security", origin: "email", owner_only: true }),
  ],
};

async function api(env, f, user, path, method = "GET", body) {
  const req = new Request(`${ORIGIN}${path}`, {
    method, headers: { "x-init-data": await initData(user) }, body: body ? JSON.stringify(body) : undefined,
  });
  const resp = await handleApi(req, env, { fetchImpl: f });
  return { status: resp.status, data: await resp.json() };
}

test("API rejects requests without valid Telegram initData", async () => {
  const resp = await handleApi(new Request(`${ORIGIN}/api/me`, { headers: { "x-init-data": "user=%7B%22id%22%3A1%7D&hash=bad" } }), makeEnv());
  assert.equal(resp.status, 401);
});

test("/api/me returns jobs scored for the caller and hides the owner's jobs", async () => {
  const env = makeEnv(); const f = makeFetch({ jobs });
  const { data } = await api(env, f, { id: 5 }, "/api/me");
  assert.equal(data.exists, false);
  assert.deepEqual(data.jobs.map((j) => j.key), ["a", "b"]);
  assert.equal(data.jobs[0].tier, "hot");
  assert.ok(!data.fields.some(([k]) => k === "security"));
  const owner = await api(env, f, { id: OWNER }, "/api/me");
  assert.equal(owner.data.jobs.length, 3);
  assert.ok(owner.data.fields.some(([k]) => k === "security"));
});

test("profile edits are validated and saved", async () => {
  const env = makeEnv(); const f = makeFetch({ jobs });
  const { data } = await api(env, f, { id: 5 }, "/api/profile", "POST", { fields: ["qa", "security"], regions: ["north"], alert_mode: "all" });
  assert.deepEqual(data.profile.fields, ["qa"]);
  assert.equal((await loadProfile(env, 5)).alert_mode, "all");
  await api(env, f, { id: 5 }, "/api/delete", "POST");
  assert.equal(await loadProfile(env, 5), null);
});

test("hourly alerts send new hot jobs once, only after the user joined", async () => {
  const env = makeEnv(); const f = makeFetch({ jobs: {
    ...jobs,
    jobs: [...jobs.jobs, job({ key: "old", title: "Old Support Student", field: "support", region: "south", first_seen: "2026-10-01" })],
  } });
  await env.USERS.put("meta:origin", ORIGIN);
  await env.USERS.put("user:5", JSON.stringify({ id: 5, fields: ["support"], regions: ["south"], employment: ["student", "part"], max_years: 1, alerts: true, created: "2026-10-20" }));
  await env.USERS.put("user:6", JSON.stringify({ id: 6, fields: ["support"], regions: [], employment: ["student"], max_years: 1, alerts: false, created: "2026-10-20" }));
  assert.equal(await runAlerts(env, { fetchImpl: f, now: NOW }), 1);
  const [m] = f.sent();
  assert.equal(m.chat_id, 5);
  assert.ok(m.text.includes("Support Student") && !m.text.includes("Old Support"));
  assert.equal(await runAlerts(env, { fetchImpl: f, now: NOW }), 0);
});

test("users who blocked the bot are removed", async () => {
  const env = makeEnv(); const f = makeFetch({ jobs, blocked: true });
  await env.USERS.put("user:5", JSON.stringify({ id: 5, fields: ["support"], regions: [], employment: ["student"], max_years: 1, alerts: true, created: "2026-10-01" }));
  await runAlerts(env, { fetchImpl: f });
  assert.equal(await loadProfile(env, 5), null);
});

test("setup registers the webhook with its secret, the menu button and commands", async () => {
  const env = makeEnv(); const f = makeFetch();
  await setup(env, ORIGIN, f);
  const byMethod = Object.fromEntries(f.calls.map((c) => [c.url.split("/").pop(), c.body]));
  assert.equal(byMethod.setWebhook.url, `${ORIGIN}/webhook`);
  assert.equal(byMethod.setWebhook.secret_token, "hook-secret");
  assert.equal(byMethod.setChatMenuButton.menu_button.web_app.url, `${ORIGIN}/app`);
  assert.equal(await env.USERS.get("meta:origin"), ORIGIN);
});

// A pool with one 🔥 and one 👍 job in the user's field, both new.
const pool = { generated_at: "x", fields: [], jobs: [
  job({ key: "hot1", title: "Support Student", field: "support", region: "south" }),
  job({ key: "good1", title: "Support Specialist", field: "support", level: "possible", employment: "full", years: 1, region: "south" }),
] };
const user = (mode) => JSON.stringify({ id: 5, fields: ["support"], regions: ["south"], employment: ["student", "part"], max_years: 1, alert_mode: mode, created: "2026-10-01" });
const at = (iso) => Date.parse(iso);   // Israel is UTC+2 in late October 2026

test("'all' mode sends 🔥 and 👍 jobs; 'hot' mode only 🔥", async () => {
  for (const [mode, expected] of [["all", 2], ["hot", 1]]) {
    const env = makeEnv(); const f = makeFetch({ jobs: pool });
    await env.USERS.put("user:5", user(mode));
    assert.equal(await runAlerts(env, { fetchImpl: f, now: NOW }), expected, mode);
  }
});

test("daily mode sends one digest around 18:00 Israel time, once a day", async () => {
  const env = makeEnv(); const f = makeFetch({ jobs: pool });
  await env.USERS.put("user:5", user("daily"));
  assert.equal(await runAlerts(env, { fetchImpl: f, now: at("2026-10-30T10:50:00Z") }), 0, "12:50 in Israel: not yet");
  assert.equal(await runAlerts(env, { fetchImpl: f, now: at("2026-10-30T16:50:00Z") }), 2, "18:50 in Israel: digest");
  assert.ok(f.sent()[0].text.includes("הסיכום היומי"));
  assert.equal(await runAlerts(env, { fetchImpl: f, now: at("2026-10-30T16:55:00Z") }), 0, "never twice a day");
});

test("'off' mode sends nothing", async () => {
  const env = makeEnv(); const f = makeFetch({ jobs: pool });
  await env.USERS.put("user:5", user("off"));
  assert.equal(await runAlerts(env, { fetchImpl: f, now: NOW }), 0);
});

test("setup subscribes the webhook to button presses", async () => {
  const env = makeEnv(); const f = makeFetch();
  await setup(env, ORIGIN, f);
  const hook = f.calls.find((c) => c.url.endsWith("/setWebhook")).body;
  assert.ok(hook.allowed_updates.includes("callback_query"));
});
