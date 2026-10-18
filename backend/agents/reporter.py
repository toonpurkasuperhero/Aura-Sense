"""Reporter: writes the shift-log entry, a 5-Why root-cause analysis,
preventive actions and a plain-language operator message (English + local
language such as Hindi or Kannada)."""
from __future__ import annotations

import re

from pydantic import BaseModel

from ..models import CaseReport
from .base import Agent, js

SYSTEM = ("You are the maintenance documentation officer. You write concise shift-log entries, rigorous 5-Why "
          "root-cause analyses (each 'why' must follow from the previous answer and stay grounded in the evidence) "
          "and preventive actions. You also write very simple operator messages that a machine operator with no "
          "engineering background understands, and translate them faithfully into the requested Indian language "
          "using its native script.")

# Unicode block of each supported language's native script.
SCRIPTS = {"Hindi": (0x0900, 0x097F), "Marathi": (0x0900, 0x097F), "Kannada": (0x0C80, 0x0CFF),
           "Tamil": (0x0B80, 0x0BFF), "Telugu": (0x0C00, 0x0C7F)}


def script_purity(text: str, lang: str) -> float:
    """Share of letters that are in the language's native script (Latin letters for brand/unit words allowed)."""
    lo, hi = SCRIPTS[lang]
    letters = [ch for ch in text if ch.isalpha()]
    if not letters:
        return 0.0
    ok = sum(1 for ch in letters if lo <= ord(ch) <= hi or ch.isascii())
    return ok / len(letters)


class Translation(BaseModel):
    text: str


class Reporter(Agent):
    name = "reporter"
    title = "Reporter"
    system = SYSTEM

    def run(self, diagnosis: dict, audit: dict, work_order: dict) -> dict:
        lang = self.ctx.case.evidence.language or "English"
        self.say("start", f"Writing shift log, 5-Why RCA and operator message ({lang})...")
        prompt = f"""MACHINE: {self.ctx.machine.name} at {self.ctx.machine.location}
CASE: {self.ctx.case.id}, alert reason: {self.ctx.case.trigger_reason}

DIAGNOSIS: {js(diagnosis)}
SAFETY: can keep running until repair = {audit.get('can_run_until_repair')}; LOTO = {audit.get('loto_required')}
WORK ORDER: {work_order.get('title')} - {work_order.get('priority')} - assigned to {work_order.get('service_centre_id')}

Write the report. operator_message_local must be in {lang} (native script). If {lang} is English, repeat the English text."""
        r: CaseReport = self.ask(prompt, CaseReport, max_tokens=1400)
        out = r.model_dump()
        for w in out["five_whys"]:
            w["why"] = re.sub(r"^\s*(why\s*\d*\s*)?[:\-.]*\s*", "", w["why"], flags=re.I)
            w["answer"] = re.sub(r"^\s*(because\s*)?[:\-.]+\s*", r"\1", w["answer"], flags=re.I)
        if lang in SCRIPTS:
            out["operator_message_local"] = self._check_script(out["operator_message_local"], out["operator_message_en"], lang)
        self.say("output", f"Shift log: {out['shift_log_entry']}", data=out)
        return out

    def _check_script(self, local: str, english: str, lang: str) -> str:
        """Small models sometimes drift into another script mid-sentence; verify and re-translate."""
        purity = script_purity(local, lang)
        if purity >= 0.95:
            return local
        self.say("tool", f"Script check: only {purity:.0%} of the {lang} message is in {lang} script; re-translating.")
        best, best_p = local, purity
        for _ in range(2):
            t: Translation = self.ask(
                f"Translate this message for a machine operator into simple {lang}. Use ONLY {lang} script "
                f"(no other Indian or foreign scripts). Keep numbers as digits.\n\nMESSAGE: {english}",
                Translation, max_tokens=400)
            p = script_purity(t.text, lang)
            if p > best_p:
                best, best_p = t.text, p
            if p >= 0.95:
                break
        if best_p < 0.95:
            self.say("info", f"Could not get a clean {lang} translation; showing the English message instead.")
            return english
        return best
