/* Heatmapify dashboard: talks to the Heatmapify API and draws the result. */
(() => {
  "use strict";
  if (location.hash === "#about") { location.replace("about.html"); return; }

  const $ = (id) => document.getElementById(id);
  const SIGNAL_COLORS = {
    comments: "#7aa2ff",
    transcript: "#5fd3a3",
    audio: "#ffb454",
    visual: "#b392f0",
    official_most_replayed: "#ff5a1f",
  };
  const THEMES = {
    dark: { grid: "rgba(255,255,255,.06)", ref: "rgba(255,255,255,.28)", hover: "rgba(255,255,255,.35)", edge: "rgba(255,255,255,.08)", bar: "rgba(255,255,255,.16)", label: "#d8d8e2", sub: "#b9b9c6", marker: "#0b0b10", dot: "#ffffff", good: "#3ecf8e", bad: "#ff6b6b", ember: "#ff5a1f", peakBand: "rgba(62,207,142,.10)", dropBand: "rgba(255,107,107,.08)",
      sig: { comments: "#7aa2ff", transcript: "#5fd3a3", audio: "#ffb454", visual: "#b392f0", official_most_replayed: "#ff5a1f" } },
    light: { grid: "rgba(20,20,30,.07)", ref: "rgba(20,20,30,.35)", hover: "rgba(20,20,30,.35)", edge: "rgba(20,20,30,.1)", bar: "rgba(20,20,30,.12)", label: "#2a2a35", sub: "#555563", marker: "#ffffff", dot: "#ffffff", good: "#128a57", bad: "#d23f3f", ember: "#ff5a1f", peakBand: "rgba(18,138,87,.09)", dropBand: "rgba(210,63,63,.07)",
      sig: { comments: "#3f6fe0", transcript: "#14946a", audio: "#e07b10", visual: "#7c4ddb", official_most_replayed: "#ff5a1f" } },
  };
  let C = THEMES[document.documentElement.dataset.theme === "light" ? "light" : "dark"];
  const SIGNAL_LABELS = {
    comments: "Comments",
    transcript: "Captions",
    audio: "Audio",
    visual: "Visuals",
    official_most_replayed: "Most replayed",
  };
  const STORE = "hmdash.v1";
  const HISTORY = "hmdash.history.v1";
  const POLL_MS = 2500;
  const MAX_WAIT_MS = 20 * 60 * 1000;

  let current = null; // the result being shown
  let hiddenSignals = new Set();
  let pollToken = 0;

  // ------------------------------------------------------------ helpers --
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const label = (n) => SIGNAL_LABELS[n] || n.replace(/_/g, " ");
  const color = (n, i = 0) => C.sig[n] || SIGNAL_COLORS[n] || ["#6fd6d6", "#f28fb1", "#e6d27a"][i % 3];
  let playhead = null; // seconds, for the playhead line on the main chart
  function hms(sec) {
    sec = Math.max(0, Math.round(sec || 0));
    const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
    const mm = h ? String(m).padStart(2, "0") : String(m);
    return (h ? h + ":" : "") + mm + ":" + String(s).padStart(2, "0");
  }
  const pct = (v, d = 0) => (v * 100).toFixed(d) + "%";
  const mean = (a) => (a.length ? a.reduce((x, y) => x + y, 0) / a.length : 0);
  function pearson(a, b) {
    const n = Math.min(a.length, b.length);
    if (n < 3) return 0;
    const ma = mean(a), mb = mean(b);
    let num = 0, da = 0, db = 0;
    for (let i = 0; i < n; i++) { const x = a[i] - ma, y = b[i] - mb; num += x * y; da += x * x; db += y * y; }
    return da && db ? num / Math.sqrt(da * db) : 0;
  }
  function svgEl(w, h, inner) {
    return `<svg viewBox="0 0 ${w} ${h}" width="${w}" height="${h}" xmlns="http://www.w3.org/2000/svg">${inner}</svg>`;
  }
  function niceTicks(max, count = 6) {
    if (max <= 0) return [0];
    const raw = max / count;
    const steps = [5, 10, 15, 30, 60, 120, 300, 600, 900, 1800, 3600];
    const step = steps.find((s) => s >= raw) || 3600;
    const out = [];
    for (let t = 0; t <= max + 0.001; t += step) out.push(t);
    return out;
  }
  function videoIdFrom(input) {
    const s = (input || "").trim();
    if (/^[\w-]{11}$/.test(s)) return s;
    const m = s.match(/(?:v=|youtu\.be\/|shorts\/|embed\/|live\/)([\w-]{11})/);
    return m ? m[1] : null;
  }
  function normBase(s) {
    s = (s || "").trim().replace(/\/+$/, "");
    if (s && !/^https?:\/\//i.test(s)) s = "https://" + s;
    return s;
  }

  // ----------------------------------------------------------- settings --
  function loadSettings() {
    try {
      const s = JSON.parse(localStorage.getItem(STORE) || "{}");
      $("apiBase").value = s.apiBase || "";
      $("apiKey").value = s.apiKey || "";
      $("windowSel").value = s.window || "";
      $("remember").checked = s.remember !== false;
      const params = new URLSearchParams(location.search);
      if (params.get("api")) $("apiBase").value = params.get("api");
      if (params.get("v")) $("ytUrl").value = params.get("v");
      if (s.os) setOS(s.os);
    } catch (_) { /* ignore */ }
  }
  function saveSettings() {
    const remember = $("remember").checked;
    const s = { remember, window: $("windowSel").value, os: currentOS };
    if (remember) { s.apiBase = normBase($("apiBase").value); s.apiKey = $("apiKey").value.trim(); }
    try { localStorage.setItem(STORE, JSON.stringify(s)); } catch (_) { /* storage blocked */ }
  }

  // ---------------------------------------------------------------- api --
  async function api(path, opts = {}) {
    const base = normBase($("apiBase").value);
    const key = $("apiKey").value.trim();
    let res;
    try {
      res = await fetch(base + path, { ...opts, headers: { "X-API-Key": key, ...(opts.headers || {}) } });
    } catch (e) {
      const err = new Error("Couldn't reach the API.");
      err.hint = "Check the API URL (a random trycloudflare.com URL changes on every restart; a workers.dev URL stays the same), that the server window is still open, and that your server is up to date so it allows requests from this dashboard.";
      throw err;
    }
    let body = null;
    try { body = await res.json(); } catch (_) { /* non-JSON */ }
    if (!res.ok) {
      const e = new Error((body && body.error && body.error.message) || `Request failed (${res.status}).`);
      e.code = body && body.error && body.error.code;
      e.status = res.status;
      if (res.status === 401 || res.status === 403) e.hint = "Check your API key: it's the line in secrets\\api_key.txt.";
      if (res.status === 429) e.hint = "You've hit the rate limit or daily quota. Wait a minute and try again.";
      if (res.status === 530 || res.status === 502 || res.status === 404 && !body) e.hint = "The tunnel isn't reaching your server. Restart the server (start-windows.bat or start-mac.command), and paste the new URL if you aren't using a permanent one.";
      if (e.code === "server_offline") e.hint = "Your permanent URL works, but the server behind it is off. Start the server (start-windows.bat or start-mac.command) on the host computer. Right after a start it can take up to a minute to switch over.";
      throw e;
    }
    return { status: res.status, body };
  }

  async function testConnection({ quiet = false } = {}) {
    const base = normBase($("apiBase").value);
    if (!base || !$("apiKey").value.trim()) {
      setConn("neutral", "Not connected", "Connect the dashboard to your own API. It runs free on your Windows or Mac.");
      openConn(true);
      return false;
    }
    setConn("neutral busy", "Checking…", "Checking " + hostOf(base) + "…");
    try {
      const { body } = await api("/health");
      const ok = body.status === "ok";
      setConn(ok ? "ok" : "warn", ok ? "Connected" : "Degraded", `${hostOf(base)} · API v${esc(body.version || "?")}${ok ? "" : " · " + esc(body.status)}`);
      if (ok) openConn(false);
      return ok;
    } catch (e) {
      const short = e.code === "server_offline" ? "Server offline" : e.status === 401 || e.status === 403 ? "Wrong key" : e.status ? `Error ${e.status}` : "Unreachable";
      setConn("bad", short, (e.hint || e.message) );
      if (!quiet) openConn(true);
      return false;
    }
  }
  function hostOf(u) { try { return new URL(u).host; } catch (_) { return u; } }
  function setConn(kind, text, summary) {
    setPill($("connStatus"), kind, text);
    setPill($("navConn"), kind, text);
    if (summary != null) $("connSummary").innerHTML = summary;
  }
  function openConn(open) {
    $("connection").classList.toggle("collapsed", !open);
    $("connToggle").textContent = open ? "Hide" : "Edit";
  }
  function setPill(el, kind, text) { el.className = "pill " + kind; el.textContent = text; }

  let currentOS = /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent) ? "mac" : "win";
  function setOS(os) {
    currentOS = os === "mac" ? "mac" : "win";
    document.querySelectorAll(".os-tabs button").forEach((b) => b.classList.toggle("on", b.dataset.os === currentOS));
    $("connection").dataset.osShow = currentOS;
  }

  // ----------------------------------------------------------- analysis --
  async function analyze(ev) {
    ev && ev.preventDefault();
    hideError();
    const url = $("ytUrl").value.trim();
    if (!videoIdFrom(url)) return showError("That doesn't look like a YouTube link.", "Paste a full video URL like https://www.youtube.com/watch?v=… or a youtu.be link.");
    if (!normBase($("apiBase").value) || !$("apiKey").value.trim()) {
      openConn(true);
      $("connection").scrollIntoView({ behavior: "smooth", block: "center" });
      return showError("Add your API URL and key first.", "Both are shown in the server window when you run start-windows.bat (Windows) or start-mac.command (Mac).");
    }
    saveSettings();
    const token = ++pollToken;
    setBusy(true);
    showProgress({ stage: "contacting server", progress: 0.02 });
    try {
      const q = new URLSearchParams({ url, top: "8", bottom: "6" });
      if ($("windowSel").value) q.set("window", $("windowSel").value);
      if ($("forceEst").checked) q.set("force_estimate", "true");
      const { status, body } = await api("/v1/heatmap?" + q.toString());
      if (status === 202 && body.job_id) {
        const result = await poll(body.job_id, token);
        if (result) finish(result);
      } else {
        finish(body);
      }
    } catch (e) {
      if (token === pollToken) { hideProgress(); showError(e.message, e.hint); }
    } finally {
      if (token === pollToken) setBusy(false);
    }
  }

  async function poll(jobId, token) {
    const started = Date.now();
    while (token === pollToken) {
      if (Date.now() - started > MAX_WAIT_MS) throw Object.assign(new Error("This is taking unusually long."), { hint: "Check the server window for errors, then try again." });
      const { body } = await api("/v1/jobs/" + encodeURIComponent(jobId));
      if (body.status === "done" && body.result) return body.result;
      if (body.status === "failed") {
        const err = body.error || {};
        throw Object.assign(new Error(err.message || "The analysis failed."), { code: err.code });
      }
      showProgress(body);
      await new Promise((r) => setTimeout(r, POLL_MS));
    }
    return null;
  }

  function finish(result) {
    hideProgress();
    addHistory(result);
    render(result);
  }

  function setBusy(b) {
    $("analyzeBtn").disabled = b;
    $("analyzeBtn").querySelector("span").textContent = b ? "Analyzing…" : "Analyze";
  }

  function showProgress(job) {
    const card = $("progressCard");
    if (card.classList.contains("hidden")) { card.classList.remove("hidden"); card.scrollIntoView({ behavior: "smooth", block: "center" }); }
    const p = Math.max(0.02, Math.min(1, job.progress || 0));
    const stage = job.stage || job.status || "queued";
    $("progressStage").textContent = stage;
    $("progressPct").textContent = Math.round(p * 100) + "%";
    $("progressBar").style.width = p * 100 + "%";
    const order = ["comments", "transcript", "audio", "visual", "scor"];
    const s = stage.toLowerCase();
    const at = order.findIndex((k) => s.includes(k) || (k === "transcript" && s.includes("caption")));
    document.querySelectorAll("#steps li").forEach((li, i) => {
      li.classList.toggle("active", i === at);
      li.classList.toggle("done", at > -1 && i < at);
    });
  }
  function hideProgress() { $("progressCard").classList.add("hidden"); }
  function showError(msg, hint) {
    const box = $("errorBox");
    box.innerHTML = `<span class="ico"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><circle cx="12" cy="12" r="9"/><path d="M12 8v5M12 16.5h.01"/></svg></span><div><b>${esc(msg)}</b>${hint ? `<p>${esc(hint)}</p>` : ""}</div>`;
    box.classList.remove("hidden");
    box.scrollIntoView({ behavior: "smooth", block: "center" });
  }
  function hideError() { $("errorBox").classList.add("hidden"); }

  // ------------------------------------------------------------ history --
  function getHistory() { try { return JSON.parse(localStorage.getItem(HISTORY) || "[]"); } catch (_) { return []; } }
  function addHistory(r) {
    try {
      const h = getHistory().filter((x) => x.video_id !== r.video_id);
      h.unshift(r);
      localStorage.setItem(HISTORY, JSON.stringify(h.slice(0, 5)));
    } catch (_) { /* quota: ignore */ }
    drawHistory();
  }
  function drawHistory() {
    const h = getHistory();
    $("recent").innerHTML = h.length
      ? `<span class="lbl">Recent</span>` + h.map((r, i) => `<button type="button" class="chip" data-i="${i}" title="${esc(r.title)}">${esc(r.title || r.video_id)}</button>`).join("")
      : "";
  }

  // ------------------------------------------------------------- render --
  function render(r) {
    current = r;
    playhead = null;
    const peakTab = document.querySelector('.seg-toggle button[data-list="top"]');
    if (peakTab) peakTab.click();
    hiddenSignals = new Set();
    $("results").classList.remove("hidden");
    Array.from($("results").children).forEach((el, i) => { el.classList.remove("reveal"); void el.offsetWidth; el.style.animationDelay = Math.min(i, 8) * 60 + "ms"; el.classList.add("reveal"); });
    const heat = r.full_heatmap || [];
    const estimated = r.source === "estimated";
    const vid = r.video_id;

    // overview
    $("thumb").src = `https://i.ytimg.com/vi/${vid}/hqdefault.jpg`;
    $("thumbLink").href = `https://www.youtube.com/watch?v=${vid}`;
    $("vTitle").textContent = r.title || vid;
    $("confReason").textContent = r.confidence_reason || "";
    $("badges").innerHTML = [
      `<span class="badge ${estimated ? "estimated" : "official"}">${estimated ? "Estimated" : "Official data"}</span>`,
      r.confidence ? `<span class="badge ${esc(r.confidence)}">${esc(r.confidence)} confidence</span>` : "",
      `<span class="badge">${hms(r.duration)}</span>`,
      r.cached ? `<span class="badge">Cached</span>` : "",
    ].join("");
    const d = $("disclaimer");
    d.textContent = r.disclaimer || "";
    d.classList.toggle("hidden", !r.disclaimer);
    $("player").src = `https://www.youtube-nocookie.com/embed/${vid}?rel=0`;
    setNow(null);

    // KPIs
    const scores = heat.map((x) => x.score);
    const top = (r.most_engaging || [])[0];
    const low = (r.least_engaging || [])[0];
    const avg = mean(scores);
    const hot = scores.filter((s) => s >= 0.6).length;
    const win = r.window_seconds || (heat[0] ? heat[0].end - heat[0].start : 0);
    $("kpis").innerHTML = [
      kpi("Peak moment", top ? hms(top.start) : "–", top ? `score ${top.score.toFixed(2)} · tap to play` : "", top && top.start, "accent"),
      kpi("Biggest drop-off", low ? hms(low.start) : "–", low ? `score ${low.score.toFixed(2)} · tap to play` : "", low && low.start),
      kpi("Average engagement", avg.toFixed(2), "out of 1.00"),
      kpi("Hot segments", heat.length ? pct(hot / heat.length) : "–", `${hot} of ${heat.length} score ≥ 0.6`),
      kpi(estimated ? "Signals used" : "Data points", estimated ? String((r.signals_used || []).length) : String(heat.length), estimated ? `${win}s segments` : "from YouTube"),
    ].join("");

    // lists
    $("topList").innerHTML = (r.most_engaging || []).map((m, i) => momentHTML(m, i, true)).join("") || `<li class="empty">No clear peaks.</li>`;
    $("lowList").innerHTML = (r.least_engaging || []).map((m, i) => momentHTML(m, i, false)).join("") || `<li class="empty">No clear drop-offs.</li>`;

    // signals
    const sigNames = estimated ? Object.keys((heat[0] && heat[0].signals) || {}) : [];
    $("r-signals").classList.toggle("hidden", !sigNames.length);
    $("navSignals").classList.toggle("hidden", !sigNames.length);
    $("sigStats").classList.toggle("hidden", !estimated);
    $("sigChips").innerHTML = sigNames.map((n, i) => `<button type="button" class="chip" data-sig="${esc(n)}"><span class="dot" style="background:${color(n, i)}"></span>${esc(label(n))}</button>`).join("");
    if (estimated) drawSignalStats(r, heat, sigNames);

    // raw
    $("rawJson").textContent = JSON.stringify(r, null, 2);

    drawCharts();
    $("results").scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function kpi(k, v, s, seek, extra = "") {
    const attr = Number.isFinite(seek) ? ` class="kpi clickable ${extra}" data-seek="${seek}" title="Play from here"` : ` class="kpi ${extra}"`;
    return `<div${attr}><div class="k">${esc(k)}</div><div class="v">${esc(v)}</div><div class="s">${esc(s)}</div></div>`;
  }

  function momentHTML(m, i, isPeak) {
    const sigs = Array.isArray(m.signals) ? m.signals : [];
    const chips = sigs
      .filter((s) => typeof s === "object")
      .slice(0, isPeak ? 3 : 2)
      .map((s, j) => `<span class="chip"><span class="dot" style="background:${color(s.name, j)}"></span>${esc(label(s.name))} ${s.share != null ? pct(s.share) : s.value.toFixed(2)}</span>`)
      .join("");
    const len = Math.round(m.end - m.start);
    return `<li class="moment" data-seek="${m.start}">
      <span class="rank">${i + 1}</span>
      <div>
        <div class="time">${hms(m.start)} – ${hms(m.end)}<small>${len}s</small></div>
        ${chips ? `<div class="chips">${chips}</div>` : ""}
      </div>
      <div class="sc"><b>${m.score.toFixed(2)}</b><div class="mini"><span style="width:${Math.max(3, m.score * 100)}%"></span></div>
      <a class="open" href="${esc(m.link)}" target="_blank" rel="noopener" data-noseek>Open ↗</a></div>
    </li>`;
  }

  function drawSignalStats(r, heat, names) {
    const weights = r.weights || {};
    const wMax = Math.max(...Object.values(weights), 0.0001);
    $("weights").innerHTML = Object.entries(weights)
      .sort((a, b) => b[1] - a[1])
      .map(([n, w], i) => hbar(label(n), pct(w), (w / wMax) * 100, color(n, i)))
      .join("") || `<div class="empty">No weights.</div>`;

    const skipped = r.signals_skipped || {};
    $("skipped").innerHTML = Object.keys(skipped).length
      ? Object.entries(skipped).map(([n, why]) => `<div class="skip"><b>${esc(label(n))} skipped:</b> ${esc(why)}</div>`).join("")
      : `<div class="allgood"><svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12l5 5L20 7"/></svg>Every signal ran</div>`;

    // share of total score each signal produced = weight * value, summed
    const contrib = {};
    names.forEach((n) => (contrib[n] = heat.reduce((a, x) => a + (weights[n] || 0) * (x.signals[n] || 0), 0)));
    const total = Object.values(contrib).reduce((a, b) => a + b, 0) || 1;
    const cMax = Math.max(...Object.values(contrib).map((v) => v / total), 0.0001);
    $("drivers").innerHTML = Object.entries(contrib)
      .sort((a, b) => b[1] - a[1])
      .map(([n, v]) => hbar(label(n), pct(v / total), ((v / total) / cMax) * 100, color(n, names.indexOf(n))))
      .join("");

    const scores = heat.map((x) => x.score);
    $("agreement").innerHTML = names
      .map((n) => [n, pearson(heat.map((x) => x.signals[n] || 0), scores)])
      .sort((a, b) => b[1] - a[1])
      .map(([n, c]) => hbarCentered(label(n), (c >= 0 ? "+" : "") + c.toFixed(2), c, color(n, names.indexOf(n))))
      .join("");
  }
  function hbar(name, val, widthPct, col) {
    return `<div class="hbar"><div class="row"><span><span class="dot" style="background:${col}"></span> ${esc(name)}</span><b>${esc(val)}</b></div><div class="track"><span style="left:0;width:${Math.max(2, widthPct)}%;background:${col}"></span></div></div>`;
  }
  function hbarCentered(name, val, c, col) {
    const w = Math.abs(c) * 50;
    const left = c >= 0 ? 50 : 50 - w;
    return `<div class="hbar"><div class="row"><span><span class="dot" style="background:${col}"></span> ${esc(name)}</span><b>${esc(val)}</b></div><div class="track center"><span style="left:${left}%;width:${Math.max(1, w)}%;background:${col}"></span></div></div>`;
  }

  // ------------------------------------------------------------- charts --
  function drawCharts() {
    if (!current) return;
    const heat = current.full_heatmap || [];
    drawStrip(heat);
    drawMain(heat, current);
    drawSignals(heat);
    drawParts(heat, current.duration);
    drawHist(heat);
  }

  // inferno-like ramp: deep violet -> magenta -> ember -> gold
  const RAMP = [[27, 16, 51], [91, 26, 110], [184, 37, 95], [242, 84, 45], [255, 179, 71], [255, 232, 163]];
  function heatColor(v) {
    const a = Math.max(0, Math.min(1, v)) * (RAMP.length - 1);
    const i = Math.min(RAMP.length - 2, Math.floor(a)), f = a - i;
    const c = RAMP[i].map((x, k) => Math.round(x + (RAMP[i + 1][k] - x) * f));
    return `rgb(${c.join(",")})`;
  }
  function drawStrip() { /* the heat strip is drawn inside the main chart */ }

  function drawMain(heat, r) {
    const box = $("mainChart");
    const W = Math.max(320, box.clientWidth), narrow = W < 600, H = narrow ? 260 : 340;
    const m = { l: 36, r: 14, t: 16, b: 52 };
    const iw = W - m.l - m.r, ih = H - m.t - m.b;
    const dur = r.duration || (heat.length ? heat[heat.length - 1].end : 1);
    const x = (t) => m.l + (t / dur) * iw;
    const y = (v) => m.t + (1 - v) * ih;
    const stripY = m.t + ih + 10, stripH = 14;
    let g = `<defs>
      <linearGradient id="fade" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stop-color="#ff5a1f" stop-opacity=".38"/><stop offset=".6" stop-color="#ff2e63" stop-opacity=".08"/><stop offset="1" stop-color="#ff2e63" stop-opacity="0"/></linearGradient>
      <linearGradient id="stroke" x1="0" x2="1" y1="0" y2="0"><stop offset="0" stop-color="#ffb347"/><stop offset=".5" stop-color="#ff5a1f"/><stop offset="1" stop-color="#ff2e63"/></linearGradient>
      <clipPath id="stripClip"><rect x="${m.l}" y="${stripY}" width="${iw}" height="${stripH}" rx="4"/></clipPath>
      <filter id="glow" x="-20%" y="-20%" width="140%" height="140%"><feGaussianBlur stdDeviation="4" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
    </defs>`;
    [0, 0.25, 0.5, 0.75, 1].forEach((v) => {
      g += `<line x1="${m.l}" x2="${W - m.r}" y1="${y(v)}" y2="${y(v)}" stroke="${C.grid}"/>`;
      g += `<text x="${m.l - 10}" y="${y(v) + 3.5}" text-anchor="end">${v === 0 ? "0" : v === 1 ? "1" : v.toFixed(2).replace(/0$/, "")}</text>`;
    });
    niceTicks(dur, narrow ? 4 : 8).forEach((t) => (g += `<text x="${x(t)}" y="${H - 8}" text-anchor="middle">${hms(t)}</text>`));

    const bands = (list, fill, stroke) => (list || []).map((s) => `<rect x="${x(s.start)}" y="${m.t}" width="${Math.max(2, x(s.end) - x(s.start))}" height="${ih}" fill="${fill}" rx="2"/><rect x="${x(s.start)}" y="${m.t + ih - 2}" width="${Math.max(2, x(s.end) - x(s.start))}" height="3" fill="${stroke}" rx="1.5"/>`).join("");
    g += bands(r.least_engaging, C.dropBand, C.bad);
    g += bands(r.most_engaging, C.peakBand, C.good);

    if (heat.length) {
      const pts = heat.map((p) => [x((p.start + p.end) / 2), y(p.score)]);
      const line = smooth(pts);
      const area = `${line}L${pts[pts.length - 1][0].toFixed(1)},${y(0)}L${pts[0][0].toFixed(1)},${y(0)}Z`;
      g += `<path d="${area}" fill="url(#fade)"/>`;
      g += `<path d="${line}" fill="none" stroke="url(#stroke)" stroke-width="2.2" stroke-linejoin="round" stroke-linecap="round" filter="url(#glow)"/>`;
      const avg = mean(heat.map((p) => p.score));
      g += `<line x1="${m.l}" x2="${W - m.r}" y1="${y(avg)}" y2="${y(avg)}" stroke="${C.ref}" stroke-dasharray="3 5"/>`;
      g += `<text x="${W - m.r}" y="${y(avg) - 7}" text-anchor="end" style="fill:${C.sub}">avg ${avg.toFixed(2)}</text>`;
      // heat strip, like YouTube's own "most replayed" bar
      g += `<g clip-path="url(#stripClip)">` + heat.map((p) => `<rect x="${x(p.start)}" y="${stripY}" width="${Math.max(0.6, x(p.end) - x(p.start)) + 0.5}" height="${stripH}" fill="${heatColor(p.score)}"/>`).join("") + `</g>`;
      g += `<rect x="${m.l}" y="${stripY}" width="${iw}" height="${stripH}" rx="4" fill="none" stroke="${C.edge}"/>`;
      const R = narrow ? 9 : 11, placed = [];
      (r.most_engaging || []).slice(0, 5).forEach((s, i) => {
        const cx = x((s.start + s.end) / 2);
        let cy = y(s.score);
        // nudge a marker up (or down) so numbered circles never sit on top of each other
        for (let k = 0; k < 6 && placed.some(([px, py]) => Math.hypot(px - cx, py - cy) < R * 2 + 2); k++) cy = cy - (R * 2 + 3) >= m.t - 4 ? cy - (R * 2 + 3) : cy + (R * 2 + 3);
        placed.push([cx, cy]);
        g += `<circle cx="${cx}" cy="${cy}" r="${R}" fill="${C.marker}" stroke="${C.good}" stroke-width="1.6"/><text x="${cx}" y="${cy + 3.6}" text-anchor="middle" style="fill:${C.good};font-weight:700;font-size:10.5px">${i + 1}</text>`;
      });
    }
    if (playhead != null) {
      const px = x(playhead);
      g += `<line x1="${px}" x2="${px}" y1="${m.t}" y2="${stripY + stripH}" stroke="${C.ember}" stroke-width="1.5"/><circle cx="${px}" cy="${m.t}" r="4" fill="${C.ember}"/>`;
    }
    g += `<line id="hoverLine" x1="0" x2="0" y1="${m.t}" y2="${stripY + stripH}" stroke="${C.hover}" visibility="hidden"/>`;
    g += `<circle id="hoverDot" r="5" fill="${C.dot}" stroke="#ff5a1f" stroke-width="2" visibility="hidden"/>`;
    g += `<rect class="hit" x="${m.l}" y="${m.t}" width="${iw}" height="${stripY + stripH - m.t}" fill="transparent"/>`;
    box.innerHTML = svgEl(W, H, g);

    const svg = box.querySelector("svg");
    const hit = svg.querySelector(".hit");
    const hl = svg.querySelector("#hoverLine"), hd = svg.querySelector("#hoverDot");
    const at = (evt) => {
      const rect = svg.getBoundingClientRect();
      const t = ((evt.clientX - rect.left) * (W / rect.width) - m.l) / iw * dur;
      return heat.find((p) => t >= p.start && t < p.end) || heat[heat.length - 1];
    };
    hit.addEventListener("mousemove", (evt) => {
      const p = at(evt);
      if (!p) return;
      const xx = x((p.start + p.end) / 2);
      hl.setAttribute("x1", xx); hl.setAttribute("x2", xx); hl.setAttribute("visibility", "visible");
      hd.setAttribute("cx", xx); hd.setAttribute("cy", y(p.score)); hd.setAttribute("visibility", "visible");
      const rows = Object.entries(p.signals || {}).map(([n, v], i) => `<div class="r"><span><span class="dot" style="background:${color(n, i)}"></span>${esc(label(n))}</span><b>${v.toFixed(2)}</b></div>`).join("");
      showTip(evt, `<div class="t">${hms(p.start)} – ${hms(p.end)}</div><div class="r main"><span>Score</span><b>${p.score.toFixed(2)}</b></div>${rows}<div class="hint">Click to play from here</div>`);
    });
    hit.addEventListener("mouseleave", () => { hl.setAttribute("visibility", "hidden"); hd.setAttribute("visibility", "hidden"); hideTip(); });
    hit.addEventListener("click", (evt) => { const p = at(evt); if (p) seek(p.start); });
  }

  // centred moving average over +-k neighbours (display only; tooltips show raw values)
  function rolling(a, k) {
    if (!k) return a;
    return a.map((_, i) => { let s = 0, c = 0; for (let d = -k; d <= k; d++) { const v = a[i + d]; if (v != null) { s += v; c++; } } return s / c; });
  }

  // monotone cubic path: smooth, but never overshoots a real peak or dip
  function smooth(pts) {
    const n = pts.length;
    if (n < 3) return "M" + pts.map((p) => p.map((v) => v.toFixed(1)).join(",")).join("L");
    const dx = [], dy = [], ms = [];
    for (let i = 0; i < n - 1; i++) { dx[i] = pts[i + 1][0] - pts[i][0]; dy[i] = pts[i + 1][1] - pts[i][1]; ms[i] = dy[i] / (dx[i] || 1); }
    const t = [ms[0]];
    for (let i = 1; i < n - 1; i++) t[i] = ms[i - 1] * ms[i] <= 0 ? 0 : (3 * (dx[i - 1] + dx[i])) / ((2 * dx[i] + dx[i - 1]) / ms[i - 1] + (dx[i] + 2 * dx[i - 1]) / ms[i]);
    t[n - 1] = ms[n - 2];
    let d = `M${pts[0][0].toFixed(1)},${pts[0][1].toFixed(1)}`;
    for (let i = 0; i < n - 1; i++) {
      const h = dx[i] / 3;
      d += `C${(pts[i][0] + h).toFixed(1)},${(pts[i][1] + h * t[i]).toFixed(1)} ${(pts[i + 1][0] - h).toFixed(1)},${(pts[i + 1][1] - h * t[i + 1]).toFixed(1)} ${pts[i + 1][0].toFixed(1)},${pts[i + 1][1].toFixed(1)}`;
    }
    return d;
  }

  function drawSignals(heat) {
    const box = $("sigChart");
    if (!heat.length || !heat[0].signals || $("r-signals").classList.contains("hidden")) { box.innerHTML = ""; return; }
    const names = Object.keys(heat[0].signals);
    const W = Math.max(320, box.clientWidth), H = W < 600 ? 220 : 260;
    const m = { l: 36, r: 14, t: 10, b: 28 };
    const iw = W - m.l - m.r, ih = H - m.t - m.b;
    const dur = current.duration || heat[heat.length - 1].end;
    const x = (t) => m.l + (t / dur) * iw;
    const y = (v) => m.t + (1 - v) * ih;
    let g = "";
    [0, 0.5, 1].forEach((v) => {
      g += `<line x1="${m.l}" x2="${W - m.r}" y1="${y(v)}" y2="${y(v)}" stroke="${C.grid}"/><text x="${m.l - 10}" y="${y(v) + 3.5}" text-anchor="end">${v}</text>`;
    });
    niceTicks(dur, W < 600 ? 4 : 8).forEach((t) => (g += `<text x="${x(t)}" y="${H - 8}" text-anchor="middle">${hms(t)}</text>`));
    names.forEach((n, i) => {
      if (hiddenSignals.has(n)) return;
      const vals = rolling(heat.map((p) => p.signals[n] || 0), $("smoothSig").checked ? 2 : 0);
      const d = smooth(heat.map((p, k) => [x((p.start + p.end) / 2), y(vals[k])]));
      g += `<path d="${d}" fill="none" stroke="${color(n, i)}" stroke-width="1.7" stroke-linejoin="round" stroke-linecap="round" opacity=".9"/>`;
    });
    g += `<line class="hl" x1="0" x2="0" y1="${m.t}" y2="${m.t + ih}" stroke="${C.hover}" visibility="hidden"/>`;
    g += `<rect class="hit" x="${m.l}" y="${m.t}" width="${iw}" height="${ih}" fill="transparent"/>`;
    box.innerHTML = svgEl(W, H, g);
    const svg = box.querySelector("svg");
    const hit = svg.querySelector(".hit"), shl = svg.querySelector(".hl");
    const at = (evt) => {
      const rect = svg.getBoundingClientRect();
      const t = ((evt.clientX - rect.left) * (W / rect.width) - m.l) / iw * dur;
      return heat.find((p) => t >= p.start && t < p.end) || heat[heat.length - 1];
    };
    hit.addEventListener("mousemove", (evt) => {
      const p = at(evt);
      const xx = x((p.start + p.end) / 2);
      shl.setAttribute("x1", xx); shl.setAttribute("x2", xx); shl.setAttribute("visibility", "visible");
      const rows = names.filter((n) => !hiddenSignals.has(n)).map((n, i) => `<div class="r"><span><span class="dot" style="background:${color(n, names.indexOf(n))}"></span>${esc(label(n))}</span><b>${(p.signals[n] || 0).toFixed(2)}</b></div>`).join("");
      showTip(evt, `<div class="t">${hms(p.start)} – ${hms(p.end)}</div>${rows}`);
    });
    hit.addEventListener("mouseleave", () => { shl.setAttribute("visibility", "hidden"); hideTip(); });
    hit.addEventListener("click", (evt) => seek(at(evt).start));
    document.querySelectorAll("#sigChips .chip").forEach((c) => c.classList.toggle("off", hiddenSignals.has(c.dataset.sig)));
  }

  function barChart(box, cats, vals, opts = {}) {
    const W = Math.max(280, box.clientWidth), H = opts.h || 220;
    const m = { l: 36, r: 8, t: 22, b: 30 };
    const iw = W - m.l - m.r, ih = H - m.t - m.b;
    const max = opts.max || Math.max(...vals, 0.0001);
    const bw = iw / cats.length;
    let g = "";
    const ticks = opts.ticks || [0, max / 2, max];
    ticks.forEach((v) => {
      const yy = m.t + (1 - v / max) * ih;
      g += `<line x1="${m.l}" x2="${W - m.r}" y1="${yy}" y2="${yy}" stroke="${C.grid}"/><text x="${m.l - 10}" y="${yy + 3.5}" text-anchor="end">${opts.fmtTick ? opts.fmtTick(v) : v}</text>`;
    });
    vals.forEach((v, i) => {
      const h = (v / max) * ih;
      const bx = m.l + i * bw + bw * 0.16;
      const w = bw * 0.68;
      const fill = opts.colors ? opts.colors[i] : C.bar;
      g += `<rect x="${bx}" y="${m.t + ih - h}" width="${w}" height="${Math.max(0, h)}" rx="5" fill="${fill}"><title>${esc(cats[i])}: ${opts.fmt ? opts.fmt(v) : v}</title></rect>`;
      if (opts.labels !== false) g += `<text x="${bx + w / 2}" y="${m.t + ih - h - 7}" text-anchor="middle" style="fill:${C.label}">${opts.fmt ? opts.fmt(v) : v}</text>`;
      if (!opts.skipCat || i % opts.skipCat === 0) g += `<text class="cat" x="${bx + w / 2}" y="${H - 9}" text-anchor="middle">${esc(cats[i])}</text>`;
    });
    box.innerHTML = svgEl(W, H, `<defs><linearGradient id="barGrad" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stop-color="#ffb347"/><stop offset=".5" stop-color="#ff5a1f"/><stop offset="1" stop-color="#ff2e63"/></linearGradient></defs>` + g);
  }

  function drawParts(heat, duration) {
    const dur = duration || (heat.length ? heat[heat.length - 1].end : 0);
    const names = ["Intro", "Early", "Middle", "Late", "Ending"];
    const vals = names.map((_, i) => {
      const a = (dur * i) / 5, b = (dur * (i + 1)) / 5;
      return mean(heat.filter((p) => (p.start + p.end) / 2 >= a && (p.start + p.end) / 2 < b).map((p) => p.score));
    });
    const best = vals.indexOf(Math.max(...vals));
    barChart($("partsChart"), names.map((n, i) => `${n}`), vals, {
      max: 1, ticks: [0, 0.5, 1], fmt: (v) => v.toFixed(2), fmtTick: (v) => v,
      colors: vals.map((_, i) => (i === best ? "url(#barGrad)" : C.bar)),
    });
  }

  function drawHist(heat) {
    const bins = new Array(10).fill(0);
    heat.forEach((p) => bins[Math.min(9, Math.floor(p.score * 10))]++);
    const cats = bins.map((_, i) => (i / 10).toFixed(1));
    barChart($("histChart"), cats, bins, {
      fmt: (v) => String(v), fmtTick: (v) => Math.round(v),
      colors: bins.map((_, i) => heatColor((i + 0.5) / 10)),
      skipCat: $("histChart").clientWidth < 420 ? 2 : 1,
    });
  }

  // ------------------------------------------------------------ tooltip --
  const tip = $("tooltip");
  function showTip(evt, html) {
    tip.innerHTML = html;
    tip.classList.remove("hidden");
    const pad = 14, tw = tip.offsetWidth, th = tip.offsetHeight;
    let left = evt.clientX + pad, top = evt.clientY + pad;
    if (left + tw > innerWidth - 8) left = evt.clientX - tw - pad;
    if (top + th > innerHeight - 8) top = evt.clientY - th - pad;
    tip.style.left = left + "px"; tip.style.top = top + "px";
  }
  function hideTip() { tip.classList.add("hidden"); }

  // ------------------------------------------------------------- player --
  function setNow(sec) {
    const el = $("nowPlaying");
    el.classList.toggle("playing", sec != null);
    el.lastElementChild.textContent = sec == null ? "Pick a moment to jump there." : `Playing from ${hms(sec)}`;
  }
  function seek(sec) {
    if (!current) return;
    const s = Math.max(0, Math.floor(sec));
    $("player").src = `https://www.youtube-nocookie.com/embed/${current.video_id}?start=${s}&autoplay=1&rel=0`;
    setNow(s);
    playhead = s;
    drawMain(current.full_heatmap || [], current);
    const pr = $("player").getBoundingClientRect();
    if (pr.top < 64 || pr.bottom > innerHeight) $("player").scrollIntoView({ behavior: "smooth", block: "center" });
  }

  // ------------------------------------------------------------ exports --
  function download(name, text, type) {
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([text], { type }));
    a.download = name;
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  }
  function toCSV(r) {
    const heat = r.full_heatmap || [];
    const names = heat[0] && heat[0].signals ? Object.keys(heat[0].signals) : [];
    const rows = [["start_s", "end_s", "start", "end", "score", ...names].join(",")];
    heat.forEach((p) => rows.push([p.start, p.end, hms(p.start), hms(p.end), p.score, ...names.map((n) => p.signals[n] ?? "")].join(",")));
    return rows.join("\n");
  }

  // ------------------------------------------------------------- events --
  $("analyzeForm").addEventListener("submit", analyze);
  $("connToggle").addEventListener("click", () => openConn($("connection").classList.contains("collapsed")));
  $("navConn").addEventListener("click", () => openConn(true));
  document.querySelectorAll(".os-tabs button").forEach((b) => b.addEventListener("click", () => { setOS(b.dataset.os); saveSettings(); }));
  document.querySelectorAll("[data-copy]").forEach((b) => b.addEventListener("click", async () => {
    try { await navigator.clipboard.writeText(b.dataset.copy); b.textContent = "Copied"; setTimeout(() => (b.textContent = "Copy"), 1400); } catch (_) { /* ignore */ }
  }));  $("showKey").addEventListener("click", () => {
    const k = $("apiKey");
    k.type = k.type === "password" ? "text" : "password";
    $("showKey").textContent = k.type === "password" ? "Show" : "Hide";
  });
  $("testConn").addEventListener("click", () => { saveSettings(); testConnection(); });
  ["apiBase", "apiKey"].forEach((id) => $(id).addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); saveSettings(); testConnection(); } }));
  ["apiBase", "apiKey", "windowSel", "remember"].forEach((id) => $(id).addEventListener("change", saveSettings));
  $("sampleBtn").addEventListener("click", async () => {
    hideError();
    try {
      const r = window.__SAMPLE__ || await (await fetch("sample.json")).json();
      render(r);
    } catch (_) { showError("Couldn't load the sample."); }
  });
  $("recent").addEventListener("click", (e) => {
    const b = e.target.closest("[data-i]");
    if (b) { const r = getHistory()[+b.dataset.i]; if (r) { hideError(); render(r); } }
  });
  document.addEventListener("click", (e) => {
    if (e.target.closest("[data-noseek]")) return;
    const s = e.target.closest("[data-seek]");
    if (s && s.closest("#results")) seek(parseFloat(s.dataset.seek));
  });
  document.querySelectorAll(".seg-toggle button").forEach((b) => b.addEventListener("click", () => {
    const low = b.dataset.list === "low";
    document.querySelectorAll(".seg-toggle button").forEach((x) => x.classList.toggle("on", x === b));
    $("topList").classList.toggle("hidden", low);
    $("lowList").classList.toggle("hidden", !low);
    $("momTitle").textContent = low ? "Drop-offs" : "Top moments";
    $("momSub").textContent = low ? "Where attention is weakest, and which signals were flat." : "The highest-scoring stretches, with what drove each one.";
  }));
  $("smoothSig").addEventListener("change", () => current && drawSignals(current.full_heatmap || []));
  $("sigChips").addEventListener("click", (e) => {
    const c = e.target.closest("[data-sig]");
    if (!c) return;
    const n = c.dataset.sig;
    hiddenSignals.has(n) ? hiddenSignals.delete(n) : hiddenSignals.add(n);
    drawSignals(current.full_heatmap || []);
  });
  $("dlJson").addEventListener("click", () => current && download(`heatmap-${current.video_id}.json`, JSON.stringify(current, null, 2), "application/json"));
  $("dlCsv").addEventListener("click", () => current && download(`heatmap-${current.video_id}.csv`, toCSV(current), "text/csv"));
  $("copyJson").addEventListener("click", async () => {
    if (!current) return;
    const lbl = $("copyJson").querySelector("span");
    try { await navigator.clipboard.writeText(JSON.stringify(current, null, 2)); lbl.textContent = "Copied"; setTimeout(() => (lbl.textContent = "Copy JSON"), 1500); } catch (_) { /* ignore */ }
  });
  document.addEventListener("themechange", (e) => {
    C = THEMES[e.detail === "light" ? "light" : "dark"];
    if (!current) return;
    const heat = current.full_heatmap || [];
    const names = current.source === "estimated" ? Object.keys((heat[0] && heat[0].signals) || {}) : [];
    $("sigChips").innerHTML = names.map((n, i) => `<button type="button" class="chip${hiddenSignals.has(n) ? " off" : ""}" data-sig="${esc(n)}"><span class="dot" style="background:${color(n, i)}"></span>${esc(label(n))}</button>`).join("");
    if (current.source === "estimated") drawSignalStats(current, heat, names);
    $("topList").innerHTML = (current.most_engaging || []).map((m, i) => momentHTML(m, i, true)).join("") || `<li class="empty">No clear peaks.</li>`;
    $("lowList").innerHTML = (current.least_engaging || []).map((m, i) => momentHTML(m, i, false)).join("") || `<li class="empty">No clear drop-offs.</li>`;
    drawCharts();
  });
  let rt;
  addEventListener("resize", () => { clearTimeout(rt); rt = setTimeout(drawCharts, 120); });

  // decorative hero bars
  if ($("heroStrip")) $("heroStrip").innerHTML = Array.from({ length: 36 }, (_, i) => {
    const base = 0.18 + 0.8 * Math.pow(Math.sin((i / 35) * Math.PI * 1.15 + 0.4) * 0.5 + 0.5, 2.2) * (0.6 + 0.4 * Math.sin(i * 1.7));
    const a = Math.max(0.12, Math.min(1, base)), b = Math.max(0.12, Math.min(1, base * (0.55 + 0.6 * ((i * 37) % 10) / 10)));
    return `<i style="--a:${a.toFixed(2)};--b:${b.toFixed(2)};animation-delay:${(-i * 0.13).toFixed(2)}s"></i>`;
  }).join("");

  setOS(currentOS);
  loadSettings();
  drawHistory();
  testConnection({ quiet: true }).then((ok) => { if (!ok && !normBase($("apiBase").value)) openConn(true); });
  if (window.__SAMPLE__ || new URLSearchParams(location.search).get("sample") != null) $("sampleBtn").click();
})();
