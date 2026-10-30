// Read a CV with Gemini and turn it into job-search preferences.
// The CV itself is never stored; only the extracted preferences are kept.

const API = "https://generativelanguage.googleapis.com/v1beta/models";

const SCHEMA = {
  type: "OBJECT",
  properties: {
    fields: {
      type: "ARRAY",
      items: { type: "STRING", enum: ["qa", "support", "cyber", "data", "devops", "dev"] },
    },
    level: { type: "STRING", enum: ["student", "junior", "experienced"] },
    years_experience: { type: "INTEGER" },
    regions: { type: "ARRAY", items: { type: "STRING", enum: ["south", "center", "north"] } },
    employment: { type: "ARRAY", items: { type: "STRING", enum: ["student", "part", "full"] } },
    skills: { type: "ARRAY", items: { type: "STRING" } },
    summary_he: { type: "STRING" },
  },
  required: ["fields", "level", "years_experience", "regions", "employment", "skills", "summary_he"],
};

const PROMPT = `You read a job seeker's CV (Hebrew or English) for an Israeli tech job-alert bot.
Return JSON only, following the schema:
- fields: the tech job tracks this person fits now (1-3), from: qa (software testing), support (tech support / IT / NOC),
  cyber (security analyst / SOC / research), data (data / BI / ML), devops (DevOps / cloud / infrastructure), dev (software development).
- level: "student" if currently studying, "junior" if graduated with under 2 years of tech work, else "experienced".
- years_experience: years of paid work in tech (software, IT, data, security). Military tech roles count. 0 if none.
- regions: where in Israel they can work, from the city they live or study in: south (Be'er Sheva, Ashkelon, Ashdod, Sderot...),
  center (Tel Aviv area, Jerusalem, Petah Tikva, Rishon...), north (Haifa, Yokneam, Galilee...). Include neighbouring regions only if obvious.
- employment: if a student, ["student", "part"]; otherwise what fits.
- skills: up to 8 technical skills (languages, tools).
- summary_he: one short Hebrew sentence describing the profile, WITHOUT name, phone, email, address or ID number.
Never copy personal identifiers into any field.`;

// Remove contact details from pasted CV text before it leaves the server.
export function redact(text) {
  return text
    .replace(/[\w.+-]+@[\w-]+\.[\w.-]+/g, "[email]")
    .replace(/https?:\/\/\S+|www\.\S+|linkedin\.com\/\S+|github\.com\/\S+/gi, "[link]")
    .replace(/(\+?972[-\s]?|0)(5\d|[2-489]|7\d)[-\s]?\d{3}[-\s]?\d{4}/g, "[phone]")
    .replace(/\b\d{9}\b/g, "[id]");
}

export function toBase64(bytes) {
  let bin = "";
  const CHUNK = 0x8000;
  for (let i = 0; i < bytes.length; i += CHUNK) {
    bin += String.fromCharCode.apply(null, bytes.subarray(i, i + CHUNK));
  }
  return btoa(bin);
}

export class CvError extends Error {}

/**
 * input: { bytes: Uint8Array, mime: "application/pdf" | "image/jpeg" | ... } or { text: string }
 * models: tried in order; a model that no longer exists (404) falls through to the next.
 */
export async function analyzeCv(input, apiKey, models, fetchImpl = fetch) {
  const part = input.text
    ? { text: "CV:\n" + redact(input.text).slice(0, 20000) }
    : { inline_data: { mime_type: input.mime, data: toBase64(input.bytes) } };
  const body = JSON.stringify({
    contents: [{ role: "user", parts: [part, { text: PROMPT }] }],
    generationConfig: { responseMimeType: "application/json", responseSchema: SCHEMA, temperature: 0 },
  });

  let lastError = "no model configured";
  for (const model of models) {
    const resp = await fetchImpl(`${API}/${model}:generateContent`, {
      method: "POST",
      headers: { "content-type": "application/json", "x-goog-api-key": apiKey },
      body,
    });
    if (resp.status === 404) { lastError = `${model}: not found`; continue; }
    if (resp.status === 429) throw new CvError("quota");
    if (!resp.ok) { lastError = `${model}: HTTP ${resp.status}`; continue; }
    const data = await resp.json();
    const text = data?.candidates?.[0]?.content?.parts?.map((p) => p.text || "").join("") || "";
    try {
      return toPreferences(JSON.parse(text));
    } catch {
      lastError = `${model}: unreadable answer`;
    }
  }
  throw new CvError(lastError);
}

export function toPreferences(r) {
  const years = Math.max(0, Math.min(40, Number(r.years_experience) || 0));
  return {
    fields: Array.isArray(r.fields) ? r.fields.slice(0, 3) : [],
    regions: Array.isArray(r.regions) ? r.regions : [],
    employment: Array.isArray(r.employment) && r.employment.length ? r.employment : ["student", "part"],
    // What the user can apply to: their own years, plus a year of stretch.
    max_years: Math.min(10, years + 1),
    level: ["student", "junior", "experienced"].includes(r.level) ? r.level : "student",
    skills: Array.isArray(r.skills) ? r.skills.slice(0, 8).map(String) : [],
    summary: typeof r.summary_he === "string" ? redact(r.summary_he).slice(0, 300) : "",
  };
}
