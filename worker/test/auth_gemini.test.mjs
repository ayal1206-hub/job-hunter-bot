import assert from "node:assert/strict";
import test from "node:test";
import { verifyInitData } from "../src/auth.js";
import { CvError, analyzeCv, redact, toBase64 } from "../src/gemini.js";
import { TOKEN, initData, makeFetch } from "./helpers.mjs";

test("valid initData returns the Telegram user", async () => {
  const data = await initData({ id: 42, first_name: "Noam" });
  assert.equal((await verifyInitData(data, TOKEN)).id, 42);
});

test("tampered, wrongly signed or expired initData is rejected", async () => {
  const data = await initData({ id: 42 });
  assert.equal(await verifyInitData(data.replace("42", "43"), TOKEN), null);
  assert.equal(await verifyInitData(data, "999:other-token"), null);
  const old = await initData({ id: 42 }, Math.floor(Date.now() / 1000) - 2 * 86400);
  assert.equal(await verifyInitData(old, TOKEN), null);
  assert.equal(await verifyInitData("", TOKEN), null);
});

test("redact removes contact details from pasted CVs", () => {
  const t = redact("Noam, noam@mail.com, 054-123-4567, +972 52 1234567, ID 123456789, linkedin.com/in/noam https://x.io");
  for (const leak of ["noam@mail.com", "4567", "123456789", "linkedin", "https"]) assert.ok(!t.includes(leak), leak);
});

test("base64 matches Node's encoder", () => {
  const bytes = new Uint8Array(100000).map((_, i) => i % 256);
  assert.equal(toBase64(bytes), Buffer.from(bytes).toString("base64"));
});

const answer = {
  fields: ["qa", "support"], level: "student", years_experience: 0, regions: ["south"],
  employment: ["student", "part"], skills: ["Java", "C++"], summary_he: "סטודנט, טלפון 050-1234567",
};

test("analyzeCv falls through a retired model and maps the answer", async () => {
  const f = makeFetch({ gemini: answer });
  const p = await analyzeCv({ bytes: new Uint8Array([1, 2, 3]), mime: "application/pdf" }, "k", ["gone-model", "good-model"], f);
  assert.deepEqual(p.fields, ["qa", "support"]);
  assert.equal(p.max_years, 1);
  assert.ok(!p.summary.includes("050"));
  const g = f.calls.filter((c) => c.url.includes("generativelanguage"));
  assert.equal(g.length, 2);
  assert.equal(g[1].body.contents[0].parts[0].inline_data.mime_type, "application/pdf");
  assert.equal(g[1].headers["x-goog-api-key"], "k");
});

test("pasted CV text is redacted before it is sent", async () => {
  const f = makeFetch({ gemini: answer });
  await analyzeCv({ text: "Noam Cohen noam@x.com 0541234567 QA student".padEnd(400, ".") }, "k", ["good-model"], f);
  const sent = f.calls.find((c) => c.url.includes("generativelanguage")).body.contents[0].parts[0].text;
  assert.ok(!sent.includes("noam@x.com") && !sent.includes("0541234567"));
});

test("quota errors are reported as such", async () => {
  await assert.rejects(analyzeCv({ text: "x" }, "k", ["good-model"], makeFetch({ gemini: 429 })),
    (e) => e instanceof CvError && e.message === "quota");
});
