// Minimal Telegram Bot API client.

export class Telegram {
  constructor(token, fetchImpl = fetch) {
    this.token = token;
    this.fetch = fetchImpl;
  }

  async call(method, body = {}) {
    const resp = await this.fetch(`https://api.telegram.org/bot${this.token}/${method}`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await resp.json().catch(() => ({ ok: false }));
    if (!data.ok) console.log(`telegram ${method} failed: ${data.description || resp.status}`);
    return data;
  }

  send(chatId, text, extra = {}) {
    return this.call("sendMessage", {
      chat_id: chatId, text, parse_mode: "HTML", disable_web_page_preview: true, ...extra,
    });
  }

  async download(fileId) {
    const info = await this.call("getFile", { file_id: fileId });
    if (!info.ok) return null;
    const resp = await this.fetch(`https://api.telegram.org/file/bot${this.token}/${info.result.file_path}`);
    if (!resp.ok) return null;
    return new Uint8Array(await resp.arrayBuffer());
  }
}

export const esc = (s) => String(s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");

export const appButton = (origin, text = "📋 המשרות שלי") =>
  ({ reply_markup: { inline_keyboard: [[{ text, web_app: { url: `${origin}/app` } }]] } });
