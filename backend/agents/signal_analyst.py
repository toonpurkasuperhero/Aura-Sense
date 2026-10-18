"""Signal Analyst: reads the Tier-1 telemetry like a vibration analyst would."""
from __future__ import annotations

from .. import telemetry_analysis as ta
from ..knowledge import FAULT_SIGNATURES
from ..models import SignalReport
from .base import Agent

SYSTEM = ("You are a certified vibration analyst (ISO 18436 Cat II) working for a small Indian factory. "
          "You interpret edge-sensor telemetry (tri-axial vibration RMS, FFT peaks, temperature, sound level, "
          "motor current) and map it to rotating-machine faults using order analysis. Be quantitative, cite the "
          "numbers, and never claim more than the data supports. The DETERMINISTIC RULE HINTS come from a "
          "validated order-analysis engine looking at the whole spectrum: rank the fault they name first unless "
          "you can cite specific numbers that contradict it. If data is ambiguous say so and request the "
          "photo/sound evidence that would disambiguate.")


class SignalAnalyst(Agent):
    name = "signal_analyst"
    title = "Signal Analyst"
    system = SYSTEM

    def run(self, intake: dict | None) -> dict:
        c = self.ctx
        self.say("start", "Reading the sensor box telemetry and FFT spectrum...")
        latest = c.latest or c.case.trigger or {}
        hints = (ta.window_hints(c.series, c.machine) or ta.order_hints(latest, c.machine)) + ta.other_hints(latest)
        rul = ta.rul_estimate(c.series)
        self.say("tool", "Order analysis + rule checks:\n- " + "\n- ".join(hints or ["no rule fired"]),
                 data={"hints": hints, "rul": rul})
        prompt = f"""TELEMETRY SUMMARY (last minutes):
{ta.summarize(c.series, latest, c.machine)}

DETERMINISTIC RULE HINTS (from order analysis, treat as evidence not truth):
{chr(10).join('- ' + h for h in hints) or '- none'}

HEALTH TREND: {rul}

ALERT REASON FROM EDGE: {c.case.trigger_reason or 'n/a'}

TECHNICIAN VOICE NOTE SYMPTOMS: {(intake or {}).get('symptoms') or 'none'}
TECHNICIAN NOTES: {c.case.evidence.notes or 'none'}

MACHINE HISTORY / PAST LESSONS:
{c.history_text or 'No previous cases.'}

FAULT SIGNATURE REFERENCE:
{FAULT_SIGNATURES}

Give your analysis: key observations with numbers, the top 3 candidate faults with likelihoods that sum to <= 1,
the trend, and which photos/sounds the technician should capture to confirm."""
        r: SignalReport = self.ask(prompt, SignalReport, max_tokens=1200)
        out = r.model_dump()
        cands = "; ".join(f"{x['fault']} ({round(100 * x['likelihood'])}%)" for x in out["candidates"])
        self.say("output", f"Candidates: {cands}. Trend: {out['trend']}", data=out)
        return out
