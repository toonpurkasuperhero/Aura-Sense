"""AuraSense backend (FastAPI).

Run:  uvicorn backend.main:app --host 0.0.0.0 --port 8000
The ESP32 posts to /api/telemetry; the dashboard uses everything else.
"""
from __future__ import annotations

import csv
import io
import json
import logging
import threading
import uuid
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import gemma, imaging, knowledge, notify, reports
from . import telemetry_analysis as ta
from .agents import orchestrator
from .config import AVG_BREAKDOWN_HOURS, DOWNTIME_COST_PER_HOUR_INR, MANUALS_DIR, ROOT, UPLOAD_DIR

DEMO_DIR = ROOT / "demo_assets"
FRONTEND_DIR = ROOT / "frontend"
from .models import Case, Evidence, Feedback, MachineProfile, RegionAnswer, Telemetry, TraceEvent, utcnow
from .store import store

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("aurasense")

app = FastAPI(title="AuraSense IoT", version="1.0",
              description="Two-tier edge-to-multimodal machine diagnosis powered by Gemma 4")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.on_event("startup")
def _startup():
    threading.Thread(target=knowledge.manuals.build, daemon=True).start()
    threading.Thread(target=gemma.warmup, daemon=True).start()


# ------------------------------------------------------------------ helpers
def _save_upload(case_or_node: str, f: UploadFile, kind: str) -> str:
    ext = Path(f.filename or "").suffix.lower() or (".jpg" if kind == "image" else ".wav")
    rel = f"{case_or_node}/{kind}-{uuid.uuid4().hex[:8]}{ext}"
    dest = UPLOAD_DIR / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(f.file.read())
    return rel


def _case_or_404(cid: str) -> Case:
    c = store.get_case(cid)
    if not c:
        raise HTTPException(404, "case not found")
    return c


# ------------------------------------------------------------------ system
@app.get("/api/health")
def health():
    return {"ok": True, "gemma": gemma.status(), "manuals": knowledge.manuals.docs(),
            "notify": notify.channels(), "time": utcnow().isoformat()}


# ------------------------------------------------------------------ telemetry (Tier 1)
_low_health_streak: dict[str, int] = {}


@app.post("/api/telemetry")
def ingest(t: Telemetry):
    rec = store.add_telemetry(t)
    hs = ta.health_score(rec)
    # The edge decides ALERT; the backend also escalates if health stays very low (dumb/old firmware).
    _low_health_streak[t.node_id] = _low_health_streak.get(t.node_id, 0) + 1 if hs < 40 else 0
    alert = t.status == "ALERT" or _low_health_streak[t.node_id] >= 3
    case_id = None
    if alert and not t.buffered:
        existing = store.open_case_for(t.node_id)
        if existing:
            case_id = existing.id
        else:
            m = store.get_machine(t.node_id)
            reason = t.reason or f"Health score {hs}/100"
            c = store.new_case(t.node_id, rec, reason)
            case_id = c.id
            store.append_trace(c.id, TraceEvent(agent="sentinel", kind="info",
                                                content=f"Tier-1 sentinel raised ALERT on {m.name}: {reason}"))
            sent = notify.push(f"AuraSense ALERT: {m.name}", f"{reason}. Health {hs}/100. Please inspect.",
                               priority="high", tags="rotating_light")
            if sent:
                store.update_case(c.id, notifications=sent)
            log.info("ALERT opened case %s for %s: %s", c.id, t.node_id, reason)
    return {"ok": True, "health": hs, "case_id": case_id}


# ------------------------------------------------------------------ machines
@app.get("/api/machines")
def machines():
    out = []
    for m in store.list_machines():
        latest = store.latest(m.node_id)
        oc = store.open_case_for(m.node_id)
        out.append({"profile": m.model_dump(), "latest": latest, "health": ta.health_score(latest) if latest else None,
                    "open_case": {"id": oc.id, "status": oc.status, "severity": (oc.diagnosis or {}).get("severity")} if oc else None,
                    "online": bool(latest) and (utcnow().timestamp() - _ts(latest)) < 15})
    return out


def _ts(rec) -> float:
    from datetime import datetime
    return datetime.fromisoformat(rec["ts"]).timestamp()


@app.get("/api/machines/{node_id}")
def machine(node_id: str):
    m = store.get_machine(node_id)
    latest = store.latest(node_id)
    return {"profile": m.model_dump(), "latest": latest, "health": ta.health_score(latest),
            "rul": ta.rul_estimate(store.series(node_id, 15)),
            "hints": (ta.window_hints(store.series(node_id, 1), m) or ta.order_hints(latest or {}, m))
                     + ta.other_hints(latest or {})}


@app.put("/api/machines/{node_id}")
def update_machine(node_id: str, m: MachineProfile):
    if m.node_id != node_id:
        raise HTTPException(400, "node_id mismatch")
    old = store.get_machine(node_id)
    m.baseline_image = m.baseline_image or old.baseline_image
    m.baseline_audio = m.baseline_audio or old.baseline_audio
    store.save_machine(m)
    return m


@app.get("/api/machines/{node_id}/series")
def series(node_id: str, minutes: float = 10):
    return store.series(node_id, minutes)


@app.post("/api/machines/{node_id}/baseline")
def set_baseline(node_id: str, image: Optional[UploadFile] = File(None), audio: Optional[UploadFile] = File(None)):
    m = store.get_machine(node_id)
    if image:
        m.baseline_image = _save_upload(f"baseline_{node_id}", image, "image")
    if audio:
        m.baseline_audio = _save_upload(f"baseline_{node_id}", audio, "audio")
    store.save_machine(m)
    return m


# ------------------------------------------------------------------ cases
@app.get("/api/cases")
def cases(open: bool = False, node_id: Optional[str] = None):
    return [_case_summary(c) for c in store.list_cases(node_id=node_id, open_only=open)]


def _case_summary(c: Case) -> dict:
    d = c.diagnosis or {}
    return {"id": c.id, "node_id": c.node_id, "status": c.status, "opened_at": c.opened_at,
            "updated_at": c.updated_at, "reason": c.trigger_reason, "fault": d.get("fault"),
            "severity": d.get("severity"), "confidence": d.get("confidence"),
            "priority": (c.work_order or {}).get("priority"), "feedback": c.feedback}


class NewCase(BaseModel):
    node_id: str
    reason: str = "Manual inspection requested by technician"


@app.post("/api/cases")
def create_case(body: NewCase):
    c = store.new_case(body.node_id, store.latest(body.node_id), body.reason, status="INVESTIGATING")
    return c


@app.get("/api/cases/{cid}")
def get_case(cid: str):
    c = _case_or_404(cid)
    out = json.loads(c.model_dump_json())
    out["running"] = orchestrator.is_running(cid)
    return out


@app.post("/api/cases/{cid}/evidence")
def add_evidence(cid: str,
                 images: list[UploadFile] = File(default=[]),
                 audio: Optional[UploadFile] = File(None),
                 voice_note: Optional[UploadFile] = File(None),
                 roi: str = Form(""), roi_question: str = Form(""),
                 notes: str = Form(""), language: str = Form("English"),
                 replace: bool = Form(True)):
    c = _case_or_404(cid)
    ev = Evidence() if replace else c.evidence
    for f in images:
        if f and f.filename:
            ev.images.append(_save_upload(cid, f, "image"))
    if audio and audio.filename:
        ev.audio = _save_upload(cid, audio, "audio")
    if voice_note and voice_note.filename:
        ev.voice_note = _save_upload(cid, voice_note, "voice")
    if roi:
        vals = [float(v) for v in roi.split(",")]
        if len(vals) != 4:
            raise HTTPException(400, "roi must be x0,y0,x1,y1 fractions")
        ev.roi = vals
    ev.roi_question, ev.notes, ev.language = roi_question, notes, language
    store.update_case(cid, evidence=ev, status="INVESTIGATING" if c.status in ("ALERT", "ERROR") else c.status)
    return ev


@app.post("/api/cases/{cid}/diagnose", status_code=202)
def diagnose(cid: str):
    _case_or_404(cid)
    started = orchestrator.start(cid)
    return {"started": started, "running": True}


class Approve(BaseModel):
    approved_by: str = "Supervisor"
    notify_vendor: bool = False


@app.post("/api/cases/{cid}/approve")
def approve(cid: str, body: Approve):
    c = _case_or_404(cid)
    if not c.diagnosis:
        raise HTTPException(400, "nothing to approve")
    wo = c.work_order or {}
    m = store.get_machine(c.node_id)
    sent = notify.push(f"Work order approved: {m.name}", f"{wo.get('title')} ({wo.get('priority')}). "
                                                         f"Approved by {body.approved_by}.", tags="white_check_mark")
    store.update_case(cid, status="APPROVED", approved_by=body.approved_by, notifications=c.notifications + sent)
    store.append_trace(cid, TraceEvent(agent="human", kind="info", content=f"Approved by {body.approved_by}."))
    return {"ok": True, "whatsapp_link": wo.get("whatsapp_link"), "sms_link": wo.get("sms_link")}


@app.post("/api/cases/{cid}/resolve")
def resolve(cid: str, fb: Feedback):
    c = _case_or_404(cid)
    if not fb.downtime_avoided_hours:
        fb.downtime_avoided_hours = AVG_BREAKDOWN_HOURS if c.diagnosis else 0
    store.update_case(cid, status="RESOLVED", feedback=fb)
    store.append_trace(cid, TraceEvent(agent="human", kind="info",
                                       content=("Technician confirmed the diagnosis." if fb.correct else
                                                f"Technician corrected the diagnosis: actual cause '{fb.actual_cause}'. "
                                                "This lesson will be used in future cases.")))
    return {"ok": True}


@app.delete("/api/cases/{cid}")
def delete_case(cid: str):
    _case_or_404(cid)
    store.delete_case(cid)
    log.info("Deleted case %s", cid)
    return {"ok": True}


@app.post("/api/cases/{cid}/dismiss")
def dismiss_case(cid: str):
    _case_or_404(cid)
    store.update_case(cid, status="RESOLVED", feedback=Feedback(correct=False, actual_cause="False alert dismissed by user", downtime_avoided_hours=0))
    store.append_trace(cid, TraceEvent(agent="human", kind="info", content="Case dismissed as false alarm by technician."))
    log.info("Dismissed case %s", cid)
    return {"ok": True}


@app.get("/api/cases/{cid}/ticket.pdf")
def ticket(cid: str):
    c = _case_or_404(cid)
    if not c.diagnosis:
        raise HTTPException(400, "no diagnosis yet")
    sc = knowledge.centre((c.work_order or {}).get("service_centre_id", ""))
    pdf = reports.build_ticket(c, store.get_machine(c.node_id), sc)
    return Response(pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="AuraSense_{cid}.pdf"'})


# ------------------------------------------------------------------ ask about a region (ROI) / free question
@app.post("/api/vision/ask")
def vision_ask(image: UploadFile = File(...), question: str = Form(...), roi: str = Form(""),
               node_id: str = Form("")):
    data = image.file.read()
    att = []
    if roi:
        r = [float(v) for v in roi.split(",")]
        att.append(gemma.Attachment("image", imaging.draw_roi(data, r), "full photo, region of interest outlined in red"))
        att.append(gemma.Attachment("image", imaging.crop_roi(data, r), "zoomed crop of the red region"))
    else:
        att.append(gemma.Attachment("image", imaging.prepare(data), "photo"))
    ctx = ""
    if node_id:
        m = store.get_machine(node_id)
        latest = store.latest(node_id)
        ctx = f"Machine context: {ta.summarize([], latest, m)}\n\n"
    res = gemma.chat("You are an expert industrial maintenance inspector. Look carefully at the region of interest. "
                     "Describe only what is visible; if the image is unclear, say so.",
                     f"{ctx}Question: {question}", att, schema=RegionAnswer, max_tokens=700)
    out = res.parsed.model_dump()
    out["duration_s"] = res.duration_s
    return out


# ------------------------------------------------------------------ knowledge
@app.get("/api/manuals")
def list_manuals():
    return knowledge.manuals.docs()


@app.post("/api/manuals")
def upload_manual(file: UploadFile = File(...)):
    if not (file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(400, "PDF only")
    (MANUALS_DIR / Path(file.filename).name).write_bytes(file.file.read())
    knowledge.manuals.build()
    return knowledge.manuals.docs()


@app.get("/api/manuals/search")
def manual_search(q: str, k: int = 5):
    return knowledge.manuals.search(q, k)


@app.get("/api/service-centres")
def service_centres():
    return {"site": knowledge.site(), "centres": knowledge.all_centres()}


# ------------------------------------------------------------------ stats / export
@app.get("/api/stats")
def stats():
    cs = store.list_cases(limit=1000)
    resolved = [c for c in cs if c.status == "RESOLVED"]
    confirmed = [c for c in resolved if c.feedback and c.feedback.correct]
    hours = sum((c.feedback.downtime_avoided_hours if c.feedback else 0) for c in resolved)
    saved = 0.0
    for c in resolved:
        m = store.get_machine(c.node_id)
        rate = m.downtime_cost_per_hour_inr or DOWNTIME_COST_PER_HOUR_INR
        saved += (c.feedback.downtime_avoided_hours if c.feedback else 0) * rate
    return {"cases_total": len(cs), "open": len([c for c in cs if c.status != "RESOLVED"]),
            "resolved": len(resolved), "ai_confirmed": len(confirmed),
            "ai_accuracy": round(len(confirmed) / len(resolved), 2) if resolved else None,
            "downtime_avoided_hours": round(hours, 1), "estimated_savings_inr": round(saved)}


@app.get("/api/export/cases.csv")
def export_csv():
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["case_id", "node_id", "status", "opened_at", "reason", "fault", "component", "severity", "confidence",
                "priority", "est_downtime_h", "est_cost_inr", "service_centre", "feedback_correct", "actual_cause"])
    for c in store.list_cases(limit=5000):
        d, wo = c.diagnosis or {}, c.work_order or {}
        w.writerow([c.id, c.node_id, c.status, c.opened_at.isoformat(), c.trigger_reason, d.get("fault"),
                    d.get("component"), d.get("severity"), d.get("confidence"), wo.get("priority"),
                    wo.get("est_downtime_hours"), wo.get("est_total_cost_inr"), wo.get("service_centre_id"),
                    c.feedback.correct if c.feedback else "", c.feedback.actual_cause if c.feedback else ""])
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": 'attachment; filename="aurasense_cases.csv"'})


# ------------------------------------------------------------------ files
@app.get("/api/files/{rel:path}")
def files(rel: str):
    p = (UPLOAD_DIR / rel).resolve()
    if not str(p).startswith(str(UPLOAD_DIR.resolve())) or not p.exists():
        raise HTTPException(404)
    return FileResponse(p)


# ------------------------------------------------------------------ node commands (polled by ESP32 / simulator)
_commands: dict[str, dict] = {}


@app.post("/api/nodes/{node_id}/relearn")
def relearn(node_id: str):
    """Ask the sensor box to forget its baseline and learn a new one (e.g. after a repair)."""
    _commands[node_id] = {"relearn": True}
    return {"queued": True}


@app.get("/api/nodes/{node_id}/command")
def node_command(node_id: str):
    return _commands.pop(node_id, {})


# ------------------------------------------------------------------ demo assets (open-licence photos & sounds)
@app.get("/api/demo-assets")
def demo_assets():
    def ls(sub, exts):
        d = DEMO_DIR / sub
        return sorted(p.name for p in d.iterdir() if p.suffix.lower() in exts) if d.exists() else []
    return {"images": ls("images", {".jpg", ".jpeg", ".png"}),
            "sounds": [f for f in ls("audio", {".wav", ".mp3"}) if "voice" not in f],
            "voice_notes": [f for f in ls("audio", {".wav", ".mp3"}) if "voice" in f]}


# ------------------------------------------------------------------ simulator control
class SimCtl(BaseModel):
    scenario: str = "normal"
    severity: float = 0.0
    ramp_seconds: float = 0.0


@app.get("/api/sim/{node_id}")
def sim_get(node_id: str):
    return store.get_sim(node_id)


@app.put("/api/sim/{node_id}")
def sim_set(node_id: str, body: SimCtl):
    d = body.model_dump()
    d["since"] = utcnow().isoformat()
    store.set_sim(node_id, d)
    return d


# ------------------------------------------------------------------ web UI (plain HTML/CSS/JS, same origin)
app.mount("/demo_assets", StaticFiles(directory=DEMO_DIR), name="demo_assets")
app.mount("/ui", StaticFiles(directory=FRONTEND_DIR, html=True), name="ui")


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse("/ui/")
