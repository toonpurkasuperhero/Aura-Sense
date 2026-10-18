"""Diagnostician: the multimodal core. One Gemma 4 call that sees the photo(s),
the marked region, the healthy-baseline photo, HEARS the machine audio, sees the
baseline-vs-current spectrogram, and reads telemetry, DSP features, manual
excerpts and history - then reasons across all of them."""
from __future__ import annotations

import os

from .. import audio as au
from .. import gemma
from ..knowledge import FAULT_SIGNATURES
from ..models import Diagnosis, RegionAnswer
from .base import Agent, js, unnumber

SYSTEM = ("You are the senior maintenance engineer of an Indian MSME factory with 25 years of experience on "
          "motors, fans, pumps and gearboxes. You diagnose faults by combining ALL evidence: sensor telemetry, "
          "photos, the machine's sound, the healthy baseline and the service manual. Rules: "
          "(1) For every modality say explicitly what it shows and whether it supports or contradicts your "
          "hypothesis; if modalities conflict, explain how you resolved it. "
          "(2) Describe only what is actually visible/audible - never invent visual defects. "
          "(3) Repair steps must be concrete, ordered and doable by a local technician. "
          "(4) manual_refs may ONLY cite doc names and page numbers that appear in the MANUAL EXCERPTS given to "
          "you, with a short exact quote; if none apply, return an empty list. "
          "(5) Calibrate confidence honestly: lower it when evidence is missing or conflicting.")

THINK = os.getenv("AURA_THINK", "0") == "1"


class Diagnostician(Agent):
    name = "diagnostician"
    title = "Diagnostician"
    system = SYSTEM

    def _attachments(self) -> tuple[list[gemma.Attachment], list[str]]:
        c, att, notes = self.ctx, [], []
        if c.roi_overlay:
            att.append(gemma.Attachment("image", c.roi_overlay, "CURRENT photo of the machine, technician's region of interest outlined in RED"))
        for i, im in enumerate(c.images[1 if c.roi_overlay else 0:], 1):
            att.append(gemma.Attachment("image", im, f"CURRENT photo #{i} of the machine"))
        if c.roi_crop:
            att.append(gemma.Attachment("image", c.roi_crop, "ZOOMED crop of the red region of interest"))
        if c.baseline_image:
            att.append(gemma.Attachment("image", c.baseline_image, "BASELINE photo of the same machine when healthy"))
        if c.audio_wav and gemma.audio_supported():
            att.append(gemma.Attachment("audio", c.audio_wav, "CURRENT 10 s sound recording of the machine running"))
        if c.spectrogram_png:
            att.append(gemma.Attachment("image", c.spectrogram_png,
                                        "SPECTROGRAM image: " + ("top = healthy baseline sound, bottom = current sound"
                                                                 if c.baseline_audio_wav else "current sound")))
        if not c.images:
            notes.append("No photo was provided.")
        if not c.audio_wav:
            notes.append("No machine sound recording was provided.")
        return att, notes

    def _prompt(self, signal: dict, intake: dict | None, missing: list[str]) -> str:
        c = self.ctx
        ac = c.acoustic or {}
        excerpts = "\n\n".join(f"[{h['doc']} | page {h['page']} | {h['section']}]\n{h['excerpt']}" for h in c.manual_hits)
        roi_q = c.case.evidence.roi_question or "What is happening inside this region?"
        return f"""MACHINE: {c.machine.name} - {c.machine.machine_type}, {c.machine.power_kw} kW, {c.machine.rated_rpm} rpm, {c.machine.notes}

SIGNAL ANALYST REPORT (from Tier-1 sensor box):
{js(signal)}

ACOUSTIC LAB (DSP measurements of the attached sound):
current features: {js(ac.get('current', {}))}
comparison with healthy baseline sound: {js(ac.get('comparison', 'no baseline recording'))}
rule hints: {ac.get('hints', [])}

TECHNICIAN VOICE NOTE: {js(intake) if intake else 'none'}
TECHNICIAN WRITTEN NOTES: {c.case.evidence.notes or 'none'}
REGION OF INTEREST QUESTION: {roi_q if c.roi_crop else 'no region marked'}
MISSING EVIDENCE: {' '.join(missing) or 'none'}

MACHINE HISTORY / LESSONS FROM PAST CASES:
{c.history_text or 'none'}

MANUAL EXCERPTS (the only sources you may cite):
{excerpts or 'none retrieved'}

FAULT SIGNATURE REFERENCE:
{FAULT_SIGNATURES}

TASK: Inspect every attachment, listen to the audio, and combine it with the telemetry to determine the most likely
root cause. Fill every field. modality_votes must contain one entry for each of: telemetry, image, audio, baseline,
voice_note, manual, history. Use stance 'not_provided' ONLY when that evidence is absent; if it is present but shows
nothing relevant (e.g. a photo with no visible defect) use 'neutral'. A photo showing no external damage is normal
for internal faults such as imbalance or bearing wear - say so instead of guessing."""

    def run(self, signal: dict, intake: dict | None) -> dict:
        att, missing = self._attachments()
        kinds = ", ".join(a.label.split(" ")[0].lower() for a in att)
        self.say("start", f"Fusing {len(att)} attachments ({kinds}) with telemetry, acoustic measurements, "
                          f"{len(self.ctx.manual_hits)} manual excerpts and machine history...")
        d: Diagnosis = self.ask(self._prompt(signal, intake, missing), Diagnosis, att, think=THINK, max_tokens=2500)
        out = self._verify_refs(d.model_dump())
        if self.ctx.roi_crop and not out.get("roi_findings", "").strip():
            out["roi_findings"] = self._region_answer()
        self.say("output", f"{out['severity']}: {out['fault']} at {out['component']} "
                           f"(confidence {round(100 * out['confidence'])}%). {out['cross_modal_reasoning']}", data=out)
        return out

    def revise(self, previous: dict, issues: list[str], signal: dict, intake: dict | None) -> dict:
        self.say("revision", "Revising the diagnosis to address the Safety Auditor's objections:\n- " + "\n- ".join(issues))
        prompt = (self._prompt(signal, intake, []) +
                  f"\n\nYOUR PREVIOUS DIAGNOSIS:\n{js(previous)}\n\nTHE SAFETY AUDITOR REJECTED IT FOR THESE REASONS:\n"
                  + "\n".join(f"- {i}" for i in issues) +
                  "\n\nProduce a corrected diagnosis. Keep what was right, fix every issue, put safety/isolation steps "
                  "FIRST in repair_steps, make the LAST repair step a verification ('Test run: restart, re-measure "
                  "vibration and temperature and compare with the healthy baseline'), and lower confidence if the "
                  "auditor found the evidence weak.")
        att, _ = self._attachments()
        d: Diagnosis = self.ask(prompt, Diagnosis, att, max_tokens=2500)
        out = self._verify_refs(d.model_dump())
        if not out.get("roi_findings", "").strip():
            out["roi_findings"] = previous.get("roi_findings", "")
        self.say("output", f"Revised: {out['severity']}: {out['fault']} at {out['component']} "
                           f"(confidence {round(100 * out['confidence'])}%).", data=out)
        return out

    def _region_answer(self) -> str:
        """Focused look at the technician-marked region when the fused answer skipped it."""
        q = self.ctx.case.evidence.roi_question or "What is happening inside this region? Any defect?"
        self.say("info", "Region of interest not covered by the fused answer; taking a focused look at it.")
        r: RegionAnswer = self.ask(
            f"Machine: {self.ctx.machine.name}. Question about the red region: {q}", RegionAnswer,
            [gemma.Attachment("image", self.ctx.roi_overlay, "full photo, region of interest outlined in red"),
             gemma.Attachment("image", self.ctx.roi_crop, "zoomed crop of the red region")], max_tokens=600)
        defects = f" Defects: {', '.join(r.defects_found)}." if r.defects_found else " No defect visible."
        return f"{r.answer}{defects}"

    def _verify_refs(self, d: dict) -> dict:
        """Trust-but-verify: keep only citations that point at excerpts we actually supplied,
        and check the quote really occurs on that page."""
        d["repair_steps"] = unnumber(d.get("repair_steps", []))
        allowed = {(h["doc"], h["page"]): h["excerpt"].lower() for h in self.ctx.manual_hits}
        kept, dropped = [], 0
        for r in d.get("manual_refs", []):
            key = (r.get("doc"), r.get("page"))
            if key in allowed:
                q = (r.get("quote") or "").lower().strip(' ".')
                r["verified"] = bool(q) and q[:40] in allowed[key]
                kept.append(r)
            else:
                dropped += 1
        if dropped:
            self.say("info", f"Citation check: removed {dropped} reference(s) that did not match a retrieved manual page.")
        d["manual_refs"] = kept
        return d


def acoustic_lab(ctx, agent: Agent):
    """Deterministic DSP tool step (features, baseline comparison, spectrogram)."""
    if not ctx.audio_wav:
        return None
    x = au.load(ctx.audio_wav)
    cur = au.features(x)
    out = {"current": au.public(cur), "hints": au.interpret(cur, ctx.machine.rated_rpm)}
    clips = []
    if ctx.baseline_audio_wav:
        xb = au.load(ctx.baseline_audio_wav)
        base = au.features(xb)
        out["baseline"] = au.public(base)
        out["comparison"] = au.compare(base, cur)
        clips.append(("BASELINE (healthy)", xb))
    clips.append(("CURRENT", x))
    ctx.spectrogram_png = au.spectrogram_png(clips)
    ctx.acoustic = out
    msg = f"Acoustic measurements: loudness {cur['rms_dbfs']} dBFS, high-band kurtosis {cur['highband_kurtosis']}, " \
          f"envelope modulation {cur['envelope_mod_hz']} Hz (prominence {cur['envelope_mod_prominence']})."
    if "comparison" in out:
        cmp_ = out["comparison"]
        msg += f" Versus healthy baseline: similarity {cmp_['spectral_similarity']}, novelty {cmp_['novelty_score']} " \
               f"-> {cmp_['verdict']}."
    agent.say("tool", msg, data=out)
    return out
