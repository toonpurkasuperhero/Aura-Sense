import { api, fetchBlob } from "../api.js";
import { $, esc, fix, gauge, icon, MACHINE_ICON, statusBadge, toast } from "../ui.js";

const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();

const orderLines = {
  id: "orderLines",
  afterDatasetsDraw(chart, _a, opts) {
    const { ctx, chartArea, scales } = chart;
    if (!opts.f1) return;
    ctx.save();
    ctx.setLineDash([4, 4]); ctx.strokeStyle = css("--muted"); ctx.fillStyle = css("--muted"); ctx.font = "600 11px system-ui";
    for (let k = 1; k <= 6; k++) {
      const x = scales.x.getPixelForValue(k * opts.f1);
      if (x < chartArea.left || x > chartArea.right) continue;
      ctx.beginPath(); ctx.moveTo(x, chartArea.top); ctx.lineTo(x, chartArea.bottom); ctx.stroke();
      ctx.fillText(`${k}×`, x + 3, chartArea.top + 11);
    }
    ctx.restore();
  },
};

function baseOpts(yTitle) {
  const grid = css("--border"), tick = css("--muted");
  return {
    responsive: true, maintainAspectRatio: false, animation: false, interaction: { mode: "index", intersect: false },
    plugins: { legend: { labels: { color: css("--text-2"), boxWidth: 10, boxHeight: 10, usePointStyle: true } },
      tooltip: { backgroundColor: css("--surface-3"), borderColor: css("--border-strong"), borderWidth: 1, titleColor: css("--text"), bodyColor: css("--text-2") } },
    scales: {
      x: { ticks: { color: tick, maxTicksLimit: 6 }, grid: { color: grid } },
      y: { ticks: { color: tick }, grid: { color: grid }, title: { display: !!yTitle, text: yTitle, color: tick } },
    },
    elements: { point: { radius: 0 }, line: { borderWidth: 2, tension: .3 } },
  };
}

export async function render(root, params, ctx) {
  const ms = await api.get("/api/machines");
  if (!ms.length) { root.innerHTML = `<div class="empty">${icon("activity")}<div>No machines yet</div></div>`; return; }
  const alerting = ms.find((m) => m.open_case);
  const nid = params[0] || (alerting || ms[0]).profile.node_id;
  let minutes = 5;
  ctx.title("Live machine", "Edge telemetry streamed from the ESP32 sensor box every 2 s");

  root.innerHTML = `
    <div class="row wrap mb" id="picker">${ms.map((m) => `<a class="btn ${m.profile.node_id === nid ? "primary" : ""}" href="#/machine/${m.profile.node_id}">
      ${icon(MACHINE_ICON[m.profile.machine_type] || "cpu", "sm")}${esc(m.profile.name)}</a>`).join("")}
      <div class="sp"></div>
      <div class="seg" id="win">${[2, 5, 15, 60].map((m) => `<button data-m="${m}" class="${m === minutes ? "on" : ""}">${m} min</button>`).join("")}</div>
    </div>
    <div class="grid" style="grid-template-columns: 220px 1fr; align-items: stretch">
      <div class="card card-pad" style="display:grid;place-items:center;gap:8px" id="gauge"></div>
      <div class="grid g4" id="stats"></div>
    </div>
    <div class="grid g2 mt">
      <div class="card"><div class="card-h">${icon("activity")}<h3>Vibration RMS</h3><span class="muted small">x / y radial · z axial</span></div><div class="chart-box tall"><canvas id="c-vib"></canvas></div></div>
      <div class="card"><div class="card-h">${icon("wave")}<h3>FFT spectrum (edge-computed)</h3><span class="muted small">peaks vs running-speed orders</span></div><div class="chart-box tall"><canvas id="c-fft"></canvas></div></div>
      <div class="card"><div class="card-h">${icon("thermo")}<h3>Temperature</h3><span class="muted small">DHT22 · 0.1 °C resolution</span></div><div class="chart-box"><canvas id="c-temp"></canvas></div></div>
      <div class="card"><div class="card-h">${icon("droplet")}<h3>Humidity & sound level</h3><span class="muted small">DHT22 %RH · microphone module</span></div><div class="chart-box"><canvas id="c-cur"></canvas></div></div>
    </div>
    <div class="split mt">
      <div class="card"><div class="card-h">${icon("sparkles")}<h3>Edge analytics</h3><span class="muted small">order analysis · persistence vote over the last 5 windows</span></div>
        <div class="card-pad hint-list" id="hints"></div></div>
      <div class="card" id="baseline"></div>
    </div>`;

  root.querySelectorAll("#win button").forEach((b) => { b.onclick = () => { minutes = +b.dataset.m; root.querySelectorAll("#win button").forEach((x) => x.classList.toggle("on", x === b)); tick(); }; });

  const C = window.Chart;
  const ok = css("--ok"), bad = css("--bad"), info = css("--info"), acc = css("--accent"), vio = css("--violet");
  const vib = new C($("#c-vib", root), { type: "line", data: { labels: [], datasets: [
    { label: "x", data: [], borderColor: info }, { label: "y", data: [], borderColor: ok }, { label: "z (axial)", data: [], borderColor: acc },
    { label: "ALERT", data: [], borderColor: bad, backgroundColor: bad, showLine: false, pointRadius: 4 }] }, options: baseOpts("g") });
  const fftOpts = baseOpts("g");
  fftOpts.scales.x = { type: "linear", min: 0, ticks: { color: css("--muted") }, grid: { color: css("--border") }, title: { display: true, text: "Hz", color: css("--muted") } };
  fftOpts.plugins.legend = { display: false };
  fftOpts.plugins.orderLines = { f1: null };
  const fft = new C($("#c-fft", root), { type: "bar", data: { datasets: [{ data: [], backgroundColor: acc, borderRadius: 4, barThickness: 8 }] }, options: fftOpts, plugins: [orderLines] });
  const temp = new C($("#c-temp", root), { type: "line", data: { labels: [], datasets: [
    { label: "°C", data: [], borderColor: bad, fill: true, backgroundColor: "rgba(239,68,68,.08)" },
    { label: "baseline", data: [], borderColor: css("--muted"), borderDash: [5, 5], borderWidth: 1.5 }] }, options: baseOpts("°C") });
  const curOpts = baseOpts("%RH");
  curOpts.scales.y2 = { position: "right", ticks: { color: css("--muted") }, grid: { display: false }, title: { display: true, text: "sound", color: css("--muted") } };
  const cur = new C($("#c-cur", root), { type: "line", data: { labels: [], datasets: [
    { label: "humidity %RH", data: [], borderColor: vio }, { label: "sound level", data: [], borderColor: "#14b8a6", borderDash: [4, 3], yAxisID: "y2" }] }, options: curOpts });

  async function tick() {
    const [info_, ser] = await Promise.all([api.get(`/api/machines/${nid}`), api.get(`/api/machines/${nid}/series`, { minutes })]);
    const l = info_.latest || {}, v = l.vib || {}, p = info_.profile, rul = info_.rul || {};
    ctx.extra(statusBadge(l.status || "OFFLINE"));
    $("#gauge", root).innerHTML = gauge(info_.health, 150) + `<div class="muted small">${esc(p.name)}</div>`;
    const dT = l.temp_baseline_c != null ? l.temp_c - l.temp_baseline_c : null;
    $("#stats", root).innerHTML = [
      stat("Remaining life", rul.status === "degrading" ? `${rul.hours_to_threshold} h` : (rul.status || "–").replace("_", " "), rul.slope_per_hour != null ? `trend ${rul.slope_per_hour} pts/h` : "linear trend to health 40", "hourglass"),
      stat("Vibration", `${fix(Math.hypot(v.rms_g?.x || 0, v.rms_g?.y || 0, v.rms_g?.z || 0), 3)} g`, v.baseline_rms ? `${fix(Math.hypot(v.rms_g.x, v.rms_g.y, v.rms_g.z) / v.baseline_rms, 1)}× baseline · z ${fix(v.zscore, 1)}` : "learning baseline", "activity"),
      stat("Temperature", `${fix(l.temp_c, 1)} °C`, dT != null ? `${dT >= 0 ? "+" : ""}${dT.toFixed(1)} °C vs baseline` : "–", "thermo"),
      l.flame ? stat("Flame sensor", "FLAME!", `IR level ${fix(l.flame_level, 0)}/100`, "alert")
        : stat("Humidity", l.humidity_pct != null ? `${fix(l.humidity_pct, 0)} %RH` : "–", `${l.moisture_pct != null ? `moisture ${fix(l.moisture_pct, 0)}% · ` : ""}flame clear · IR ${fix(l.flame_level, 0)}/100${l.sound_event ? " · sound tripped" : ""}`, "droplet"),
    ].join("");
    const labels = ser.map((r) => new Date(r.ts).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }));
    vib.data.labels = labels;
    vib.data.datasets[0].data = ser.map((r) => r.vib.rms_g.x);
    vib.data.datasets[1].data = ser.map((r) => r.vib.rms_g.y);
    vib.data.datasets[2].data = ser.map((r) => r.vib.rms_g.z);
    vib.data.datasets[3].data = ser.map((r) => r.status === "ALERT" ? Math.max(...Object.values(r.vib.rms_g)) : null);
    vib.update("none");
    const f1 = (l.rpm_hint || p.rated_rpm || 0) / 60;
    fft.options.plugins.orderLines.f1 = f1 || null;
    fft.options.scales.x.max = Math.max(f1 * 6.5, ...(v.fft_peaks || []).map((q) => q.hz * 1.1), 60);
    fft.data.datasets[0].data = (v.fft_peaks || []).map((q) => ({ x: q.hz, y: q.amp }));
    fft.update("none");
    temp.data.labels = labels;
    temp.data.datasets[0].data = ser.map((r) => r.temp_c);
    temp.data.datasets[1].data = ser.map((r) => r.temp_baseline_c);
    temp.update("none");
    cur.data.labels = labels;
    cur.data.datasets[0].data = ser.map((r) => r.humidity_pct ?? null);
    cur.data.datasets[1].data = ser.map((r) => r.sound_level);
    cur.update("none");
    $("#hints", root).innerHTML = (info_.hints || []).map((h) => {
      const tagged = h.replace(/(IMBALANCE|MISALIGNMENT|LOOSENESS|BEARING|ELECTRICAL|CAVITATION)/g, "<b>$1</b>");
      return `<div class="hint">${icon("chevron", "sm")}<span>${tagged.replace(/\[(seen in .*?)\]/, '<span class="badge info" style="margin-left:6px">$1</span>')}</span></div>`;
    }).join("") || `<div class="muted">Waiting for telemetry…</div>`;
  }

  async function renderBaseline() {
    const p = (await api.get(`/api/machines/${nid}`)).profile;
    const demo = await api.get("/api/demo-assets");
    $("#baseline", root).innerHTML = `
      <div class="card-h">${icon("image")}<h3>Healthy baseline</h3><span class="muted small">compared against every new inspection</span></div>
      <div class="card-pad stack">
        <div class="grid g2">
          ${p.baseline_image ? `<img src="${api.file(p.baseline_image)}" style="width:100%;height:150px;object-fit:cover;border-radius:10px;border:1px solid var(--border)">` : `<div class="empty">${icon("image")}<div>No baseline photo</div></div>`}
          <div class="stack">${p.baseline_audio ? `<div class="audio-chip">${icon("wave", "sm")}<audio controls src="${api.file(p.baseline_audio)}"></audio></div>` : `<div class="muted small">No baseline sound</div>`}
            <button class="btn sm" id="relearn">${icon("refresh", "sm")}Re-learn sensor baseline</button></div>
        </div>
        <div class="grid g2">
          <div class="field"><label>Set photo from demo assets</label><select class="input" id="b-img"><option value="">—</option>${demo.images.map((f) => `<option>${esc(f)}</option>`).join("")}</select></div>
          <div class="field"><label>Set sound from demo assets</label><select class="input" id="b-aud"><option value="">—</option>${demo.sounds.map((f) => `<option>${esc(f)}</option>`).join("")}</select></div>
        </div>
        <div class="row"><label class="btn sm">${icon("upload", "sm")}Upload photo<input type="file" accept="image/*" id="b-up-img" hidden></label>
          <label class="btn sm">${icon("upload", "sm")}Upload sound<input type="file" accept="audio/*" id="b-up-aud" hidden></label><div class="sp"></div>
          <button class="btn sm primary" id="b-save">Save baseline</button></div>
      </div>`;
    $("#relearn", root).onclick = async () => { await api.post(`/api/nodes/${nid}/relearn`); toast("Sensor box will re-learn its baseline over ~30 s", "info"); };
    $("#b-save", root).onclick = async () => {
      const fd = new FormData();
      const ui = $("#b-up-img", root).files[0], ua = $("#b-up-aud", root).files[0];
      const di = $("#b-img", root).value, da = $("#b-aud", root).value;
      if (ui) fd.append("image", ui); else if (di) fd.append("image", await fetchBlob(`/demo_assets/images/${di}`), di);
      if (ua) fd.append("audio", ua); else if (da) fd.append("audio", await fetchBlob(`/demo_assets/audio/${da}`), da);
      if (![...fd.keys()].length) return toast("Pick a photo or sound first", "bad");
      await api.form(`/api/machines/${nid}/baseline`, fd);
      toast("Baseline saved", "ok"); renderBaseline();
    };
  }

  renderBaseline();
  ctx.every(tick, 2000);
  const onTheme = () => window.dispatchEvent(new HashChangeEvent("hashchange"));
  window.addEventListener("themechange", onTheme);
  return () => { [vib, fft, temp, cur].forEach((c) => c.destroy()); window.removeEventListener("themechange", onTheme); };
}

function stat(k, v, sub, ic) {
  return `<div class="card kpi"><div class="label">${icon(ic, "sm")}${k}</div><div class="value" style="font-size:22px">${esc(v)}</div><div class="sub">${esc(sub)}</div></div>`;
}
