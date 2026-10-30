// Cloudflare Worker entry: Telegram webhook, mini app + its API, hourly alerts.
import APP_HTML from "./app.html";
import { handleApi, handleUpdate, runAlerts, setup } from "./handlers.js";

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    const origin = url.origin;

    if (url.pathname === "/webhook" && request.method === "POST") {
      if (request.headers.get("x-telegram-bot-api-secret-token") !== env.WEBHOOK_SECRET) {
        return new Response("forbidden", { status: 403 });
      }
      const update = await request.json().catch(() => null);
      // Answer Telegram right away; reading a CV can take several seconds.
      if (update) ctx.waitUntil(handleUpdate(update, env, { origin }).catch((e) => console.log("update failed", e)));
      return new Response("ok");
    }

    if (url.pathname.startsWith("/api/")) return handleApi(request, env);

    if (url.pathname === "/app" || url.pathname === "/app/") {
      return new Response(APP_HTML, { headers: { "content-type": "text/html; charset=utf-8", "cache-control": "no-cache" } });
    }

    if (url.pathname === "/setup" && request.method === "POST") {
      if (!env.WEBHOOK_SECRET || request.headers.get("x-setup-key") !== env.WEBHOOK_SECRET) {
        return new Response("forbidden", { status: 403 });
      }
      return Response.json(await setup(env, origin));
    }

    if (url.pathname === "/") return Response.redirect(`${origin}/app`, 302);
    return new Response("not found", { status: 404 });
  },

  async scheduled(event, env, ctx) {
    ctx.waitUntil(runAlerts(env).then((n) => console.log(`alerts sent: ${n}`)));
  },
};
