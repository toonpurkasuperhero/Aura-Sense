import { api, fetchBlob } from "../api.js";
import { canRecord, WavRecorder } from "../recorder.js";
import { mountRoi } from "../roi.js";
import { $, $$, AGENTS, ago, esc, gauge, icon, inr, lightbox, MACHINE_ICON, PIPELINE, sevBadge, statusBadge, toast } from "../ui.js";

const LANGS = ["English", "Hindi", "Kannada", "Tamil", "Telugu", "Marathi"];
const STANCE = { supports: ["ok", "Supports"], contradicts: ["bad", "Contradicts"], neutral: ["", "Neutral"], not_provided: ["", "Not provided"] };
const MOD_ICON = { telemetry: "activity", image: "image", audio: "wave", voice_note: "mic", baseline: "layers", manual: "book", history: "history" };

export async function render(root, params, ctx) {
  let cid = params[0];
  if (!cid) {
    const open = await api.get("/api/cases", { open: true });
    const all = open.length ? open : await api.get("/api/cases");
    if (!all.length) {
      ctx.title("Diagnose", "No cases yet");
      root.innerHTML = `<div class="card empty">${icon("stetho")}<h3>No cases yet</h3><p>Inject a fault on the Plant overview or start a manual inspection.</p>
        <a class="btn primary" href="#/overview">Go to Plant overview</a></div>`;
      return;
    }
    cid = all[0].id;
    history.replaceState(null, "", `#/case/${cid}`);
  }

  let c = await api.get(`/api/cases/${cid}`);
  const m = (await api.get(`/api/machines/${c.node_id}`)).profile;
  const demo = await api.get("/api/demo-assets");
  ctx.title(m.name, `Case ${cid} · ${m.location}`);

  const ev = { images: [], audio: null, voice: null, roi: null, roiQ: "What is happening inside this region? Any defect?", notes: "", lang: c.evidence?.language || "English" };
  let tab = c.diagnosis ? "diag" : (c.running || c.status === "DIAGNOSING") ? "room" : "evidence";
  let lastStatus = c.status, recorder = null, roiCtl = null, fullTrace = false;

  root.innerHTML = `
    <div class="card case-hero" id="hero"></div>
    <div class="card card-pad mt" id="pipeline-card"><div class="row mb" style="margin-bottom:10px">${icon("brain")}<b>Agent pipeline</b><span class="muted small">All agents run on Gemma 4 E4B locally</span></div><div class="pipeline" id="pipeline"></div></div>
    <div class="tabs mt" id="tabs"></div>
    <div id="tab-evidence"></div><div id="tab-room"></div><div id="tab-diag"></div><div id="tab-action"></div><div id="tab-report"></div>`;

  // ------------------------------------------------------------------ header + pipeline + tabs
  function hero() {
    const d = c.diagnosis;
    $("#hero", root).innerHTML = `
      <div class="mtype" style="width:52px;height:52px">${icon(MACHINE_ICON[m.machine_type] || "cpu", "lg")}</div>
      <div style="flex:1;min-width:240px">
        <div class="row wrap"><h2>${esc(m.name)}</h2>${statusBadge(c.status)}${d ? sevBadge(d.severity) : ""}</div>
        <div class="meta"><span>${icon("clock", "sm")} opened ${ago(c.opened_at)}</span><span class="mono">${esc(c.id)}</span><span>${esc(m.power_kw)} kW · ${esc(m.rated_rpm)} rpm</span></div>
      </div>
      <div class="trigger" style="display:flex;align-items:center;gap:12px;background:rgba(239,68,68,0.12);border:1px solid rgba(239,68,68,0.3);padding:8px 14px;border-radius:10px">
        ${icon("zap")}
        <div style="flex:1">
          <div class="small muted" style="color:var(--bad)">Tier-1 trigger alert</div>
          <b>${esc(c.trigger_reason || "Manual inspection")}</b>
        </div>
        <button class="btn sm" id="btn-delete-case" title="Dismiss / Clear this alert flyer" style="background:rgba(239,68,68,0.2);border:1px solid rgba(239,68,68,0.5);color:#f87171;font-weight:600;padding:5px 12px;cursor:pointer;white-space:nowrap">
          ${icon("x", "sm")} Dismiss Alert
        </button>
      </div>`;
    const delBtn = $("#btn-delete-case", root);
    if (delBtn) {
      delBtn.onclick = async () => {
        if (!confirm(`Dismiss and clear alert for case ${c.id}?`)) return;
        try {
          await api.del(`/api/cases/${cid}`);
          toast("Alert cleared and case removed", "ok");
          window.location.hash = "#/overview";
        } catch (e) {
          toast(e.message, "bad");
        }
      };
    }
  }
  function pipeline() {
    const seen = new Set(c.trace.map((e) => e.agent));
    const last = [...c.trace].reverse().find((e) => PIPELINE.includes(e.agent));
    $("#pipeline", root).innerHTML = PIPELINE.map((a) => {
      const st = c.running && last?.agent === a ? "active" : seen.has(a) ? "done" : "";
      return `<span class="pipe ${st}"><span class="d"></span>${AGENTS[a].name}</span>`;
    }).join(`<span class="muted">${icon("chevron", "sm")}</span>`);
  }
  function tabs() {
    const T = [["evidence", "Evidence", true], ["room", "Agent room", c.trace.length > 0], ["diag", "Diagnosis", !!c.diagnosis],
      ["action", "Action", !!c.work_order], ["report", "Report", !!c.report]];
    $("#tabs", root).innerHTML = T.map(([k, label, done], i) => `<button data-t="${k}" class="${k === tab ? "on" : ""} ${done && k !== "evidence" ? "done" : ""}"><span class="n">${i + 1}</span>${label}</button>`).join("");
    $$("#tabs button", root).forEach((b) => { b.onclick = () => { tab = b.dataset.t; show(); }; });
  }
  function show() {
    ["evidence", "room", "diag", "action", "report"].forEach((k) => $(`#tab-${k}`, root).classList.toggle("hidden", k !== tab));
    $$("#tabs button", root).forEach((b) => b.classList.toggle("on", b.dataset.t === tab));
  }

  // ------------------------------------------------------------------ evidence
  function evidence() {
    const checks = ["Stand clear of rotating parts; never remove guards while running.",
      "Photo of the whole machine: motor, driven equipment and base.",
      "Close-up of bearing housings, coupling/belt and mounting bolts.",
      "Record 10 s of sound about 30 cm from the bearing housing.",
      "Without touching: note any smell (burning, hot oil) or leaks.",
      ...((c.signal_report || {}).inspection_requests || [])];
    $("#tab-evidence", root).innerHTML = `
      <div class="split">
        <div class="card card-pad stack">
          <div class="row" style="background:linear-gradient(135deg, rgba(99,102,241,0.12), rgba(168,85,247,0.08));border:1px solid rgba(99,102,241,0.3);border-radius:10px;padding:12px 14px;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px">
            <div>
              <div style="font-weight:700;display:flex;align-items:center;gap:6px;font-size:14px">
                ${icon("zap", "sm")}<b>Telemetry Diagnosis Available:</b>
              </div>
              <div class="small muted" style="margin-top:2px">
                Live ESP32 telemetry (vibration FFT, temp, humidity, sound) is ingested. You can diagnose immediately with Gemma 4, or attach inspection photos & audio.
              </div>
            </div>
            <div class="row" style="gap:8px">
              <button class="btn primary sm" id="btn-quick-diagnose" type="button" style="white-space:nowrap">${icon("brain", "sm")} Run AI Diagnosis Now</button>
              <button class="btn sm" id="btn-prefill-demo" type="button" style="white-space:nowrap">${icon("layers", "sm")} Auto-Fill Evidence</button>
            </div>
          </div>
          <div class="media-block">
            <div class="media-title"><span class="step">${icon("camera", "sm")}</span>Photos of the machine<span class="sp"></span><span class="muted small" id="img-count"></span></div>
            <label class="drop" id="drop">
              <div class="ic">${icon("upload")}</div>
              <div><b>Drop photos here, browse, or use the phone camera</b><span>JPG / PNG · several angles help</span></div>
              <input type="file" accept="image/*" capture="environment" multiple hidden id="img-in">
            </label>
            <div class="row"><select class="input" id="demo-img"><option value="">Add a demo photo…</option>${demo.images.map((f) => `<option>${esc(f)}</option>`).join("")}</select></div>
            <div class="thumbs" id="thumbs"></div>
            <div id="roi-zone" class="hidden stack">
              <div class="row"><span class="label-sm">${icon("crosshair", "sm")} Drag on the photo to mark a region of interest</span><div class="sp"></div><button class="btn sm ghost" id="roi-clear">Clear</button></div>
              <div id="roi"></div>
              <input class="input" id="roi-q" value="${esc(ev.roiQ)}">
            </div>
          </div>
          <div class="divider"></div>
          ${audioBlock("audio", "Machine sound", "wave", "5–10 s, phone ~30 cm from the machine", demo.sounds)}
          <div class="divider"></div>
          ${audioBlock("voice", "Technician voice note", "mic", "Describe the problem in any language", demo.voice_notes)}
          <div class="divider"></div>
          <div class="grid g2">
            <div class="field"><label>Notes (optional)</label><textarea class="input" id="notes" placeholder="Anything else the agents should know">${esc(ev.notes)}</textarea></div>
            <div class="field"><label>Operator message language</label><select class="input" id="lang">${LANGS.map((l) => `<option ${l === ev.lang ? "selected" : ""}>${l}</option>`).join("")}</select>
              <span class="muted small">The Reporter agent writes the operator message in this language.</span></div>
          </div>
          <button class="btn primary lg block" id="run">${icon("brain")}Run AI diagnosis with Gemma 4</button>
          <div class="muted small" style="text-align:center">Photo, sound and voice note are fused in one multimodal reasoning step, then audited by the agent team.</div>
        </div>
        <div class="stack">
          <div class="card"><div class="card-h">${icon("activity")}<h3>Sensor Ingestion Pipeline</h3></div>
            <div class="card-pad stack small">
              <div class="row" style="align-items:flex-start;gap:8px"><span class="badge ok">1</span><div><b>Edge Sensors & DSP:</b> ESP32 samples MPU6050 vibration (1024-pt FFT), DHT11 & IR flame, and POSTs JSON every 2s.</div></div>
              <div class="row" style="align-items:flex-start;gap:8px"><span class="badge info">2</span><div><b>Multimodal Evidence:</b> Visual defect photos & machine acoustics are fused with telemetry or inferred from edge signals.</div></div>
              <div class="row" style="align-items:flex-start;gap:8px"><span class="badge accent">3</span><div><b>Gemma 4 Multi-Agent:</b> 6 specialized agents reason across physics, vibration harmonics, safety manuals & logistics.</div></div>
            </div>
          </div>
          <div class="card"><div class="card-h">${icon("list")}<h3>Guided inspection</h3></div>
            <div class="card-pad checklist">${checks.map((t, i) => `<label class="check"><input type="checkbox" data-ck="${i}"><span>${esc(t)}</span></label>`).join("")}</div></div>
          ${c.evidence && (c.evidence.images.length || c.evidence.audio) ? `<div class="card"><div class="card-h">${icon("layers")}<h3>Evidence on file</h3></div><div class="card-pad stack">
            <div class="thumbs">${c.evidence.images.map((p) => `<div class="thumb"><img src="${api.file(p)}" data-zoom="${api.file(p)}"></div>`).join("")}</div>
            ${c.evidence.audio ? `<div class="audio-chip">${icon("wave", "sm")}<audio controls src="${api.file(c.evidence.audio)}"></audio></div>` : ""}
            ${c.evidence.voice_note ? `<div class="audio-chip">${icon("mic", "sm")}<audio controls src="${api.file(c.evidence.voice_note)}"></audio></div>` : ""}
          </div></div>` : ""}
        </div>
      </div>`;
    const t = $("#tab-evidence", root);
    $$("[data-ck]", t).forEach((x) => { x.onchange = () => x.closest(".check").classList.toggle("done", x.checked); });
    $$("[data-zoom]", t).forEach((x) => { x.onclick = () => lightbox(x.dataset.zoom); });
    const drop = $("#drop", t);
    $("#img-in", t).onchange = (e) => addImages([...e.target.files]);
    drop.ondragover = (e) => { e.preventDefault(); drop.classList.add("over"); };
    drop.ondragleave = () => drop.classList.remove("over");
    drop.ondrop = (e) => { e.preventDefault(); drop.classList.remove("over"); addImages([...e.dataTransfer.files].filter((f) => f.type.startsWith("image/"))); };
    $("#demo-img", t).onchange = async (e) => {
      const f = e.target.value; if (!f) return;
      addImages([new File([await fetchBlob(`/demo_assets/images/${f}`)], f, { type: "image/jpeg" })]); e.target.value = "";
    };
    const qdBtn = $("#btn-quick-diagnose", t);
    if (qdBtn) qdBtn.onclick = run;
    const preBtn = $("#btn-prefill-demo", t);
    if (preBtn) {
      preBtn.onclick = async () => {
        preBtn.disabled = true;
        preBtn.textContent = "Loading sample evidence...";
        try {
          const imgName = m.machine_type === "pump" ? "pump_housing_corroded.jpg" : "bearing_damage.jpg";
          const sndName = demo.sounds.find((s) => s.includes("abnormal")) || demo.sounds[0] || "";
          const vName = demo.voice_notes.find((v) => v.includes("hi")) || demo.voice_notes[0] || "";
          if (imgName) {
            const b = await fetchBlob(`/demo_assets/images/${imgName}`);
            ev.images = [{ name: imgName, blob: b, url: URL.createObjectURL(b) }];
            ev.roi = [0.25, 0.25, 0.75, 0.75];
            thumbs();
          }
          if (sndName) {
            setAudio("audio", sndName, await fetchBlob(`/demo_assets/audio/${sndName}`));
          }
          if (vName) {
            setAudio("voice", vName, await fetchBlob(`/demo_assets/audio/${vName}`));
          }
          toast("Sample evidence auto-filled! Click 'Run AI diagnosis' below.", "ok");
        } catch (err) {
          toast(err.message, "bad");
        } finally {
          preBtn.disabled = false;
          preBtn.innerHTML = icon("layers", "sm") + " Auto-Fill Evidence";
        }
      };
    }
    $("#roi-clear", t).onclick = () => roiCtl && roiCtl.clear();
    $("#roi-q", t).oninput = (e) => { ev.roiQ = e.target.value; };
    $("#notes", t).oninput = (e) => { ev.notes = e.target.value; };
    $("#lang", t).onchange = (e) => { ev.lang = e.target.value; };
    wireAudio("audio", 12); wireAudio("voice", 30);
    $("#run", t).onclick = run;
    thumbs();
  }

  function addImages(files) {
    for (const f of files) ev.images.push({ name: f.name, blob: f, url: URL.createObjectURL(f) });
    thumbs();
  }
  function thumbs() {
    const t = $("#tab-evidence", root);
    $("#img-count", t).textContent = ev.images.length ? `${ev.images.length} added` : "";
    $("#thumbs", t).innerHTML = ev.images.map((im, i) => `<div class="thumb"><img src="${im.url}">${i === 0 ? '<span class="tag">ROI photo</span>' : ""}<button data-rm="${i}" title="Remove">${icon("x", "sm")}</button></div>`).join("");
    $$("[data-rm]", t).forEach((b) => { b.onclick = (e) => { e.preventDefault(); ev.images.splice(+b.dataset.rm, 1); ev.roi = null; thumbs(); }; });
    const zone = $("#roi-zone", t);
    zone.classList.toggle("hidden", !ev.images.length);
    if (ev.images.length) roiCtl = mountRoi($("#roi", t), ev.images[0].url, (r) => { ev.roi = r; });
  }

  function audioBlock(kind, title, ic, sub, list) {
    return `<div class="media-block" id="ab-${kind}">
      <div class="media-title"><span class="step">${icon(ic, "sm")}</span>${title}<span class="muted small" style="font-weight:400">· ${sub}</span></div>
      <div class="row wrap">
        ${canRecord() ? `<button class="btn" data-rec="${kind}">${icon("mic", "sm")}Record</button>` : ""}
        <label class="btn">${icon("upload", "sm")}Upload<input type="file" accept="audio/*" capture hidden data-up="${kind}"></label>
        <select class="input" style="max-width:260px" data-demo="${kind}"><option value="">Demo ${kind === "voice" ? "voice note" : "sound"}…</option>${list.map((f) => `<option>${esc(f)}</option>`).join("")}</select>
        <span class="rec hidden" data-recui="${kind}"><span class="rec-dot"></span><span class="mono" data-rect="${kind}">0.0 s</span><span class="meter"><i data-lvl="${kind}"></i></span></span>
      </div>
      <div data-prev="${kind}"></div>
    </div>`;
  }
  function setAudio(kind, name, blob) {
    ev[kind] = blob ? { name, blob, url: URL.createObjectURL(blob) } : null;
    const box = root.querySelector(`[data-prev="${kind}"]`);
    box.innerHTML = ev[kind] ? `<div class="audio-chip">${icon(kind === "voice" ? "mic" : "wave", "sm")}<span class="small mono" style="max-width:160px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(name)}</span>
      <audio controls src="${ev[kind].url}"></audio><button class="btn sm ghost icon-btn" data-clear="${kind}">${icon("x", "sm")}</button></div>` : "";
    const cl = box.querySelector("[data-clear]");
    if (cl) cl.onclick = () => setAudio(kind, null, null);
  }
  function wireAudio(kind, maxS) {
    const up = root.querySelector(`[data-up="${kind}"]`), dm = root.querySelector(`[data-demo="${kind}"]`), rb = root.querySelector(`[data-rec="${kind}"]`);
    up.onchange = (e) => { const f = e.target.files[0]; if (f) setAudio(kind, f.name, f); };
    dm.onchange = async (e) => { const f = e.target.value; if (f) setAudio(kind, f, await fetchBlob(`/demo_assets/audio/${f}`)); };
    if (!rb) return;
    let timer = null;
    const ui = root.querySelector(`[data-recui="${kind}"]`), tt = root.querySelector(`[data-rect="${kind}"]`), lvl = root.querySelector(`[data-lvl="${kind}"]`);
    const stop = async () => {
      clearInterval(timer);
      const blob = await recorder.stop(); recorder = null;
      ui.classList.add("hidden"); rb.innerHTML = icon("mic", "sm") + "Record"; rb.classList.remove("primary");
      setAudio(kind, `${kind === "voice" ? "voice-note" : "machine-sound"}.wav`, blob);
    };
    rb.onclick = async () => {
      if (recorder) return stop();
      try {
        recorder = new WavRecorder((v) => { lvl.style.width = `${v * 100}%`; });
        await recorder.start();
      } catch (e) { recorder = null; return toast("Microphone not available: " + e.message, "bad"); }
      ui.classList.remove("hidden"); rb.innerHTML = icon("stop", "sm") + "Stop"; rb.classList.add("primary");
      timer = setInterval(() => { const s = recorder.elapsed(); tt.textContent = s.toFixed(1) + " s"; if (s >= maxS) stop(); }, 100);
    };
  }

  async function run() {
    const btn = $("#run", root);
    btn.disabled = true; btn.innerHTML = icon("hourglass") + "Uploading evidence…";
    try {
      const fd = new FormData();
      ev.images.forEach((im) => fd.append("images", im.blob, im.name));
      if (ev.audio) fd.append("audio", ev.audio.blob, ev.audio.name);
      if (ev.voice) fd.append("voice_note", ev.voice.blob, ev.voice.name);
      fd.append("roi", ev.roi ? ev.roi.join(",") : "");
      fd.append("roi_question", ev.roi ? ev.roiQ : "");
      fd.append("notes", ev.notes); fd.append("language", ev.lang);
      fd.append("replace", ev.images.length || ev.audio || ev.voice ? "true" : "false");
      await api.form(`/api/cases/${cid}/evidence`, fd);
      await api.post(`/api/cases/${cid}/diagnose`);
      toast("Agent team started", "ok");
      tab = "room"; c.running = true; c.trace = []; show(); poll();
    } catch (e) { toast(e.message, "bad"); }
    btn.disabled = false; btn.innerHTML = icon("brain") + "Run AI diagnosis with Gemma 4";
  }

  // ------------------------------------------------------------------ agent room
  function room() {
    const items = c.trace.filter((e) => fullTrace || !["info", "start"].includes(e.kind)).map((e) => {
      const a = AGENTS[e.agent] || { name: e.agent, icon: "cpu", color: "#64748b" };
      const kindLabel = { start: "started", output: "result", tool: "tool", info: "Gemma call", critique: "critique", revision: "revision", done: "done", error: "error" }[e.kind] || e.kind;
      return `<div class="msg ${e.kind}">
        <div class="avatar" style="background:${a.color}">${icon(a.icon)}</div>
        <div class="bubble"><div class="who"><b>${esc(a.name)}</b><span class="badge ${e.kind === "critique" ? "bad" : e.kind === "revision" ? "warn" : e.kind === "output" ? "accent" : e.kind === "done" ? "ok" : ""}">${kindLabel}</span>
          ${e.duration_s ? `<span class="muted small">${icon("clock", "sm")} ${e.duration_s} s</span>` : ""}<span class="sp"></span><span class="muted small">${new Date(e.ts).toLocaleTimeString()}</span></div>
          <div class="txt">${esc(e.content)}</div></div></div>`;
    }).join("");
    const typing = c.running ? `<div class="msg"><div class="avatar" style="background:var(--surface-3)">${icon("brain")}</div><div class="bubble"><div class="who"><b>Gemma 4 is thinking</b></div><div class="typing"><i></i><i></i><i></i></div></div></div>` : "";
    const calls = c.trace.filter((e) => e.kind === "info" && e.content.startsWith("Gemma 4 call"));
    const secs = calls.reduce((a, e) => a + (e.duration_s || 0), 0);
    const bar = `<div class="row wrap mb"><div class="seg" id="tr-mode"><button data-v="0" class="${fullTrace ? "" : "on"}">Conversation</button><button data-v="1" class="${fullTrace ? "on" : ""}">Full trace</button></div>
      <div class="sp"></div><span class="badge accent">${icon("brain", "sm")} ${calls.length} Gemma 4 calls · ${secs.toFixed(0)} s</span></div>`;
    $("#tab-room", root).innerHTML = items || typing ? `${bar}<div class="card card-pad"><div class="room">${items}${typing}</div></div>`
      : `<div class="card empty">${icon("brain")}<h3>No agent activity yet</h3><p>Add evidence and run the diagnosis.</p></div>`;
    $$("#tr-mode button", root).forEach((b) => { b.onclick = () => { fullTrace = b.dataset.v === "1"; room(); }; });
  }

  // ------------------------------------------------------------------ diagnosis
  function diag() {
    const d = c.diagnosis, el = $("#tab-diag", root);
    if (!d) { el.innerHTML = `<div class="card empty">${icon("stetho")}<h3>No diagnosis yet</h3></div>`; return; }
    const au = c.audit || {}, ac = c.acoustic || {}, rul = c.rul || {};
    const steps = [...(au.added_safety_steps || []).map((s) => ({ s, safety: true })), ...d.repair_steps.map((s) => ({ s }))];
    const hits = Object.fromEntries((c.manual_hits || []).map((h) => [`${h.doc}|${h.page}`, h]));
    const gal = [...c.evidence.images.map((p, i) => [api.file(p), i ? `Current photo ${i + 1}` : "Current photo"]),
      ...(m.baseline_image ? [[api.file(m.baseline_image), "Healthy baseline"]] : []),
      ...(ac.spectrogram ? [[api.file(ac.spectrogram), "Sound: baseline (top) vs current"]] : [])];
    el.innerHTML = `
      <div class="sev-hero sev-${d.severity}">
        <div><div class="lvl">${esc(d.severity)} severity · ${esc(d.fault_category)}</div><h2>${esc(d.fault)}</h2><div class="comp">${icon("pin", "sm")} ${esc(d.component)}</div></div>
        <div class="row" style="gap:18px">${gauge(d.confidence * 100, 104, "confidence")}${gauge(c.health_score, 104, "health")}</div>
      </div>
      <div class="card mt"><div class="stat-strip">
        <div><div class="k">Time to failure</div><div class="v">${esc(d.time_to_failure.replace("_", " "))}</div></div>
        <div><div class="k">Trend</div><div class="v">${esc((rul.status || "–").replace("_", " "))}</div><div class="muted small">${rul.slope_per_hour != null ? rul.slope_per_hour + " pts/h" : ""}</div></div>
        <div><div class="k">Safety audit</div><div class="v" style="font-size:16px">${esc(au.verdict || "–").replaceAll("_", " ")}</div></div>
        <div><div class="k">Evidence fused</div><div class="v">${(d.modality_votes || []).filter((v) => v.stance !== "not_provided").length}<span class="muted" style="font-size:14px"> sources</span></div></div>
      </div></div>
      <div class="callout warn mt">${icon("alert")}<div><b>Immediate action</b><div>${esc(d.immediate_action)}</div><div class="muted small mt-s">AI suggestion generated locally by Gemma 4. Verify on site before acting.</div></div></div>

      <h3 class="mt mb" style="font-size:15px">Cross-modal evidence</h3>
      <div class="modal-grid">${(d.modality_votes || []).map((v) => {
        const [cls, lab] = STANCE[v.stance] || ["", v.stance];
        return `<div class="mod ${v.stance}"><div class="t">${icon(MOD_ICON[v.modality] || "info", "sm")}${esc(v.modality.replace("_", " "))}<span class="sp"></span><span class="badge ${cls}">${lab}</span></div><p>${esc(v.note)}</p></div>`;
      }).join("")}</div>
      <div class="card card-pad mt"><div class="row mb" style="margin-bottom:8px">${icon("brain")}<b>How the evidence was combined</b></div><div style="color:var(--text-2)">${esc(d.cross_modal_reasoning)}</div>
        ${d.roi_findings ? `<div class="callout info mt">${icon("crosshair")}<div><b>Marked region</b><div>${esc(d.roi_findings)}</div></div></div>` : ""}</div>

      <div class="split mt">
        <div class="card"><div class="card-h">${icon("image")}<h3>What the agents looked at and listened to</h3></div><div class="card-pad stack">
          <div class="gallery">${gal.map(([src, cap]) => `<figure><img src="${src}" data-zoom="${src}"><figcaption>${esc(cap)}</figcaption></figure>`).join("")}</div>
          ${c.evidence.audio ? `<div class="audio-chip">${icon("wave", "sm")}<span class="small">Machine sound</span><audio controls src="${api.file(c.evidence.audio)}"></audio></div>` : ""}
          ${ac.comparison ? `<div class="grid g3">
            <div class="mod"><div class="t">${icon("layers", "sm")}Similarity</div><b style="font-size:20px">${ac.comparison.spectral_similarity}</b><span class="muted small">to healthy sound</span></div>
            <div class="mod"><div class="t">${icon("sparkles", "sm")}Novelty</div><b style="font-size:20px">${ac.comparison.novelty_score}</b><span class="muted small">${esc(ac.comparison.verdict)}</span></div>
            <div class="mod"><div class="t">${icon("wave", "sm")}Loudness</div><b style="font-size:20px">${ac.comparison.loudness_change_db > 0 ? "+" : ""}${ac.comparison.loudness_change_db} dB</b><span class="muted small">vs baseline</span></div></div>` : ""}
        </div></div>
        <div class="card"><div class="card-h">${icon("layers")}<h3>Differential diagnosis</h3></div><div class="card-pad stack">
          ${(d.differential || []).map((x) => `<div class="diff"><b>${esc(x.fault)}</b><span class="muted">${esc(x.why_less_likely)}</span></div>`).join("") || '<span class="muted">None given</span>'}
          ${c.first_diagnosis && c.first_diagnosis.fault !== d.fault ? `<div class="callout info">${icon("refresh")}<div><b>Revised after the Safety Auditor's critique</b><div class="muted">First draft: ${esc(c.first_diagnosis.severity)} · ${esc(c.first_diagnosis.fault)}</div></div></div>` : ""}
        </div></div>
      </div>

      <div class="split mt">
        <div class="card"><div class="card-h">${icon("wrench")}<h3>Repair checklist</h3><span class="sp"></span><span class="muted small">safety steps first</span></div>
          <div class="card-pad checklist">${steps.map((x, i) => `<label class="check ${x.safety ? "safety" : ""}"><input type="checkbox"><span class="no">${i + 1}</span><span>${x.safety ? icon("shield", "sm") + " " : ""}${esc(x.s)}</span></label>`).join("")}</div>
          ${(d.parts_needed || []).length ? `<div class="card-pad" style="padding-top:0"><span class="label-sm">Parts</span><div class="row wrap mt-s">${d.parts_needed.map((p) => `<span class="badge">${p.qty} × ${esc(p.part)}</span>`).join("")}</div></div>` : ""}
        </div>
        <div class="card"><div class="card-h">${icon("book")}<h3>Service-manual references</h3></div><div class="card-pad stack">
          ${(d.manual_refs || []).map((r) => { const h = hits[`${r.doc}|${r.page}`];
            return `<div class="ref"><div class="row wrap"><b>${esc(r.doc.replace(/_/g, " ").replace(".pdf", ""))}</b><span class="badge">p. ${r.page}</span>
              <span class="badge ${r.verified ? "ok" : "warn"}">${r.verified ? "quote verified" : "page verified"}</span></div>
              <div class="muted small">${esc(r.section || "")}</div>${r.quote ? `<q>${esc(r.quote)}</q>` : ""}
              ${h ? `<details><summary>Show retrieved page excerpt</summary><p>${esc(h.excerpt)}</p></details>` : ""}</div>`; }).join("") || '<span class="muted">No manual page cited.</span>'}
        </div></div>
      </div>`;
    $$("[data-zoom]", el).forEach((x) => { x.onclick = () => lightbox(x.dataset.zoom); });
    $$(".check input", el).forEach((x) => { x.onchange = () => x.closest(".check").classList.toggle("done", x.checked); });
  }

  // ------------------------------------------------------------------ action
  function action() {
    const wo = c.work_order, au = c.audit || {}, el = $("#tab-action", root);
    if (!wo) { el.innerHTML = `<div class="card empty">${icon("truck")}<h3>No work order yet</h3></div>`; return; }
    const sc = (wo.candidates || []).find((x) => x.id === wo.service_centre_id);
    const approved = ["APPROVED", "RESOLVED"].includes(c.status);
    el.innerHTML = `
      <div class="split">
        <div class="card"><div class="card-h">${icon("wrench")}<h3>Work order</h3><span class="sp"></span><span class="badge ${wo.priority.startsWith("P1") ? "bad" : wo.priority.startsWith("P2") ? "high" : "warn"}">${esc(wo.priority)}</span></div>
          <div class="card-pad stack">
            <h3 style="font-size:17px">${esc(wo.title)}</h3>
            <div class="grid g3">
              <div class="mod"><span class="muted small">Est. downtime</span><b style="font-size:20px">${wo.est_downtime_hours} h</b></div>
              <div class="mod"><span class="muted small">Est. cost</span><b style="font-size:20px">${inr(wo.est_total_cost_inr)}</b></div>
              <div class="mod"><span class="muted small">Breakdown cost avoided (~8 h)</span><b style="font-size:20px">${inr((wo.downtime_cost_per_hour_inr || 0) * 8)}</b></div>
            </div>
            <div class="row wrap">${wo.skills_needed.map((s) => `<span class="badge info">${esc(s)}</span>`).join("")}</div>
            <div class="checklist">${wo.tasks.map((t, i) => `<div class="check"><span class="no">${i + 1}</span><span>${esc(t)}</span></div>`).join("")}</div>
            ${wo.parts.length ? `<table class="table"><thead><tr><th>Part</th><th>Qty</th><th style="text-align:right">Est. cost</th></tr></thead><tbody>
              ${wo.parts.map((p) => `<tr><td>${esc(p.part)}</td><td>${p.qty}</td><td style="text-align:right" class="num">${inr(p.est_cost_inr)}</td></tr>`).join("")}</tbody></table>` : ""}
          </div></div>
        <div class="stack">
          <div class="card"><div class="card-h">${icon("shield")}<h3>Safety audit</h3><span class="sp"></span><span class="badge ${String(au.verdict).startsWith("APPROVE") ? "ok" : "bad"}">${esc(String(au.verdict || "–").replaceAll("_", " "))}</span></div>
            <div class="card-pad stack">
              <div class="row wrap"><span class="badge ${au.loto_required ? "warn" : ""}">LOTO ${au.loto_required ? "required" : "not required"}</span>
                <span class="badge ${au.can_run_until_repair ? "ok" : "bad"}">${au.can_run_until_repair ? "May run until repair" : "Do not run until repaired"}</span></div>
              <div class="row wrap">${(au.ppe || []).map((p) => `<span class="badge">${esc(p)}</span>`).join("")}</div>
              <div class="muted small">${esc(au.hazard_notes || "")}</div>
              ${(au.first_round_issues || []).length ? `<div class="callout bad">${icon("refresh")}<div><b>Round-1 objections (fixed by revision)</b>${au.first_round_issues.map((i) => `<div class="small">• ${esc(i)}</div>`).join("")}</div></div>` : ""}
            </div></div>
          <div class="card"><div class="card-h">${icon("truck")}<h3>Repair centre</h3></div>
            <div class="card-pad stack">
              ${sc ? `<div class="vendor"><div class="logo">${icon("wrench")}</div><div><b>${esc(sc.name)}</b><div class="muted small">${icon("pin", "sm")} ${esc(sc.area)} · ${sc.distance_km} km · ${icon("star", "sm")} ${sc.rating} · ~${sc.avg_response_hours} h response</div></div></div>`
                : `<div class="vendor"><div class="logo">${icon("user")}</div><div><b>In-house repair</b></div></div>`}
              <div class="muted small">${esc(wo.service_centre_reason)}</div>
              <div class="label-sm">Message drafted by the Logistics agent</div>
              <div class="msg-box">${esc(wo.vendor_message)}</div>
            </div></div>
        </div>
      </div>
      <div class="card card-pad mt">
        <div class="row wrap">
          ${c.status === "DIAGNOSED" ? `<input class="input" id="appr-by" value="Supervisor" style="max-width:200px"><button class="btn ok" id="approve">${icon("check", "sm")}Approve & dispatch</button>`
            : `<span class="badge ${approved ? "ok" : ""}">${esc(c.status)}${c.approved_by ? " by " + esc(c.approved_by) : ""}</span>`}
          <div class="sp"></div>
          ${wo.whatsapp_link ? `<a class="btn ${approved ? "primary" : ""}" ${approved ? `href="${esc(wo.whatsapp_link)}" target="_blank" rel="noopener"` : 'aria-disabled="true" style="opacity:.45;pointer-events:none"'}>${icon("chat", "sm")}WhatsApp vendor</a>
            <a class="btn" ${approved ? `href="${esc(wo.sms_link)}"` : 'style="opacity:.45;pointer-events:none"'}>${icon("phone", "sm")}SMS</a>` : ""}
          <a class="btn" href="/api/cases/${esc(cid)}/ticket.pdf" target="_blank">${icon("download", "sm")}Service ticket PDF</a>
        </div>
        ${!approved ? `<div class="muted small mt-s">Human-in-the-loop: nothing is sent to the vendor until a supervisor approves.</div>` : ""}
      </div>
      ${["APPROVED", "DIAGNOSED"].includes(c.status) ? `<div class="card mt"><div class="card-h">${icon("check")}<h3>Close the case</h3><span class="muted small">technician feedback becomes a lesson for future diagnoses</span></div>
        <div class="card-pad grid g4" style="align-items:end">
          <div class="field"><label>Was the AI diagnosis correct?</label><div class="seg" id="fb-ok"><button class="on" data-v="1">Yes</button><button data-v="0">No</button></div></div>
          <div class="field"><label>Actual cause (if different)</label><input class="input" id="fb-cause"></div>
          <div class="field"><label>Breakdown hours avoided</label><input class="input" id="fb-h" type="number" value="8"></div>
          <button class="btn primary" id="resolve">${icon("check", "sm")}Resolve case</button>
        </div></div>` : ""}
      ${c.feedback ? `<div class="callout ${c.feedback.correct ? "ok" : "info"} mt">${icon("check")}<div>${c.feedback.correct ? "Technician confirmed the diagnosis." : "Correction recorded: " + esc(c.feedback.actual_cause) + ". This lesson is used in future cases."}</div></div>` : ""}`;
    const ap = $("#approve", el);
    if (ap) ap.onclick = async () => { await api.post(`/api/cases/${cid}/approve`, { approved_by: $("#appr-by", el).value }); toast("Approved: vendor contact unlocked", "ok"); await refresh(true); };
    $$("#fb-ok button", el).forEach((b) => { b.onclick = () => $$("#fb-ok button", el).forEach((x) => x.classList.toggle("on", x === b)); });
    const rs = $("#resolve", el);
    if (rs) rs.onclick = async () => {
      await api.post(`/api/cases/${cid}/resolve`, { correct: $("#fb-ok .on", el).dataset.v === "1", actual_cause: $("#fb-cause", el).value, downtime_avoided_hours: +$("#fb-h", el).value || 0 });
      await api.post(`/api/nodes/${c.node_id}/relearn`);
      toast("Case resolved. The sensor box re-learns its baseline.", "ok"); await refresh(true);
    };
  }

  // ------------------------------------------------------------------ report
  function report() {
    const r = c.report, el = $("#tab-report", root);
    if (!r) { el.innerHTML = `<div class="card empty">${icon("pen")}<h3>No report yet</h3></div>`; return; }
    el.innerHTML = `
      <div class="label-sm mb" style="margin-bottom:8px">${icon("user", "sm")} Message for the machine operator · ${esc(c.evidence.language)}</div>
      <div class="op-msg">${esc(r.operator_message_local)}</div>
      ${c.evidence.language !== "English" ? `<div class="muted mt-s">${esc(r.operator_message_en)}</div>` : ""}
      <div class="split mt">
        <div class="card"><div class="card-h">${icon("layers")}<h3>5-Why root-cause analysis</h3></div><div class="card-pad">
          ${r.five_whys.map((w, i) => `<div class="why"><div class="n">${i + 1}</div><div><b>${esc(/^why/i.test(w.why) ? w.why : "Why " + w.why)}</b><span>${esc(w.answer)}</span></div></div>`).join("")}
          <div class="root">${icon("check", "sm")} <b>Root cause:</b> ${esc(r.root_cause_statement)}</div></div></div>
        <div class="stack">
          <div class="card"><div class="card-h">${icon("file")}<h3>Shift-log entry</h3></div><div class="card-pad"><div class="log">${esc(r.shift_log_entry)}</div></div></div>
          <div class="card"><div class="card-h">${icon("shield")}<h3>Preventive actions</h3></div><div class="card-pad checklist">${r.preventive_actions.map((p) => `<div class="check">${icon("chevron", "sm")}<span>${esc(p)}</span></div>`).join("")}</div></div>
        </div>
      </div>`;
  }

  // ------------------------------------------------------------------ polling
  async function refresh(full = false) {
    c = await api.get(`/api/cases/${cid}`);
    hero(); pipeline(); tabs(); room();
    const finished = lastStatus !== c.status && ["DIAGNOSED", "ERROR"].includes(c.status);
    if (full || finished || !c.running) { diag(); action(); report(); }
    if (finished && c.status === "DIAGNOSED") { toast("Diagnosis ready", "ok"); tab = "diag"; }
    if (finished && c.status === "ERROR") toast("Pipeline error: " + (c.error || ""), "bad");
    lastStatus = c.status;
    show();
  }
  let polling = null;
  function poll() { if (!polling) polling = setInterval(async () => { await refresh(); if (!c.running && c.status !== "DIAGNOSING") { clearInterval(polling); polling = null; } }, 2000); }

  evidence(); await refresh(true);
  if (c.running || c.status === "DIAGNOSING") poll();
  return () => { if (polling) clearInterval(polling); if (recorder) recorder.stop().catch(() => {}); };
}

