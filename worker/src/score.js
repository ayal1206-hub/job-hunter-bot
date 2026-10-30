// Personal relevance score: the shared job pool (docs/jobs.json) scored
// against one user's profile. Every score carries the reasons behind it.

export const TECH_FIELDS = ["qa", "support", "cyber", "data", "devops", "dev", "tech"];
export const GENERAL_FIELDS = ["security", "lifeguard", "government", "office"];
export const REGIONS = { south: "דרום", center: "מרכז", north: "צפון" };
export const EMPLOYMENT = ["student", "part", "full"];

export const DEFAULT_PROFILE = Object.freeze({
  fields: [],                       // empty = every tech field
  regions: [],                      // empty = anywhere in Israel
  employment: ["student", "part"],  // what the user is open to
  max_years: 1,                     // experience the user can show
  alerts: true,
});

const HOT = 7;
const GOOD = 3;

export function fieldMatches(job, profile) {
  if (profile.fields && profile.fields.length) return profile.fields.includes(job.field);
  return TECH_FIELDS.includes(job.field);
}

export function scoreJob(job, profile = DEFAULT_PROFILE) {
  const p = { ...DEFAULT_PROFILE, ...profile };
  let s = 0;
  const reasons = [];

  if (job.level === "student") { s += 4; reasons.push("משרת סטודנט"); }
  else if (job.level === "junior") { s += 2; reasons.push("ג'וניור"); }

  const y = job.years;
  if (y === 0) { s += 2; reasons.push("ללא ניסיון"); }
  else if (y != null && y <= p.max_years) { s += 1; reasons.push(y === 1 ? "שנת ניסיון" : `${y} שנות ניסיון`); }
  else if (y != null) { s -= 3; reasons.push(`דורש ${y}+ שנות ניסיון`); }

  // Email-sourced jobs have no reliable employment type, so they are not judged on it.
  if (job.origin !== "email") {
    if (p.employment.includes(job.employment)) {
      s += 1;
      if (job.employment === "part") reasons.push("משרה חלקית");
    } else if (job.employment === "full") {
      // Many ads never say "part-time", so a full-time guess is only a small minus.
      s -= 1; reasons.push("משרה מלאה");
    }
  }

  if (job.hybrid) { s += 1; reasons.push("היברידי / מהבית"); }

  if (job.region === "any") s += 1;
  else if (!p.regions.length) s += 2;
  else if (p.regions.includes(job.region)) { s += 2; reasons.push("ב" + REGIONS[job.region]); }
  else { s -= 2; reasons.push("מחוץ לאזור שבחרת"); }

  const match = fieldMatches(job, p);
  if (match && p.fields.length) {
    s += 1;
    if (GENERAL_FIELDS.includes(job.field)) s += 2;
    reasons.push("בתחום שבחרת");
  }

  const tier = s >= HOT ? "hot" : s >= GOOD ? "good" : "long";
  return { score: s, tier, reasons, match };
}

export function scoreAll(jobs, profile, { isOwner = false } = {}) {
  return jobs
    .filter((j) => isOwner || !j.owner_only)
    .map((j) => ({ ...j, ...scoreJob(j, profile) }))
    .sort((a, b) => b.score - a.score || (b.first_seen || "").localeCompare(a.first_seen || ""));
}

// Validate and normalise a profile coming from the app or from the CV reader.
export function cleanProfile(input, { isOwner = false } = {}) {
  const allowedFields = isOwner ? [...TECH_FIELDS, ...GENERAL_FIELDS] : TECH_FIELDS;
  const pick = (arr, allowed) => [...new Set((Array.isArray(arr) ? arr : []).filter((v) => allowed.includes(v)))];
  const out = {};
  if ("fields" in input) out.fields = pick(input.fields, allowedFields);
  if ("regions" in input) out.regions = pick(input.regions, Object.keys(REGIONS));
  if ("employment" in input) {
    const e = pick(input.employment, EMPLOYMENT);
    out.employment = e.length ? e : [...DEFAULT_PROFILE.employment];
  }
  if ("max_years" in input) {
    const n = Number(input.max_years);
    out.max_years = Number.isFinite(n) ? Math.max(0, Math.min(10, Math.round(n))) : DEFAULT_PROFILE.max_years;
  }
  if ("alerts" in input) out.alerts = Boolean(input.alerts);
  return out;
}
