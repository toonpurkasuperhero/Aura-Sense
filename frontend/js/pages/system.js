import { api } from "../api.js";
import { $, esc, icon, toast } from "../ui.js";

export async function render(root, _p, ctx) {
  ctx.title("System & knowledge", "Local AI engine, service manuals and repair-centre directory");
  const [h, sc] = await Promise.all([api.get("/api/health"), api.get("/api/service-centres")]);
  const g = h.gemma || {};
  const row = (k, v) => `<div class="row" style="justify-content:space-between;padding:7px 0;border-bottom:1px solid var(--border)"><span class="muted">${k}</span><b>${v}</b></div>`;
  root.innerHTML = `
    <div class="grid g3">
      <div class="card"><div class="card-h">${icon("brain")}<h3>Gemma 4 engine</h3><span class="sp"></span><span class="badge ${g.model_present ? "ok" : "bad"}"><span class="dot"></span>${g.model_present ? "Ready" : "Missing"}</span></div>
        <div class="card-pad">${row("Model", `<span class="mono">${esc(g.model)}</span>`)}${row("Runtime", `Ollama ${esc(g.ollama || "–")}`)}
          ${row("Loaded in GPU", g.model_loaded ? "Yes" : "On first call")}${row("Audio input", g.audio_native ? "Native (Gemma hears it)" : "Spectrogram + DSP")}${row("Data leaves the site", "Never")}</div></div>
      <div class="card"><div class="card-h">${icon("send")}<h3>Notifications</h3></div>
        <div class="card-pad">${row("WhatsApp / SMS deep links", '<span class="badge ok">ready</span>')}
          ${row("ntfy push", h.notify.ntfy ? '<span class="badge ok">on</span>' : '<span class="badge">off</span>')}
          ${row("Telegram bot", h.notify.telegram ? '<span class="badge ok">on</span>' : '<span class="badge">off</span>')}
          <div class="muted small mt-s">Set <span class="mono">NTFY_TOPIC</span> or <span class="mono">TELEGRAM_BOT_TOKEN</span> + <span class="mono">TELEGRAM_CHAT_ID</span> before starting the backend.</div></div></div>
      <div class="card"><div class="card-h">${icon("book")}<h3>Service manuals</h3></div>
        <div class="card-pad stack">${h.manuals.map((m) => `<div class="row"><span style="color:var(--accent)">${icon("file", "sm")}</span><span style="flex:1">${esc(m.doc.replace(/_/g, " ").replace(".pdf", ""))}</span><span class="badge">${m.english_pages_indexed} pages</span></div>`).join("")}
          <label class="btn sm">${icon("upload", "sm")}Add manual (PDF)<input type="file" accept="application/pdf" hidden id="man"></label></div></div>
    </div>
    <div class="card mt"><div class="card-h">${icon("scan")}<h3>Try the manual search</h3><span class="muted small">the same BM25 retrieval the Manual Librarian agent uses</span></div>
      <div class="card-pad stack"><div class="row"><input class="input" id="q" value="bearing overheating misalignment belt tension"><button class="btn primary" id="go">Search</button></div><div id="hits" class="stack"></div></div></div>
    <div class="card mt"><div class="card-h">${icon("truck")}<h3>Repair-centre directory</h3><span class="sp"></span><span class="badge warn">Sample data: replace with real vendors</span></div>
      <div style="overflow-x:auto"><table class="table"><thead><tr><th>Centre</th><th>Area</th><th>Specialties</th><th>Rating</th><th>Response</th><th>Phone</th></tr></thead><tbody>
      ${sc.centres.map((c) => `<tr><td><b>${esc(c.name)}</b></td><td class="muted">${esc(c.area)}</td><td>${c.specialties.map((s) => `<span class="badge" style="margin:2px">${esc(s)}</span>`).join("")}</td>
        <td>${icon("star", "sm")} ${c.rating}</td><td>~${c.avg_response_hours} h</td><td class="mono small">${esc(c.phone)}</td></tr>`).join("")}</tbody></table></div></div>`;
  const search = async () => {
    const hits = await api.get("/api/manuals/search", { q: $("#q", root).value, k: 3 });
    $("#hits", root).innerHTML = hits.map((x) => `<div class="ref"><div class="row wrap"><b>${esc(x.doc.replace(/_/g, " "))}</b><span class="badge">p. ${x.page}</span><span class="badge info">score ${x.score}</span></div>
      <div class="muted small mt-s">${esc(x.excerpt.slice(0, 500))}…</div></div>`).join("") || '<span class="muted">No matches</span>';
  };
  $("#go", root).onclick = search;
  $("#man", root).onchange = async (e) => {
    const f = e.target.files[0]; if (!f) return;
    const fd = new FormData(); fd.append("file", f);
    toast("Indexing manual…", "info"); await api.form("/api/manuals", fd); toast("Manual indexed", "ok");
    window.dispatchEvent(new HashChangeEvent("hashchange"));
  };
  search();
}
