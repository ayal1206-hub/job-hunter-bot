// Bot logic, kept free of Worker-only imports so it can be tested in Node.
//
// KV layout (binding USERS):
//   user:<telegram id>  -> profile JSON (preferences only; CVs are never stored)
//   sent:<telegram id>  -> job keys already alerted to that user
//   meta:origin         -> this worker's public URL (for links in alert messages)

import { verifyInitData } from "./auth.js";
import { analyzeCv, CvError } from "./gemini.js";
import { ALERT_MODES, DEFAULT_PROFILE, REGIONS, alertMode, alertTiers, cleanProfile, scoreAll } from "./score.js";
import { Telegram, appButton, esc } from "./telegram.js";

const CV_LIMIT_PER_DAY = 3;
const MAX_FILE_BYTES = 10 * 1024 * 1024;
const MAX_ALERTS_PER_MESSAGE = 5;
const MAX_DIGEST_JOBS = 10;
const DIGEST_HOUR = 18;          // Israel time; the hourly cron runs at :50, so the digest lands around 18:50

export const ALERT_LABELS = {
  hot: "🔥 מיד, רק משרות מעולות",
  all: "📬 על כל משרה חדשה שמתאימה לי",
  daily: "🗓 סיכום אחד ביום, בערב",
  off: "🔕 בלי התראות",
};

const alertKeyboard = (current) => ({ reply_markup: { inline_keyboard: ALERT_MODES.map((m) => [{
  text: (m === current ? "✓ " : "") + ALERT_LABELS[m], callback_data: `alert:${m}`,
}]) } });

const israelHour = (now) => Number(new Intl.DateTimeFormat("en-GB", { timeZone: "Asia/Jerusalem", hour: "2-digit", hourCycle: "h23" }).format(now));
const SENT_KEEP = 400;

const FIELD_HE = {
  qa: "QA", support: "תמיכה / IT", cyber: "סייבר", data: "דאטה / BI", devops: "DevOps / ענן",
  dev: "פיתוח", tech: "טכנולוגיה", security: "אבטחה", lifeguard: "הצלה", government: "שירות המדינה", office: "משרדי",
};
const EMPLOYMENT_HE = { student: "משרת סטודנט", part: "חלקית", full: "מלאה" };

const today = (now) => new Date(now).toISOString().slice(0, 10);
const isOwner = (env, id) => String(id) === String(env.OWNER_ID || "");
const models = (env) => String(env.GEMINI_MODELS || "gemini-flash-latest").split(",").map((m) => m.trim()).filter(Boolean);

export async function loadProfile(env, id) {
  const raw = await env.USERS.get(`user:${id}`);
  return raw ? JSON.parse(raw) : null;
}

async function saveProfile(env, profile) {
  await env.USERS.put(`user:${profile.id}`, JSON.stringify(profile));
}

function newProfile(id, now) {
  return { id, ...DEFAULT_PROFILE, created: today(now), skills: [], summary: "" };
}

export function describeProfile(p) {
  const fields = p.fields.length ? p.fields.map((f) => FIELD_HE[f] || f).join(", ") : "כל תחומי ההייטק";
  const regions = p.regions.length ? p.regions.map((r) => REGIONS[r]).join(", ") : "כל הארץ";
  const lines = [
    `🎯 <b>תחומים:</b> ${esc(fields)}`,
    `📍 <b>אזור:</b> ${esc(regions)}`,
    `🕒 <b>סוג משרה:</b> ${esc(p.employment.map((e) => EMPLOYMENT_HE[e]).join(", "))}`,
    `📈 <b>ניסיון שאפשר לדרוש ממך:</b> עד ${p.max_years} ${p.max_years === 1 ? "שנה" : "שנים"}`,
    `🔔 <b>התראות:</b> ${ALERT_LABELS[alertMode(p)]}`,
  ];
  if (p.skills && p.skills.length) lines.push(`🛠 <b>כישורים מהקו"ח:</b> ${esc(p.skills.join(", "))}`);
  return lines.join("\n");
}

const WELCOME = `👋 <b>היי! אני בוט שמחפש משרות סטודנט וג'וניור בהייטק.</b>

כל כמה שעות אני סורק עשרות חברות ישראליות, קורא את תיאור כל משרה ומדרג אותה לפי מה שמתאים לך: 🔥 להגיש עכשיו, 👍 שווה לבדוק, 🤔 סיכוי נמוך.

<b>איך מתחילים:</b>
1. שלח לי את קורות החיים שלך כקובץ PDF (או הדבק אותם כטקסט), ואני אבנה לך פרופיל.
2. או פתח את "המשרות שלי" והגדר תחומים ואזור ידנית.

🔒 <b>פרטיות:</b> קורות החיים נשלחים לניתוח ב־Google Gemini (גרסה חינמית; גוגל עשויה להשתמש בתוכן לשיפור השירותים שלה) ולא נשמרים אצלנו. נשמרות רק ההעדפות שחולצו מהם: תחומים, אזור ורמת ניסיון. מומלץ לשלוח גרסה בלי טלפון, כתובת ות"ז. /delete מוחק את כל המידע שלך.

פקודות: /profile הפרופיל שלך · /alerts מתי לקבל התראות · /delete מחיקת המידע`;

/** Telegram webhook update. Runs after the 200 response has been sent (waitUntil). */
export async function handleUpdate(update, env, { origin, fetchImpl = fetch, now = Date.now() } = {}) {
  if (update.callback_query) return handleCallback(update.callback_query, env, { fetchImpl, now });
  const msg = update.message;
  if (!msg || !msg.from || msg.chat?.type !== "private") return;
  const tg = new Telegram(env.TELEGRAM_BOT_TOKEN, fetchImpl);
  const id = msg.from.id;
  const text = (msg.text || "").trim();
  const cmd = text.startsWith("/") ? text.split(/[\s@]/)[0].toLowerCase() : null;

  if (cmd === "/start" || cmd === "/help") {
    return tg.send(id, WELCOME, appButton(origin));
  }
  if (cmd === "/profile") {
    const p = await loadProfile(env, id);
    if (!p) return tg.send(id, "עוד אין לך פרופיל. שלח לי קורות חיים כ־PDF, או הגדר העדפות במסך המשרות.", appButton(origin));
    return tg.send(id, `<b>הפרופיל שלך</b>\n\n${describeProfile(p)}`, appButton(origin, "✏️ עריכה"));
  }
  if (cmd === "/alerts") {
    const p = (await loadProfile(env, id)) || newProfile(id, now);
    return tg.send(id, "<b>מתי לשלוח לך משרות חדשות?</b>\nבכל מקרה, כל המשרות מחכות לך במסך \"משרות\".", alertKeyboard(alertMode(p)));
  }
  if (cmd === "/delete") {
    await deleteUser(env, id);
    return tg.send(id, "🗑 כל המידע שלך נמחק. אפשר להתחיל מחדש בכל רגע עם /start.");
  }
  if (cmd) return tg.send(id, "לא מכיר את הפקודה הזו. נסה /help.");

  // A CV: PDF / image document, a photo, or a long pasted text.
  const doc = msg.document;
  const photo = msg.photo && msg.photo[msg.photo.length - 1];
  let input = null;
  if (doc) {
    const mime = doc.mime_type || "";
    const name = (doc.file_name || "").toLowerCase();
    if (!(mime === "application/pdf" || name.endsWith(".pdf") || mime.startsWith("image/"))) {
      return tg.send(id, "אני קורא קורות חיים בפורמט PDF או תמונה. אם יש לך קובץ Word, שמור אותו כ־PDF ושלח שוב.");
    }
    if ((doc.file_size || 0) > MAX_FILE_BYTES) return tg.send(id, "הקובץ גדול מדי (מעל 10MB).");
    input = { fileId: doc.file_id, mime: mime.startsWith("image/") ? mime : "application/pdf" };
  } else if (photo) {
    input = { fileId: photo.file_id, mime: "image/jpeg" };
  } else if (text.length >= 300) {
    input = { text };
  } else {
    return tg.send(id, "כדי שאבנה לך פרופיל, שלח לי את קורות החיים כקובץ PDF או הדבק אותם כאן. אפשר גם להגדיר הכל ידנית במסך המשרות.", appButton(origin));
  }

  return readCv(env, tg, id, msg.from, input, { origin, fetchImpl, now });
}

async function readCv(env, tg, id, from, input, { origin, fetchImpl, now }) {
  const day = today(now);
  const profile = (await loadProfile(env, id)) || newProfile(id, now);
  const usage = profile.cv_usage && profile.cv_usage.day === day ? profile.cv_usage : { day, count: 0 };
  if (usage.count >= CV_LIMIT_PER_DAY) {
    return tg.send(id, `אפשר לנתח עד ${CV_LIMIT_PER_DAY} קורות חיים ביום. נסה שוב מחר, או ערוך את הפרופיל ידנית.`, appButton(origin, "✏️ עריכה"));
  }

  await tg.send(id, "📄 קורא את קורות החיים, זה לוקח כמה שניות…");
  try {
    let source = input;
    if (input.fileId) {
      const bytes = await tg.download(input.fileId);
      if (!bytes) return tg.send(id, "לא הצלחתי להוריד את הקובץ. נסה לשלוח שוב.");
      source = { bytes, mime: input.mime };
    }
    const prefs = await analyzeCv(source, env.GEMINI_API_KEY, models(env), fetchImpl);
    Object.assign(profile, cleanProfile(prefs, { isOwner: isOwner(env, id) }), {
      skills: prefs.skills, summary: prefs.summary, level: prefs.level,
      cv_usage: { day, count: usage.count + 1 },
    });
    await saveProfile(env, profile);
    const summary = profile.summary ? `<i>${esc(profile.summary)}</i>\n\n` : "";
    return tg.send(id, `✅ <b>בניתי לך פרופיל מקורות החיים</b>\n\n${summary}${describeProfile(profile)}\n\nאפשר לשנות כל דבר במסך המשרות. משרות 🔥 חדשות יישלחו אליך לכאן.`, appButton(origin));
  } catch (err) {
    console.log("cv analysis failed:", err && err.message);
    const quota = err instanceof CvError && err.message === "quota";
    return tg.send(id, quota
      ? "השירות שקורא קורות חיים עמוס כרגע. נסה שוב בעוד כמה דקות, או הגדר את הפרופיל ידנית."
      : "לא הצלחתי לקרוא את קורות החיים. נסה קובץ PDF אחר, או הגדר את הפרופיל ידנית.", appButton(origin, "✏️ עריכה"));
  }
}

async function handleCallback(cq, env, { fetchImpl, now }) {
  const tg = new Telegram(env.TELEGRAM_BOT_TOKEN, fetchImpl);
  const [kind, mode] = String(cq.data || "").split(":");
  if (kind !== "alert" || !ALERT_MODES.includes(mode) || !cq.from) {
    return tg.call("answerCallbackQuery", { callback_query_id: cq.id });
  }
  const p = (await loadProfile(env, cq.from.id)) || newProfile(cq.from.id, now);
  p.alert_mode = mode;
  delete p.alerts;
  await saveProfile(env, p);
  await tg.call("answerCallbackQuery", { callback_query_id: cq.id, text: "נשמר ✓" });
  if (cq.message) {
    await tg.call("editMessageText", {
      chat_id: cq.message.chat.id, message_id: cq.message.message_id, parse_mode: "HTML",
      text: `🔔 <b>התראות:</b> ${ALERT_LABELS[mode]}\nאפשר לשנות בכל רגע עם /alerts.`,
    });
  }
}

export async function deleteUser(env, id) {
  await env.USERS.delete(`user:${id}`);
  await env.USERS.delete(`sent:${id}`);
}

// ---------- Jobs ----------

export async function loadJobs(env, fetchImpl = fetch) {
  const resp = await fetchImpl(env.JOBS_URL, { cf: { cacheTtl: 300, cacheEverything: true } });
  if (!resp.ok) throw new Error(`jobs.json HTTP ${resp.status}`);
  return resp.json();
}

// ---------- Mini app API ----------

const json = (data, status = 200) => new Response(JSON.stringify(data), {
  status, headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" },
});

export async function handleApi(request, env, { fetchImpl = fetch, now = Date.now() } = {}) {
  const user = await verifyInitData(request.headers.get("x-init-data"), env.TELEGRAM_BOT_TOKEN, { now });
  if (!user) return json({ error: "unauthorized" }, 401);
  const path = new URL(request.url).pathname;
  const owner = isOwner(env, user.id);

  if (path === "/api/me" && request.method === "GET") {
    const stored = await loadProfile(env, user.id);
    const profile = stored || newProfile(user.id, now);
    const data = await loadJobs(env, fetchImpl);
    const fields = (data.fields || []).filter(([k]) => owner || !["security", "lifeguard", "government", "office"].includes(k));
    return json({
      exists: Boolean(stored), owner, profile, fields,
      generated_at: data.generated_at,
      jobs: scoreAll(data.jobs || [], profile, { isOwner: owner }),
    });
  }

  if (path === "/api/profile" && request.method === "POST") {
    const body = await request.json().catch(() => null);
    if (!body || typeof body !== "object") return json({ error: "bad request" }, 400);
    const profile = (await loadProfile(env, user.id)) || newProfile(user.id, now);
    Object.assign(profile, cleanProfile(body, { isOwner: owner }));
    await saveProfile(env, profile);
    return json({ ok: true, profile });
  }

  if (path === "/api/delete" && request.method === "POST") {
    await deleteUser(env, user.id);
    return json({ ok: true });
  }

  return json({ error: "not found" }, 404);
}

// ---------- Hourly alerts ----------

const TIER_ICON = { hot: "🔥", good: "👍", long: "🤔" };

function alertMessage(jobs, { digest = false, more = 0 } = {}) {
  const blocks = jobs.map((j) => {
    const where = j.location || REGIONS[j.region] || "כל הארץ";
    return `${TIER_ICON[j.tier]} <b>${esc(j.title)}</b>\n🏢 ${esc(j.company)} · 📍 ${esc(where)}\n✅ ${esc(j.reasons.join(" · "))}\n<a href="${esc(j.url)}">לפרטים והגשה</a>`;
  });
  const count = jobs.length + more;
  const head = digest
    ? `🗓 <b>הסיכום היומי: ${count === 1 ? "משרה חדשה אחת" : `${count} משרות חדשות`} בשבילך</b>`
    : `<b>${count === 1 ? "משרה חדשה" : `${count} משרות חדשות`} שמתאימות לך</b>`;
  const tail = more ? `\n\n➕ ועוד ${more} במסך המשרות.` : "";
  return `${head}\n\n${blocks.join("\n\n")}${tail}`;
}

export async function runAlerts(env, { fetchImpl = fetch, now = Date.now() } = {}) {
  const data = await loadJobs(env, fetchImpl);
  const digestTime = israelHour(now) === DIGEST_HOUR;
  const day = today(now);
  const origin = (await env.USERS.get("meta:origin")) || "";
  const tg = new Telegram(env.TELEGRAM_BOT_TOKEN, fetchImpl);
  let cursor, sentTotal = 0;
  do {
    const page = await env.USERS.list({ prefix: "user:", cursor });
    for (const { name } of page.keys) {
      const profile = JSON.parse((await env.USERS.get(name)) || "null");
      if (!profile) continue;
      const mode = alertMode(profile);
      if (mode === "off") continue;
      const digest = mode === "daily";
      if (digest && (!digestTime || profile.last_digest === day)) continue;
      const tiers = alertTiers(mode);
      const sent = new Set(JSON.parse((await env.USERS.get(`sent:${profile.id}`)) || "[]"));
      // Only jobs that appeared after the user joined, so a new user isn't flooded.
      const fresh = scoreAll(data.jobs || [], profile, { isOwner: isOwner(env, profile.id) })
        .filter((j) => tiers.includes(j.tier) && j.match && !sent.has(j.key) && (j.first_seen || "") >= (profile.created || ""));
      if (!fresh.length) continue;
      // Hourly modes send a few at a time (the rest come next hour); the digest lists more and
      // counts the remainder, and everything it covered is marked as seen.
      const batch = fresh.slice(0, digest ? MAX_DIGEST_JOBS : MAX_ALERTS_PER_MESSAGE);
      const covered = digest ? fresh : batch;
      const res = await tg.send(profile.id, alertMessage(batch, { digest, more: digest ? fresh.length - batch.length : 0 }),
        origin ? appButton(origin, "📋 כל המשרות שלי") : {});
      if (res && res.error_code === 403) { await deleteUser(env, profile.id); continue; }  // user blocked the bot
      if (digest) { profile.last_digest = day; await saveProfile(env, profile); }
      covered.forEach((j) => sent.add(j.key));
      await env.USERS.put(`sent:${profile.id}`, JSON.stringify([...sent].slice(-SENT_KEEP)));
      sentTotal += covered.length;
    }
    cursor = page.list_complete ? undefined : page.cursor;
  } while (cursor);
  return sentTotal;
}

// ---------- One-time setup (called by the deploy workflow) ----------

export async function setup(env, origin, fetchImpl = fetch) {
  const tg = new Telegram(env.TELEGRAM_BOT_TOKEN, fetchImpl);
  await env.USERS.put("meta:origin", origin);
  const results = {};
  results.webhook = await tg.call("setWebhook", {
    url: `${origin}/webhook`, secret_token: env.WEBHOOK_SECRET,
    allowed_updates: ["message", "callback_query"], drop_pending_updates: false,
  });
  results.menu = await tg.call("setChatMenuButton", {
    menu_button: { type: "web_app", text: "משרות", web_app: { url: `${origin}/app` } },
  });
  results.commands = await tg.call("setMyCommands", {
    commands: [
      { command: "start", description: "התחלה והסבר" },
      { command: "profile", description: "הפרופיל שלי" },
      { command: "alerts", description: "מתי לקבל התראות" },
      { command: "delete", description: "מחיקת כל המידע שלי" },
    ],
  });
  return results;
}
