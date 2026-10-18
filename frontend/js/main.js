// App shell: hash router, sidebar (nav, open cases, engine status), theme, clock.
import { api } from "./api.js";
import { $, esc, icon, statusBadge, toast } from "./ui.js";
import * as overview from "./pages/overview.js";
import * as machine from "./pages/machine.js";
import * as kase from "./pages/case.js";
import * as ask from "./pages/ask.js";
import * as history from "./pages/history.js";
import * as system from "./pages/system.js";

const ROUTES = [
  { key: "overview", short: "Plant", label: "Plant overview", icon: "grid", page: overview },
  { key: "machine", short: "Live", label: "Live machine", icon: "activity", page: machine },
  { key: "case", short: "Diagnose", label: "Diagnose", icon: "stetho", page: kase },
  { key: "ask", short: "Ask", label: "Ask a photo", icon: "scan", page: ask },
  { key: "history", short: "Orders", label: "Work orders", icon: "list", page: history },
  { key: "system", short: "System", label: "System", icon: "settings", page: system },
];

let timers = [];
let cleanup = null;

const ctx = {
  every(fn, ms) { fn(); timers.push(setInterval(fn, ms)); },
  title(t, crumb = "") { $("#page-title").textContent = t; $("#page-crumb").textContent = crumb; document.title = `${t} · AuraSense`; },
  extra(html) { $("#top-extra").innerHTML = html || ""; },
  go(hash) { location.hash = hash; },
};

function renderNav(active, openCount) {
  $("#nav").innerHTML = ROUTES.map((r) => `<a href="#/${r.key}" class="${r.key === active ? "active" : ""}">
    ${icon(r.icon)}<span class="full">${r.label}</span><span class="short">${r.short}</span>${r.key === "case" && openCount ? `<span class="count">${openCount}</span>` : ""}</a>`).join("");
}

async function route() {
  timers.forEach(clearInterval); timers = [];
  if (cleanup) { try { cleanup(); } catch { /* ignore */ } cleanup = null; }
  const [, key = "overview", ...rest] = (location.hash || "#/overview").split("/");
  const r = ROUTES.find((x) => x.key === key) || ROUTES[0];
  window.__active = r.key;
  renderNav(r.key, window.__openCount || 0);
  ctx.extra("");
  const view = $("#view");
  view.innerHTML = "";
  window.scrollTo(0, 0);
  try {
    cleanup = await r.page.render(view, rest.map(decodeURIComponent), ctx);
  } catch (e) {
    view.innerHTML = `<div class="card card-pad callout bad">${icon("alert")}<div><b>Could not load this page.</b><div class="muted">${esc(e.message)}</div></div></div>`;
  }
}

async function refreshShell() {
  try {
    const [cases, health] = await Promise.all([api.get("/api/cases", { open: true }), api.get("/api/health")]);
    window.__openCount = cases.length;
    renderNav(window.__active, cases.length);
    $("#side-cases").innerHTML = cases.length ? cases.slice(0, 8).map((c) => `
      <div class="row" style="align-items:center;padding-right:4px;gap:2px">
        <a class="side-case" href="#/case/${encodeURIComponent(c.id)}" style="flex:1;min-width:0">
          ${statusBadge(c.status)}<span style="min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(c.node_id)}${c.fault ? " · " + esc(c.fault) : ""}</span>
        </a>
        <button class="btn sm ghost" style="padding:2px 6px;color:var(--bad);font-size:11px;min-width:20px;height:22px;border:none" title="Dismiss this alert" onclick="event.preventDefault();event.stopPropagation();window.__dismissCase('${c.id}')">✕</button>
      </div>`).join("") : `<div class="muted small" style="padding:0 11px">All machines healthy</div>`;
    const g = health.gemma || {};
    $("#engine").innerHTML = `
      <div class="engine-row"><span class="badge ${g.model_present ? "ok" : "bad"}"><span class="dot"></span>${g.model_present ? "Online" : "Offline"}</span><b style="color:var(--text)">Gemma 4</b></div>
      <div class="engine-row">${icon("cpu", "sm")}<span class="mono">${esc(g.model || "–")}</span></div>
      <div class="engine-row">${icon("ear", "sm")}<span>Audio: ${g.audio_native ? "native" : "DSP fallback"}</span></div>
      <div class="engine-row">${icon("shield", "sm")}<span>100% local · Ollama ${esc(g.ollama || "")}</span></div>`;
    $("#live-badge").className = "badge ok live";
    $("#live-badge").innerHTML = `<span class="dot"></span>Live`;
  } catch {
    $("#live-badge").className = "badge bad";
    $("#live-badge").innerHTML = `<span class="dot"></span>Backend offline`;
  }
}

function theme() {
  const cur = document.documentElement.dataset.theme || "dark";
  $("#theme-btn").innerHTML = icon(cur === "dark" ? "sun" : "moon", "sm") + (cur === "dark" ? "Light mode" : "Dark mode");
}
$("#theme-btn").onclick = () => {
  const next = (document.documentElement.dataset.theme || "dark") === "dark" ? "light" : "dark";
  document.documentElement.dataset.theme = next;
  try { localStorage.setItem("aura-theme", next); } catch { /* private mode */ }
  theme();
  window.dispatchEvent(new Event("themechange"));
};

window.__dismissCase = async (id) => {
  if (!confirm(`Dismiss and clear alert for case ${id}?`)) return;
  try {
    await api.del(`/api/cases/${id}`);
    toast("Case deleted and alert dismissed", "ok");
    await refreshShell();
    if (window.location.hash.includes(id)) window.location.hash = "#/overview";
  } catch (e) {
    toast(e.message, "bad");
  }
};

setInterval(() => { $("#clock").textContent = new Date().toLocaleTimeString(); }, 1000);
window.addEventListener("hashchange", route);
window.addEventListener("unhandledrejection", (e) => toast(e.reason?.message || "Something went wrong", "bad"));
theme();
refreshShell();
setInterval(refreshShell, 4000);
route();
