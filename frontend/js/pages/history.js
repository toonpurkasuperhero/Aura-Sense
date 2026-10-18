import { api } from "../api.js";
import { $, ago, esc, icon, inr, pct, sevBadge, statusBadge } from "../ui.js";

export async function render(root, _p, ctx) {
  ctx.title("Work orders & history", "Every alert, diagnosis and technician feedback");
  ctx.extra(`<a class="btn sm" href="/api/export/cases.csv">${icon("download", "sm")}Export CSV for CMMS</a>`);
  let filter = "all";
  root.innerHTML = `<div class="grid g5 mb" id="kpis"></div>
    <div class="card"><div class="card-h">${icon("list")}<h3>Cases</h3><div class="sp"></div>
      <div class="seg" id="f">${["all", "open", "resolved"].map((x) => `<button data-f="${x}" class="${x === filter ? "on" : ""}">${x[0].toUpperCase() + x.slice(1)}</button>`).join("")}</div></div>
      <div style="overflow-x:auto"><table class="table"><thead><tr><th>Case</th><th>Machine</th><th>Status</th><th>Diagnosis</th><th>Severity</th><th>Confidence</th><th>Priority</th><th>AI correct?</th><th>Opened</th></tr></thead><tbody id="rows"></tbody></table></div></div>`;
  wireFilter();
  function wireFilter() { root.querySelectorAll("#f button").forEach((b) => { b.onclick = () => { filter = b.dataset.f; root.querySelectorAll("#f button").forEach((x) => x.classList.toggle("on", x === b)); tick(); }; }); }

  async function tick() {
    const [s, cs] = await Promise.all([api.get("/api/stats"), api.get("/api/cases")]);
    const k = (l, v, ic) => `<div class="card kpi"><div class="label">${icon(ic, "sm")}${l}</div><div class="value">${v}</div></div>`;
    $("#kpis", root).innerHTML = k("Cases", s.cases_total, "list") + k("Resolved", s.resolved, "check") +
      k("AI accuracy", s.ai_accuracy == null ? "–" : pct(s.ai_accuracy), "brain") + k("Downtime avoided", `${s.downtime_avoided_hours} h`, "clock") +
      k("Est. savings", inr(s.estimated_savings_inr), "rupee");
    const rows = cs.filter((c) => filter === "all" || (filter === "open" ? c.status !== "RESOLVED" : c.status === "RESOLVED"));
    $("#rows", root).innerHTML = rows.map((c) => `<tr class="click" onclick="location.hash='#/case/${esc(c.id)}'">
      <td class="mono small">${esc(c.id)}</td><td>${esc(c.node_id)}</td><td>${statusBadge(c.status)}</td>
      <td><b>${esc(c.fault || "–")}</b><div class="muted small">${esc(c.reason || "")}</div></td><td>${sevBadge(c.severity)}</td>
      <td class="num">${pct(c.confidence)}</td><td>${esc(c.priority || "–")}</td>
      <td>${c.feedback ? (c.feedback.correct ? '<span class="badge ok">Yes</span>' : '<span class="badge bad">No</span>') : '<span class="muted">–</span>'}</td>
      <td class="muted small">${ago(c.opened_at)}</td></tr>`).join("") || `<tr><td colspan="9" class="empty">No cases</td></tr>`;
  }
  ctx.every(tick, 5000);
}
