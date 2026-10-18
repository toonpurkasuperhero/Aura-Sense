"""Safety Auditor: critiques the Diagnostician. Gemma reviews the plan like an
industrial safety officer; a set of hard safety and consistency rules is also
enforced in code so a critical omission can never slip through."""
from __future__ import annotations

import re

from .. import telemetry_analysis as ta
from ..models import SafetyAudit
from .base import Agent, Context, js

SYSTEM = ("You are the industrial safety officer and quality reviewer for a factory maintenance team (Indian "
          "Factories Act / OSHA style practice). You review an AI-generated diagnosis and repair plan BEFORE a "
          "technician sees it. Reject (verdict REVISE) if ANY of these hold: repair steps touch the machine without "
          "lock-out/tag-out and verifying zero energy; electrical work without isolation; rotating parts handled "
          "before full stop; hot surfaces not allowed to cool; severity HIGH/CRITICAL with confidence below 0.5; "
          "severity inconsistent with the measured data; the cited evidence contradicts the claimed fault; no "
          "post-repair verification; or the immediate action would let a CRITICAL machine keep running. "
          "Be specific and brief. Approve good plans - do not nitpick.")

_LOTO = re.compile(r"lock[\s\-]?out|loto|isolat|de-?energi|switch (it )?off|disconnect (the )?(power|supply)", re.I)
_VERIFY = re.compile(r"verif|re-?measure|re-?check|test run|trial run|compare .*baseline|monitor .*after|"
                     r"confirm .*vibration|check vibration", re.I)
_SEV = ["LOW", "MEDIUM", "HIGH", "CRITICAL"]


def hard_rules(d: dict, ctx: Context | None = None) -> list[str]:
    issues = []
    steps = d.get("repair_steps", [])
    text = " ".join(steps) + " " + d.get("immediate_action", "")
    sev = d.get("severity")
    if sev in ("HIGH", "CRITICAL") and d.get("confidence", 0) < 0.5:
        issues.append(f"Severity {sev} with confidence {d['confidence']:.2f} < 0.5: gather more evidence "
                      "or downgrade severity.")
    if d.get("fault_category") != "none" and steps and not _LOTO.search(text):
        issues.append("Repair steps do not start with electrical isolation / lock-out-tag-out and zero-energy check.")
    if d.get("fault_category") != "none" and steps and not _VERIFY.search(" ".join(steps[-3:])):
        issues.append("Plan has no post-repair verification: add a test run and re-measure vibration/temperature "
                      "against the healthy baseline before handing the machine back.")
    if d.get("time_to_failure") == "hours" and sev in ("LOW", "MEDIUM"):
        issues.append(f"Time to failure 'hours' is inconsistent with severity {sev}.")
    contra = [v for v in d.get("modality_votes", []) if v.get("stance") == "contradicts"]
    if len(contra) >= 2:
        issues.append(f"{len(contra)} evidence sources contradict the diagnosis "
                      f"({', '.join(v['modality'] for v in contra)}); justify or reconsider.")
    if ctx is not None:
        latest = ctx.latest or ctx.case.trigger or {}
        g = ta.guide_severity(latest)
        if g and sev in _SEV and _SEV.index(sev) < _SEV.index(g):
            issues.append(f"Severity {sev} is lower than the measured data supports: vibration/temperature vs. "
                          f"baseline puts this at {g} by the severity guide. Raise severity or justify.")
        if latest.get("flame") and sev != "CRITICAL":
            issues.append("The flame sensor TRIPPED: severity must be CRITICAL and the immediate action must be to "
                          "stop the machine, isolate power and use the correct (CO2/dry-powder) extinguisher.")
        # A fire overrides vibration signatures; don't demand the diagnosis chase them.
        persist = {} if latest.get("flame") else ta.persistent_signatures(ctx.series, ctx.machine)
        fault_text = (d.get("fault", "") + " " + d.get("component", "")).lower()
        for key, n in persist.items():
            if not any(w in fault_text for w in ta.FAULT_WORDS[key]):
                diff = " ".join(x.get("fault", "") + " " + x.get("why_less_likely", "") for x in d.get("differential", []))
                issues.append(f"The vibration signature of {key} persisted in {n} of the last 5 sensor windows, but the "
                              f"diagnosis is '{d.get('fault')}'. Either adopt {key.lower()} or give specific numeric "
                              f"evidence that rules it out (current differential says: '{diff[:160]}').")
        votes = {v.get("modality"): v.get("stance") for v in d.get("modality_votes", [])}
        if ctx.images and votes.get("image") == "not_provided":
            issues.append("A photo WAS provided but the diagnosis marks the image as not provided; inspect it.")
        if ctx.audio_wav and votes.get("audio") == "not_provided":
            issues.append("A sound recording WAS provided but the diagnosis marks audio as not provided; use it.")
    return issues


class SafetyAuditor(Agent):
    name = "safety_auditor"
    title = "Safety Auditor"
    system = SYSTEM

    def run(self, diagnosis: dict, round_no: int) -> dict:
        self.say("start", f"Reviewing diagnosis and repair plan (round {round_no})...")
        latest = self.ctx.latest or {}
        prompt = f"""MACHINE: {self.ctx.machine.name} ({self.ctx.machine.machine_type}, {self.ctx.machine.power_kw} kW)
Current surface temperature: {latest.get('temp_c')} °C (baseline {latest.get('temp_baseline_c')}). Edge status: {latest.get('status')}.
Severity suggested by the measured data: {ta.guide_severity(latest) or 'unknown'}.

DIAGNOSIS AND PLAN TO REVIEW:
{js(diagnosis)}

Review it. List concrete issues (empty if none), the safety steps that must come first, PPE, whether LOTO is
required, whether the machine may keep running until the repair, and hazard notes."""
        a: SafetyAudit = self.ask(prompt, SafetyAudit, max_tokens=900)
        out = a.model_dump()
        rules = hard_rules(diagnosis, self.ctx)
        if rules:
            self.say("tool", "Hard safety/consistency rules flagged:\n- " + "\n- ".join(rules), data={"rules": rules})
            for r in rules:
                if r not in out["issues"]:
                    out["issues"].append(r)
            out["verdict"] = "REVISE"
        elif out["verdict"] == "REVISE" and not out["issues"]:
            out["verdict"] = "APPROVE"  # a rejection without reasons is not actionable
        if out["verdict"] == "REVISE":
            self.say("critique", "REVISE - " + " | ".join(out["issues"]), data=out)
        else:
            self.say("output", "APPROVED. Safety steps added: " + "; ".join(out["added_safety_steps"][:3]), data=out)
        return out
