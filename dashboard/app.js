/* Heatmap Dashboard: talks to the YouTube Heatmap Extractor API and draws the result. */
(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const SIGNAL_COLORS = {
    comments: "#5b7bb5",
    transcript: "#4e7a5c",
    audio: "#c08a52",
    visual: "#8a7fb0",
    official_most_replayed: "#ff4d00",
  };
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
  const color = (n, i = 0) => SIGNAL_COLORS[n] || ["#7e9c9b", "#c9a3a8", "#d9c489"][i % 3];
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
      if (s.apiBase && s.apiKey && !params.get("api")) $("connection").classList.add("collapsed");
    } catch (_) { /* ignore */ }
  }
  function saveSettings() {
    const remember = $("remember").checked;
    const s = { remember, window: $("windowSel").value };
    if (remember) { s.apiBase = normBase($("apiBase").value); s.apiKey = $("apiKey").value.trim(); }
    localStorage.setItem(STORE, JSON.stringify(s));
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
      err.hint = "Check the API URL (the tunnel URL changes every time the server restarts), that the server window is still open, and that your server is up to date so it allows requests from this dashboard.";
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
      if (res.status === 530 || res.status === 502 || res.status === 404 && !body) e.hint = "The tunnel isn't reaching your server. Restart start-windows.bat and paste the new URL.";
      throw e;
    }
    return { status: res.status, body };
  }

  async function testConnection() {
    const pill = $("connStatus");
    if (!normBase($("apiBase").value)) { setPill(pill, "warn", "Add the API URL"); return false; }
    setPill(pill, "neutral", "Checking…");
    try {
      const { body } = await api("/health");
      setPill(pill, body.status === "ok" ? "ok" : "warn", body.status === "ok" ? `Connected · v${body.version}` : "Server degraded");
      return true;
    } catch (e) {
      setPill(pill, "bad", e.status ? `Error ${e.status}` : "Unreachable");
      return false;
    }
  }
  function setPill(el, kind, text) { el.className = "pill " + kind; el.textContent = text; }

  // ----------------------------------------------------------- analysis --
  async function analyze(ev) {
    ev && ev.preventDefault();
    hideError();
    const url = $("ytUrl").value.trim();
    if (!videoIdFrom(url)) return showError("That doesn't look like a YouTube link.", "Paste a full video URL like https://www.youtube.com/watch?v=… or a youtu.be link.");
    if (!normBase($("apiBase").value) || !$("apiKey").value.trim()) {
      $("connection").classList.remove("collapsed");
      return showError("Add your API URL and key first.", "Both are shown in the server window when you run start-windows.bat.");
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
    $("analyzeBtn").textContent = b ? "Analyzing…" : "Analyze";
  }

  function showProgress(job) {
    $("progressCard").classList.remove("hidden");
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
    box.innerHTML = `<b>${esc(msg)}</b>${hint ? `<p>${esc(hint)}</p>` : ""}`;
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
      ? `<span class="muted small-text">Recent</span>` + h.map((r, i) => `<button type="button" class="chip" data-i="${i}" title="${esc(r.title)}">${esc(r.title || r.video_id)}</button>`).join("")
      : "";
  }

  // ------------------------------------------------------------- render --
  function render(r) {
    current = r;
    hiddenSignals = new Set();
    $("results").classList.remove("hidden");
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
      `<span class="badge">${hms(r.duration)} long</span>`,
      r.cached ? `<span class="badge">Cached</span>` : "",
    ].join("");
    const d = $("disclaimer");
    d.textContent = r.disclaimer || "";
    d.classList.toggle("hidden", !r.disclaimer);
    $("player").src = `https://www.youtube-nocookie.com/embed/${vid}?rel=0`;
    $("nowPlaying").textContent = "Pick a moment to jump there.";

    // KPIs
    const scores = heat.map((x) => x.score);
    const top = (r.most_engaging || [])[0];
    const low = (r.least_engaging || [])[0];
    const avg = mean(scores);
    const hot = scores.filter((s) => s >= 0.6).length;
    const win = r.window_seconds || (heat[0] ? heat[0].end - heat[0].start : 0);
    $("kpis").innerHTML = [
      kpi("Peak moment", top ? hms(top.start) : "–", top ? `score ${top.score.toFixed(2)}` : "", top && top.start),
      kpi("Biggest drop-off", low ? hms(low.start) : "–", low ? `score ${low.score.toFixed(2)}` : "", low && low.start),
      kpi("Average engagement", avg.toFixed(2), "out of 1.00"),
      kpi("Hot segments", heat.length ? pct(hot / heat.length) : "–", `${hot} of ${heat.length} score ≥ 0.6`),
      kpi(estimated ? "Signals used" : "Data points", estimated ? String((r.signals_used || []).length) : String(heat.length), estimated ? `${win}s segments` : "from YouTube"),
    ].join("");

    // lists
    $("topList").innerHTML = (r.most_engaging || []).map((m, i) => momentHTML(m, i, true)).join("") || `<li class="empty">No clear peaks.</li>`;
    $("lowList").innerHTML = (r.least_engaging || []).map((m, i) => momentHTML(m, i, false)).join("") || `<li class="empty">No clear drop-offs.</li>`;

    // signals
    const sigNames = estimated ? Object.keys((heat[0] && heat[0].signals) || {}) : [];
    $("signalsCard").classList.toggle("hidden", !sigNames.length);
    $("sigStats").classList.toggle("hidden", !estimated);
    $("sigChips").innerHTML = sigNames.map((n, i) => `<button type="button" class="chip" data-sig="${esc(n)}"><span class="dot" style="background:${color(n, i)}"></span>${esc(label(n))}</button>`).join("");
    if (estimated) drawSignalStats(r, heat, sigNames);

    // raw
    $("rawJson").textContent = JSON.stringify(r, null, 2);

    drawCharts();
    $("results").scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function kpi(k, v, s, seek) {
    const attr = Number.isFinite(seek) ? ` class="kpi clickable" data-seek="${seek}" title="Play from here"` : ` class="kpi"`;
    return `<div${attr}><div class="k">${esc(k)}</div><div class="v">${esc(v)}</div><div class="s">${esc(s)}</div></div>`;
  }

  function momentHTML(m, i, isPeak) {
    const sigs = Array.isArray(m.signals) ? m.signals : [];
    const chips = sigs
      .filter((s) => typeof s === "object")
      .slice(0, 4)
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
      <a class="open" href="${esc(m.link)}" target="_blank" rel="noopener" data-noseek>YouTube ↗</a></div>
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
      : `<div class="chip" style="align-self:flex-start"><span class="dot" style="background:var(--good)"></span>Every signal ran</div>`;

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

  function heatColor(v) {
    // pale peach -> brand heat
    const a = Math.max(0, Math.min(1, v));
    const c0 = [255, 236, 226], c1 = [255, 77, 0];
    const mix = c0.map((x, i) => Math.round(x + (c1[i] - x) * Math.pow(a, 1.15)));
    return `rgb(${mix.join(",")})`;
  }
  function drawStrip(heat) {
    $("strip").innerHTML = heat.map((x) => `<span style="background:${heatColor(x.score)};flex:${Math.max(0.1, x.end - x.start)}" data-seek="${x.start}"></span>`).join("");
  }

  function drawMain(heat, r) {
    const box = $("mainChart");
    const W = Math.max(320, box.clientWidth), H = W < 600 ? 220 : 280;
    const m = { l: 34, r: 12, t: 14, b: 26 };
    const iw = W - m.l - m.r, ih = H - m.t - m.b;
    const dur = r.duration || (heat.length ? heat[heat.length - 1].end : 1);
    const x = (t) => m.l + (t / dur) * iw;
    const y = (v) => m.t + (1 - v) * ih;
    let g = "";
    [0, 0.25, 0.5, 0.75, 1].forEach((v) => {
      g += `<line x1="${m.l}" x2="${W - m.r}" y1="${y(v)}" y2="${y(v)}" stroke="rgba(29,29,31,.07)"/>`;
      g += `<text x="${m.l - 8}" y="${y(v) + 4}" text-anchor="end">${v.toFixed(2).replace(/0$/, "")}</text>`;
    });
    const ticks = niceTicks(dur, W < 600 ? 4 : 7);
    ticks.forEach((t) => (g += `<text x="${x(t)}" y="${H - 6}" text-anchor="middle">${hms(t)}</text>`));

    const bands = (list, fill, stroke) => (list || []).map((s) => `<rect x="${x(s.start)}" y="${m.t}" width="${Math.max(2, x(s.end) - x(s.start))}" height="${ih}" fill="${fill}"/><line x1="${x(s.start)}" x2="${x(s.end)}" y1="${m.t + ih}" y2="${m.t + ih}" stroke="${stroke}" stroke-width="3"/>`).join("");
    g += bands(r.least_engaging, "rgba(156,99,94,.10)", "#9c635e");
    g += bands(r.most_engaging, "rgba(96,120,104,.15)", "#4e7a5c");

    if (heat.length) {
      const pts = heat.map((p) => [x((p.start + p.end) / 2), y(p.score)]);
      const line = "M" + pts.map((p) => p.map((v) => v.toFixed(1)).join(",")).join("L");
      const area = `${line}L${pts[pts.length - 1][0].toFixed(1)},${y(0)}L${pts[0][0].toFixed(1)},${y(0)}Z`;
      g += `<defs><linearGradient id="fade" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stop-color="#ff4d00" stop-opacity=".22"/><stop offset="1" stop-color="#ff4d00" stop-opacity="0"/></linearGradient></defs>`;
      g += `<path d="${area}" fill="url(#fade)"/>`;
      g += `<path d="${line}" fill="none" stroke="#1d1d1f" stroke-width="1.6" stroke-linejoin="round" stroke-linecap="round"/>`;
      const avg = mean(heat.map((p) => p.score));
      g += `<line x1="${m.l}" x2="${W - m.r}" y1="${y(avg)}" y2="${y(avg)}" stroke="rgba(29,29,31,.3)" stroke-dasharray="4 4"/>`;
      g += `<text x="${W - m.r}" y="${y(avg) - 6}" text-anchor="end">avg ${avg.toFixed(2)}</text>`;
      (r.most_engaging || []).slice(0, 5).forEach((s, i) => {
        const cx = x((s.start + s.end) / 2), cy = y(s.score);
        g += `<circle cx="${cx}" cy="${cy}" r="9" fill="#4e7a5c" stroke="#fff" stroke-width="2"/><text x="${cx}" y="${cy + 3.5}" text-anchor="middle" style="fill:#fff;font-weight:700;font-size:10px">${i + 1}</text>`;
      });
    }
    g += `<line id="hoverLine" x1="0" x2="0" y1="${m.t}" y2="${m.t + ih}" stroke="rgba(29,29,31,.4)" visibility="hidden"/>`;
    g += `<rect class="hit" x="${m.l}" y="${m.t}" width="${iw}" height="${ih}" fill="transparent"/>`;
    box.innerHTML = svgEl(W, H, g);

    const svg = box.querySelector("svg");
    const hit = svg.querySelector(".hit");
    const hl = svg.querySelector("#hoverLine");
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
      const rows = Object.entries(p.signals || {}).map(([n, v], i) => `<div class="r"><span><span class="dot" style="background:${color(n, i)}"></span>${esc(label(n))}</span><b>${v.toFixed(2)}</b></div>`).join("");
      showTip(evt, `<div class="t">${hms(p.start)} – ${hms(p.end)}</div><div class="r"><span>Score</span><b>${p.score.toFixed(2)}</b></div>${rows}<div class="hint">Click to play</div>`);
    });
    hit.addEventListener("mouseleave", () => { hl.setAttribute("visibility", "hidden"); hideTip(); });
    hit.addEventListener("click", (evt) => { const p = at(evt); if (p) seek(p.start); });
  }

  function drawSignals(heat) {
    const box = $("sigChart");
    if (!heat.length || !heat[0].signals || $("signalsCard").classList.contains("hidden")) { box.innerHTML = ""; return; }
    const names = Object.keys(heat[0].signals);
    const W = Math.max(320, box.clientWidth), H = W < 600 ? 200 : 240;
    const m = { l: 34, r: 12, t: 10, b: 26 };
    const iw = W - m.l - m.r, ih = H - m.t - m.b;
    const dur = current.duration || heat[heat.length - 1].end;
    const x = (t) => m.l + (t / dur) * iw;
    const y = (v) => m.t + (1 - v) * ih;
    let g = "";
    [0, 0.5, 1].forEach((v) => {
      g += `<line x1="${m.l}" x2="${W - m.r}" y1="${y(v)}" y2="${y(v)}" stroke="rgba(29,29,31,.07)"/><text x="${m.l - 8}" y="${y(v) + 4}" text-anchor="end">${v}</text>`;
    });
    niceTicks(dur, W < 600 ? 4 : 7).forEach((t) => (g += `<text x="${x(t)}" y="${H - 6}" text-anchor="middle">${hms(t)}</text>`));
    names.forEach((n, i) => {
      if (hiddenSignals.has(n)) return;
      const d = "M" + heat.map((p) => `${x((p.start + p.end) / 2).toFixed(1)},${y(p.signals[n] || 0).toFixed(1)}`).join("L");
      g += `<path d="${d}" fill="none" stroke="${color(n, i)}" stroke-width="1.4" stroke-linejoin="round" stroke-linecap="round" opacity=".85"/>`;
    });
    g += `<rect class="hit" x="${m.l}" y="${m.t}" width="${iw}" height="${ih}" fill="transparent"/>`;
    box.innerHTML = svgEl(W, H, g);
    const svg = box.querySelector("svg");
    const hit = svg.querySelector(".hit");
    const at = (evt) => {
      const rect = svg.getBoundingClientRect();
      const t = ((evt.clientX - rect.left) * (W / rect.width) - m.l) / iw * dur;
      return heat.find((p) => t >= p.start && t < p.end) || heat[heat.length - 1];
    };
    hit.addEventListener("mousemove", (evt) => {
      const p = at(evt);
      const rows = names.filter((n) => !hiddenSignals.has(n)).map((n, i) => `<div class="r"><span><span class="dot" style="background:${color(n, names.indexOf(n))}"></span>${esc(label(n))}</span><b>${(p.signals[n] || 0).toFixed(2)}</b></div>`).join("");
      showTip(evt, `<div class="t">${hms(p.start)} – ${hms(p.end)}</div>${rows}`);
    });
    hit.addEventListener("mouseleave", hideTip);
    hit.addEventListener("click", (evt) => seek(at(evt).start));
    document.querySelectorAll("#sigChips .chip").forEach((c) => c.classList.toggle("off", hiddenSignals.has(c.dataset.sig)));
  }

  function barChart(box, cats, vals, opts = {}) {
    const W = Math.max(280, box.clientWidth), H = opts.h || 200;
    const m = { l: 34, r: 8, t: 18, b: 30 };
    const iw = W - m.l - m.r, ih = H - m.t - m.b;
    const max = opts.max || Math.max(...vals, 0.0001);
    const bw = iw / cats.length;
    let g = "";
    const ticks = opts.ticks || [0, max / 2, max];
    ticks.forEach((v) => {
      const yy = m.t + (1 - v / max) * ih;
      g += `<line x1="${m.l}" x2="${W - m.r}" y1="${yy}" y2="${yy}" stroke="rgba(29,29,31,.07)"/><text x="${m.l - 8}" y="${yy + 4}" text-anchor="end">${opts.fmtTick ? opts.fmtTick(v) : v}</text>`;
    });
    vals.forEach((v, i) => {
      const h = (v / max) * ih;
      const bx = m.l + i * bw + bw * 0.16;
      const w = bw * 0.68;
      const fill = opts.colors ? opts.colors[i] : "#1d1d1f";
      g += `<rect x="${bx}" y="${m.t + ih - h}" width="${w}" height="${Math.max(0, h)}" rx="4" fill="${fill}"><title>${esc(cats[i])}: ${opts.fmt ? opts.fmt(v) : v}</title></rect>`;
      if (opts.labels !== false) g += `<text x="${bx + w / 2}" y="${m.t + ih - h - 5}" text-anchor="middle" style="fill:#1d1d1f">${opts.fmt ? opts.fmt(v) : v}</text>`;
      if (!opts.skipCat || i % opts.skipCat === 0) g += `<text class="cat" x="${bx + w / 2}" y="${H - 9}" text-anchor="middle">${esc(cats[i])}</text>`;
    });
    box.innerHTML = svgEl(W, H, g);
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
      colors: vals.map((_, i) => (i === best ? "#ff4d00" : "rgba(29,29,31,.78)")),
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
  function seek(sec) {
    if (!current) return;
    const s = Math.max(0, Math.floor(sec));
    $("player").src = `https://www.youtube-nocookie.com/embed/${current.video_id}?start=${s}&autoplay=1&rel=0`;
    $("nowPlaying").textContent = `Playing from ${hms(s)}.`;
    if (innerWidth < 760) $("player").scrollIntoView({ behavior: "smooth", block: "center" });
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
  $("settingsToggle").addEventListener("click", () => $("connection").classList.toggle("collapsed"));
  $("showKey").addEventListener("click", () => {
    const k = $("apiKey");
    k.type = k.type === "password" ? "text" : "password";
    $("showKey").textContent = k.type === "password" ? "Show" : "Hide";
  });
  $("testConn").addEventListener("click", () => { saveSettings(); testConnection(); });
  ["apiBase", "apiKey", "windowSel", "remember"].forEach((id) => $(id).addEventListener("change", saveSettings));
  $("sampleBtn").addEventListener("click", async () => {
    hideError();
    try {
      const r = await (await fetch("sample.json")).json();
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
    try { await navigator.clipboard.writeText(JSON.stringify(current, null, 2)); $("copyJson").textContent = "Copied"; setTimeout(() => ($("copyJson").textContent = "Copy JSON"), 1500); } catch (_) { /* ignore */ }
  });
  let rt;
  addEventListener("resize", () => { clearTimeout(rt); rt = setTimeout(drawCharts, 120); });

  loadSettings();
  drawHistory();
})();
