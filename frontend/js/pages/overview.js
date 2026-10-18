import { api } from "../api.js";
import { $, esc, fix, gauge, healthColor, icon, inr, MACHINE_ICON, sparkline, statusBadge, toast } from "../ui.js";

const SCEN = ["normal", "imbalance", "misalignment", "looseness", "bearing", "electrical", "overheat", "cavitation", "belt_slip", "fire", "humid"];

export async function render(root, _p, ctx) {
  ctx.title("Plant overview", "All monitored machines · live from the Tier-1 sensor boxes");
  root.innerHTML = `
    <div class="grid g5 mb" id="kpis">${'<div class="card kpi skeleton" style="height:98px"></div>'.repeat(5)}</div>
    <div class="row mb"><h3 style="font-size:15px">Machines</h3><span class="muted small" id="online"></span><div class="sp"></div>
      <span class="muted small">Click a machine to open it</span></div>
    <div class="machines" id="machines">${'<div class="card skeleton" style="height:250px"></div>'.repeat(3)}</div>
    <div class="card mt" id="sim">
      <div class="card-h">${icon("zap")}<h3>Demo controls</h3><span class="muted small">Inject a fault into a simulated sensor node to trigger the Tier-1 alert</span></div>
      <div id="sim-rows"></div>
    </div>`;

  const series = {};
  async function tick() {
    const [ms, stats] = await Promise.all([api.get("/api/machines"), api.get("/api/stats")]);
    await Promise.all(ms.map(async (m) => {
      series[m.profile.node_id] = await api.get(`/api/machines/${m.profile.node_id}/series`, { minutes: 5 });
    }));
    const online = ms.filter((m) => m.online).length;
    const hs = ms.map((m) => m.health).filter((h) => h != null);
    const avg = hs.length ? hs.reduce((a, b) => a + b, 0) / hs.length : null;
    const alerts = ms.filter((m) => m.open_case).length;
    $("#kpis", root).innerHTML = [
      kpi("Machines online", `${online}<span class="muted" style="font-size:16px"> / ${ms.length}</span>`, "Sensor boxes reporting", "activity", "var(--info)"),
      kpi("Active alerts", alerts, alerts ? "Needs inspection" : "All clear", "alert", alerts ? "var(--bad)" : "var(--ok)"),
      kpi("Average health", avg == null ? "–" : Math.round(avg), "0–100 across the plant", "shield", healthColor(avg)),
      kpi("Downtime avoided", `${stats.downtime_avoided_hours} h`, `${stats.resolved} cases resolved`, "clock", "var(--violet)"),
      kpi("Estimated savings", inr(stats.estimated_savings_inr), stats.ai_accuracy != null ? `AI accuracy ${Math.round(stats.ai_accuracy * 100)}%` : "From resolved cases", "rupee", "var(--accent)"),
    ].join("");
    $("#online", root).textContent = `· ${online} online`;
    $("#machines", root).innerHTML = ms.map((m) => card(m, series[m.profile.node_id] || [])).join("");
    root.querySelectorAll("[data-node]").forEach((el) => {
      el.onclick = (e) => {
        if (e.target.closest("button")) return;
        ctx.go(el.dataset.case ? `#/case/${el.dataset.case}` : `#/machine/${el.dataset.node}`);
      };
    });
    root.querySelectorAll("[data-inspect]").forEach((b) => {
      b.onclick = async () => {
        const c = await api.post("/api/cases", { node_id: b.dataset.inspect });
        ctx.go(`#/case/${c.id}`);
      };
    });
  }

  async function sim() {
    const ms = await api.get("/api/machines");
    const states = await Promise.all(ms.map((m) => api.get(`/api/sim/${m.profile.node_id}`)));
    $("#sim-rows", root).innerHTML = ms.map((m, i) => {
      const s = states[i], id = m.profile.node_id;
      return `<div class="sim-row">
        <div class="row"><div class="mtype">${icon(MACHINE_ICON[m.profile.machine_type] || "cpu")}</div>
          <div><b>${esc(m.profile.name)}</b><div class="muted small">now: <span class="mono">${esc(s.scenario)} ${fix(s.severity, 1)}</span></div></div></div>
        <select class="input" data-scen="${id}">${SCEN.map((x) => `<option ${x === s.scenario ? "selected" : ""}>${x}</option>`).join("")}</select>
        <div class="row"><input type="range" min="0" max="1" step="0.1" value="0.8" data-sev="${id}" style="flex:1"><span class="mono small" data-sevv="${id}">0.8</span></div>
        <div class="row">
          <button class="btn sm primary" data-inject="${id}">${icon("zap", "sm")}Inject</button>
          <button class="btn sm" data-heal="${id}">Heal</button>
          <button class="btn sm ghost" data-relearn="${id}" title="Forget and re-learn the healthy baseline">${icon("refresh", "sm")}</button>
        </div>
      </div>`;
    }).join("");
    root.querySelectorAll("[data-sev]").forEach((r) => { r.oninput = () => { root.querySelector(`[data-sevv="${r.dataset.sev}"]`).textContent = r.value; }; });
    root.querySelectorAll("[data-inject]").forEach((b) => {
      b.onclick = async () => {
        const id = b.dataset.inject;
        const scenario = root.querySelector(`[data-scen="${id}"]`).value, severity = +root.querySelector(`[data-sev="${id}"]`).value;
        await api.put(`/api/sim/${id}`, { scenario, severity, ramp_seconds: 8 });
        toast(`${scenario} injected on ${id}: alert expected within ~15 s`, "ok"); sim();
      };
    });
    root.querySelectorAll("[data-heal]").forEach((b) => { b.onclick = async () => { await api.put(`/api/sim/${b.dataset.heal}`, { scenario: "normal", severity: 0 }); toast("Machine healed", "ok"); sim(); }; });
    root.querySelectorAll("[data-relearn]").forEach((b) => { b.onclick = async () => { await api.post(`/api/nodes/${b.dataset.relearn}/relearn`); toast("Baseline re-learning queued (~30 s)", "info"); }; });
  }

  sim();
  ctx.every(tick, 2500);
}

function kpi(label, value, sub, ic, glow) {
  return `<div class="card kpi" style="--glow:${glow}">
    <div class="label"><span style="color:${glow}">${icon(ic, "sm")}</span>${label}</div>
    <div class="value">${value}</div><div class="sub">${sub}</div></div>`;
}

function card(m, ser) {
  const p = m.profile, l = m.latest || {}, v = l.vib || {}, rms = v.rms_g || {};
  const status = m.online ? l.status || "OFFLINE" : "OFFLINE";
  const oc = m.open_case;
  const alert = status === "ALERT" || !!oc;
  const maxRms = Math.max(rms.x || 0, rms.y || 0, rms.z || 0);
  const dT = l.temp_baseline_c != null && l.temp_c != null ? l.temp_c - l.temp_baseline_c : null;
  const vals = ser.map((r) => Math.max(...Object.values(r.vib.rms_g)));
  return `<div class="card mcard ${alert ? "alert" : ""}" data-node="${esc(p.node_id)}" ${oc ? `data-case="${esc(oc.id)}"` : ""}>
    <div class="head">
      <div class="mtype">${icon(MACHINE_ICON[p.machine_type] || "cpu", "lg")}</div>
      <div style="min-width:0;flex:1"><h3>${esc(p.name)}</h3><div class="loc">${esc(p.node_id)} · ${esc(p.location)}</div></div>
      ${l.flame ? `<span class="badge bad live"><span class="dot"></span>FLAME</span>` : statusBadge(status)}
    </div>
    <div class="body">
      ${gauge(m.health)}
      <div class="metrics">
        <div class="metric"><div class="k">Vibration</div><div class="v">${fix(maxRms, 3)}<small> g</small></div></div>
        <div class="metric"><div class="k">vs baseline</div><div class="v">${v.baseline_rms ? fix(Math.hypot(rms.x || 0, rms.y || 0, rms.z || 0) / v.baseline_rms, 1) + "<small>×</small>" : "–"}</div></div>
        <div class="metric"><div class="k">Temperature</div><div class="v">${fix(l.temp_c, 1)}<small> °C ${dT != null ? (dT >= 0 ? "+" : "") + dT.toFixed(1) : ""}</small></div></div>
        ${l.humidity_pct != null ? `<div class="metric"><div class="k">Humidity</div><div class="v">${fix(l.humidity_pct, 0)}<small> %RH</small></div></div>`
          : `<div class="metric"><div class="k">Current</div><div class="v">${fix(l.current_a, 1)}<small> A</small></div></div>`}
      </div>
    </div>
    ${sparkline(vals, alert ? "var(--bad)" : healthColor(m.health))}
    ${l.reason && status !== "OK" ? `<div class="reason">${icon("alert", "sm")} ${esc(l.reason)}</div>` : ""}
    ${oc ? `<button class="btn primary block" onclick="location.hash='#/case/${esc(oc.id)}'">${icon("stetho", "sm")}Open case · ${esc(oc.status.toLowerCase())}${oc.severity ? " · " + esc(oc.severity) : ""}</button>`
         : `<button class="btn block" data-inspect="${esc(p.node_id)}">${icon("scan", "sm")}Start manual inspection</button>`}
  </div>`;
}

