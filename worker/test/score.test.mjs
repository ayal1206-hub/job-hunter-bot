import assert from "node:assert/strict";
import test from "node:test";
import { cleanProfile, scoreAll, scoreJob } from "../src/score.js";
import { job } from "./helpers.mjs";

const student = { fields: ["qa", "support"], regions: ["south"], employment: ["student", "part"], max_years: 1 };

test("student job in my field and region is hot", () => {
  const r = scoreJob(job({ region: "south" }), student);
  assert.equal(r.tier, "hot");
  assert.ok(r.match);
  assert.ok(r.reasons.includes("בדרום") && r.reasons.includes("בתחום שבחרת"));
});

test("student job outside my region drops to worth a look", () => {
  assert.equal(scoreJob(job({ region: "north" }), student).tier, "good");
});

test("full-time role asking for 3 years is a long shot", () => {
  const r = scoreJob(job({ level: "possible", employment: "full", years: 3 }), student);
  assert.equal(r.tier, "long");
  assert.ok(r.reasons.some((x) => x.includes("3+")));
});

test("a graduate who accepts full-time and has 2 years sees junior roles as good", () => {
  const grad = { fields: ["dev"], regions: [], employment: ["full"], max_years: 3 };
  const r = scoreJob(job({ field: "dev", level: "junior", employment: "full", years: 2 }), grad);
  assert.ok(["good", "hot"].includes(r.tier), r.tier);
});

test("jobs outside my fields are not a match", () => {
  assert.equal(scoreJob(job({ field: "data" }), student).match, false);
});

test("no fields chosen = every tech field matches, general fields don't", () => {
  assert.equal(scoreJob(job({ field: "cyber" }), {}).match, true);
  assert.equal(scoreJob(job({ field: "security" }), {}).match, false);
});

test("owner-only jobs are hidden from everyone else", () => {
  const jobs = [job(), job({ key: "email:x", owner_only: true, origin: "email" })];
  assert.equal(scoreAll(jobs, student).length, 1);
  assert.equal(scoreAll(jobs, student, { isOwner: true }).length, 2);
});

test("email jobs in a chosen general field are worth a look for the owner", () => {
  const owner = { fields: ["security"], regions: ["south"], employment: ["student", "part"] };
  const r = scoreJob(job({ field: "security", level: "possible", employment: "full", origin: "email", region: "south" }), owner);
  assert.equal(r.tier, "good");
});

test("cleanProfile drops unknown values and general fields for non-owners", () => {
  const p = cleanProfile({ fields: ["qa", "hacking", "security"], regions: ["south", "mars"], employment: [], max_years: "99", alerts: 0 });
  assert.deepEqual(p.fields, ["qa"]);
  assert.deepEqual(p.regions, ["south"]);
  assert.deepEqual(p.employment, ["student", "part"]);
  assert.equal(p.max_years, 10);
  assert.equal(p.alerts, false);
  assert.deepEqual(cleanProfile({ fields: ["security"] }, { isOwner: true }).fields, ["security"]);
});

test("a full-time support job in my region with a year of experience is worth a look", () => {
  const r = scoreJob(job({ field: "support", level: "possible", employment: "full", years: 1, region: "south" }), student);
  assert.equal(r.tier, "good");
});
