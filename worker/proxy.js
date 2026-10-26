// Cloudflare Worker: a permanent https://<name>.<you>.workers.dev front door for the API.
// The start script (start-windows.bat / start-mac.command) stores the current quick-tunnel URL in Workers KV (key "target") on
// every start, and this Worker forwards each request there. Free plan: 100k requests/day.
const offline = (msg) =>
  new Response(JSON.stringify({ error: { code: "server_offline", message: msg } }), {
    status: 503,
    headers: { "content-type": "application/json", "access-control-allow-origin": "*" },
  });

export default {
  async fetch(request, env) {
    const target = await env.KV.get("target", { cacheTtl: 30 });
    if (!target) return offline("The API server isn't running. Start the server (start-windows.bat or start-mac.command) on the host computer.");
    const url = new URL(request.url);
    const t = new URL(target);
    url.protocol = t.protocol;
    url.host = t.host;
    let resp;
    try {
      resp = await fetch(new Request(url, request), { redirect: "manual" });
    } catch (e) {
      return offline("The API server can't be reached. Is the server window still open?");
    }
    // 530 / 1033: the quick tunnel behind the stored URL is gone (window closed or restarting).
    if (resp.status === 530 || resp.status === 502) {
      return offline("The API server is offline or restarting. Try again in a minute.");
    }
    return resp;
  },
};
