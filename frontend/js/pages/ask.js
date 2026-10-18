import { api, fetchBlob } from "../api.js";
import { mountRoi } from "../roi.js";
import { $, esc, icon, sevBadge, toast } from "../ui.js";

export async function render(root, _p, ctx) {
  ctx.title("Ask a photo", "Mark any region of a machine photo and ask Gemma 4 what is going on there");
  const [ms, demo] = await Promise.all([api.get("/api/machines"), api.get("/api/demo-assets")]);
  let blob = null, roi = null, ctl = null;
  root.innerHTML = `
    <div class="split">
      <div class="card card-pad stack">
        <label class="drop" id="drop"><div class="ic">${icon("camera")}</div>
          <div><b>Upload or take a photo</b><span>then drag on it to mark the region you are asking about</span></div>
          <input type="file" accept="image/*" capture="environment" hidden id="in"></label>
        <select class="input" id="demo"><option value="">…or pick a demo photo</option>${demo.images.map((f) => `<option>${esc(f)}</option>`).join("")}</select>
        <div id="roi"></div>
      </div>
      <div class="stack">
        <div class="card card-pad stack">
          <div class="field"><label>Machine context (optional)</label><select class="input" id="node"><option value="">None</option>${ms.map((m) => `<option value="${esc(m.profile.node_id)}">${esc(m.profile.name)}</option>`).join("")}</select></div>
          <div class="field"><label>Your question</label><textarea class="input" id="q">What is happening inside this region? Any defect, wear, leak or damage?</textarea></div>
          <div class="row"><span class="muted small" id="roi-state">${icon("crosshair", "sm")} No region marked: the whole photo is analysed</span><div class="sp"></div>
            <button class="btn primary" id="ask">${icon("sparkles", "sm")}Ask Gemma 4</button></div>
        </div>
        <div id="answer"></div>
      </div>
    </div>`;
  const load = (b) => {
    blob = b;
    ctl = mountRoi($("#roi", root), URL.createObjectURL(b), (r) => {
      roi = r;
      $("#roi-state", root).innerHTML = r ? `${icon("crosshair", "sm")} Region marked` : `${icon("crosshair", "sm")} No region marked: the whole photo is analysed`;
    });
  };
  $("#in", root).onchange = (e) => e.target.files[0] && load(e.target.files[0]);
  $("#demo", root).onchange = async (e) => e.target.value && load(await fetchBlob(`/demo_assets/images/${e.target.value}`));
  $("#ask", root).onclick = async () => {
    if (!blob) return toast("Add a photo first", "bad");
    const btn = $("#ask", root);
    btn.disabled = true; btn.innerHTML = icon("hourglass", "sm") + "Inspecting…";
    $("#answer", root).innerHTML = `<div class="card card-pad"><div class="row">${icon("brain")}<b>Gemma 4 is looking at the region</b><div class="typing"><i></i><i></i><i></i></div></div></div>`;
    try {
      const fd = new FormData();
      fd.append("image", blob, "photo.jpg"); fd.append("question", $("#q", root).value);
      fd.append("roi", roi ? roi.join(",") : ""); fd.append("node_id", $("#node", root).value);
      const r = await api.form("/api/vision/ask", fd);
      $("#answer", root).innerHTML = `<div class="card card-pad answer">
        <div class="row">${icon("sparkles")}<b>Answer</b>${sevBadge(r.severity === "NONE" ? "LOW" : r.severity)}<div class="sp"></div><span class="muted small">${r.duration_s} s · local</span></div>
        <div style="font-size:15px">${esc(r.answer)}</div>
        <div class="muted">${esc(r.region_description)}</div>
        ${r.defects_found.length ? `<div class="row wrap">${r.defects_found.map((d) => `<span class="badge bad">${esc(d)}</span>`).join("")}</div>` : `<span class="badge ok">No defect found</span>`}
        <div class="callout info">${icon("info")}<div><b>Recommended check</b><div>${esc(r.recommended_check)}</div></div></div></div>`;
    } catch (e) { $("#answer", root).innerHTML = ""; toast(e.message, "bad"); }
    btn.disabled = false; btn.innerHTML = icon("sparkles", "sm") + "Ask Gemma 4";
  };
}
