"""Orchestrator: runs the agent team on a shared case file.

  Intake Clerk ─┐
                ├─> Signal Analyst ─> [Acoustic Lab + Manual Librarian tools]
                │       ─> Diagnostician (multimodal) <──┐
                │                 │                      │ REVISE (max 1 loop)
                │                 └─> Safety Auditor ────┘
                │                          │ APPROVE
                └──────────────────────────┴─> Logistics Coordinator ─> Reporter

Every step is streamed into the case trace so the UI's Agent Room shows the
agents talking to each other in real time.
"""
from __future__ import annotations

import threading
import time
import traceback

from .. import audio as au
from .. import imaging, knowledge, notify
from .. import telemetry_analysis as ta
from ..config import UPLOAD_DIR
from ..models import TraceEvent
from ..store import store
from .base import Agent, Context
from .diagnostician import Diagnostician, acoustic_lab
from .intake import IntakeClerk
from .logistics import LogisticsCoordinator
from .reporter import Reporter
from .safety_auditor import SafetyAuditor
from .signal_analyst import SignalAnalyst

_running: set[str] = set()


class _Orch(Agent):
    name = "orchestrator"
    title = "Orchestrator"


class _Librarian(Agent):
    name = "librarian"
    title = "Manual Librarian"


def _read(rel: str | None) -> bytes | None:
    if not rel:
        return None
    p = UPLOAD_DIR / rel
    return p.read_bytes() if p.exists() else None


def history_text(node_id: str, exclude: str) -> str:
    lines = []
    for c in store.list_cases(node_id=node_id, limit=20):
        if c.id == exclude or not c.diagnosis:
            continue
        d = c.diagnosis
        fb = c.feedback
        line = f"- {c.opened_at:%d %b %Y}: diagnosed '{d.get('fault')}' ({d.get('severity')})"
        if fb:
            line += (" - technician CONFIRMED it" if fb.correct else
                     f" - technician said WRONG, actual cause: '{fb.actual_cause}'")
            if fb.notes:
                line += f" ({fb.notes})"
        lines.append(line)
    # Global lessons: any case on any machine where the AI was wrong
    for c in store.list_cases(limit=50):
        if c.node_id != node_id and c.feedback and not c.feedback.correct and c.diagnosis:
            lines.append(f"- LESSON from {c.node_id}: AI said '{c.diagnosis.get('fault')}', "
                         f"actual was '{c.feedback.actual_cause}'.")
    return "\n".join(lines[:12])


def build_context(case_id: str) -> Context:
    case = store.get_case(case_id)
    machine = store.get_machine(case.node_id)

    def emit(ev: TraceEvent):
        store.append_trace(case_id, ev)

    ctx = Context(case=case, machine=machine, latest=store.latest(case.node_id) or case.trigger,
                  series=store.series(case.node_id, minutes=15), emit=emit)
    ev = case.evidence
    raw = [_read(p) for p in ev.images]
    raw = [r for r in raw if r]
    if raw and ev.roi:
        try:
            ctx.roi_crop = imaging.crop_roi(raw[0], ev.roi)
            ctx.roi_overlay = imaging.draw_roi(raw[0], ev.roi)
        except ValueError:
            pass
    ctx.images = [imaging.prepare(r) for r in raw]
    if ctx.roi_overlay:
        ctx.images[0] = ctx.roi_overlay
    b = _read(machine.baseline_image)
    ctx.baseline_image = imaging.prepare(b) if b else None
    a = _read(ev.audio)
    ctx.audio_wav = au.to_wav(au.load(a)) if a else None
    ba = _read(machine.baseline_audio)
    ctx.baseline_audio_wav = au.to_wav(au.load(ba)) if ba else None
    v = _read(ev.voice_note)
    ctx.voice_wav = au.to_wav(au.load(v, max_seconds=30)) if v else None
    ctx.history_text = history_text(case.node_id, case.id)
    return ctx


def run_pipeline(case_id: str):
    t0 = time.time()
    try:
        store.update_case(case_id, status="DIAGNOSING", trace=[], error=None)
        ctx = build_context(case_id)
        orch = _Orch(ctx)
        ev = ctx.case.evidence
        orch.say("start", f"Case {case_id} for {ctx.machine.name}: evidence = {len(ev.images)} photo(s), "
                          f"{'machine sound' if ev.audio else 'no sound'}, "
                          f"{'voice note' if ev.voice_note else 'no voice note'}, "
                          f"{'region marked' if ev.roi else 'no region'}, "
                          f"baseline {'available' if ctx.baseline_image or ctx.baseline_audio_wav else 'missing'}. "
                          "Assembling the agent team.")

        intake = IntakeClerk(ctx).run()
        store.update_case(case_id, intake=intake)

        signal = SignalAnalyst(ctx).run(intake)
        store.update_case(case_id, signal_report=signal)

        diag_agent = Diagnostician(ctx)
        acoustic = acoustic_lab(ctx, diag_agent)
        if ctx.spectrogram_png:
            rel = f"{case_id}/spectrogram.png"
            (UPLOAD_DIR / case_id).mkdir(parents=True, exist_ok=True)
            (UPLOAD_DIR / rel).write_bytes(ctx.spectrogram_png)
            if acoustic is not None:
                acoustic["spectrogram"] = rel
        store.update_case(case_id, acoustic=acoustic)

        lib = _Librarian(ctx)
        query = " ".join([c["fault"] for c in signal["candidates"]] + (intake or {}).get("symptoms", []) +
                         [ctx.machine.machine_type, "troubleshooting maintenance bearing vibration"])
        hits = knowledge.manuals.search(query, k=4, docs=ctx.machine.manuals or None)
        ctx.manual_hits = hits
        lib.say("tool", "Retrieved manual pages: " + "; ".join(f"{h['doc']} p.{h['page']} ({h['section'][:40]})" for h in hits),
                data={"hits": [{k: h[k] for k in ('doc', 'page', 'section', 'score')} for h in hits]})
        store.update_case(case_id, manual_hits=hits)

        diagnosis = diag_agent.run(signal, intake)
        store.update_case(case_id, first_diagnosis=diagnosis, diagnosis=diagnosis)

        auditor = SafetyAuditor(ctx)
        audit = auditor.run(diagnosis, 1)
        if audit["verdict"] == "REVISE":
            diagnosis = diag_agent.revise(diagnosis, audit["issues"], signal, intake)
            store.update_case(case_id, diagnosis=diagnosis)
            audit2 = auditor.run(diagnosis, 2)
            audit2["first_round_issues"] = audit["issues"]
            if audit2["verdict"] == "REVISE":
                if any("post-repair verification" in i for i in audit2["issues"]):
                    diagnosis["repair_steps"].append("Test run: restart the machine, re-measure vibration and "
                                                     "temperature, and compare with the healthy baseline before "
                                                     "handing it back to production.")
                    store.update_case(case_id, diagnosis=diagnosis)
                auditor.say("info", "Second review still has concerns; approving WITH CONDITIONS: mandatory steps "
                                    "added and human sign-off required. Open points: " + " | ".join(audit2["issues"]))
                audit2["verdict"] = "APPROVE_WITH_CONDITIONS"
            audit = audit2
        store.update_case(case_id, audit=audit)

        wo = LogisticsCoordinator(ctx).run(diagnosis, audit)
        sc = knowledge.centre(wo["service_centre_id"])
        if sc:
            wo["whatsapp_link"] = notify.whatsapp_link(sc["whatsapp"], wo["vendor_message"])
            wo["sms_link"] = notify.sms_link(sc["phone"], wo["vendor_message"])
        store.update_case(case_id, work_order=wo)

        report = Reporter(ctx).run(diagnosis, audit, wo)

        latest = store.latest(ctx.case.node_id) or ctx.case.trigger
        hs = ta.health_score(latest)
        rul = ta.rul_estimate(store.series(ctx.case.node_id, minutes=15))
        store.update_case(case_id, report=report, health_score=hs, rul=rul, status="DIAGNOSED")
        sent = notify.push(f"AuraSense: {ctx.machine.name} - {diagnosis['severity']}",
                           f"{diagnosis['fault']} ({diagnosis['component']}). {diagnosis['immediate_action']}",
                           priority="high" if diagnosis["severity"] in ("HIGH", "CRITICAL") else "default")
        if sent:
            c = store.get_case(case_id)
            store.update_case(case_id, notifications=c.notifications + sent)
        orch.say("done", f"Pipeline finished in {time.time() - t0:.0f} s. Waiting for human approval before dispatch.")
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        store.append_trace(case_id, TraceEvent(agent="orchestrator", kind="error", content=f"{type(e).__name__}: {e}"))
        store.update_case(case_id, status="ERROR", error=str(e))
    finally:
        _running.discard(case_id)


def start(case_id: str) -> bool:
    if case_id in _running:
        return False
    _running.add(case_id)
    threading.Thread(target=run_pipeline, args=(case_id,), daemon=True).start()
    return True


def is_running(case_id: str) -> bool:
    return case_id in _running
