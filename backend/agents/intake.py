"""Intake Clerk: listens to the technician's spoken voice note (any language)
with Gemma 4 native audio and extracts the symptoms."""
from __future__ import annotations

import io

from .. import gemma
from ..config import WHISPER_MODEL
from ..models import IntakeReport
from .base import Agent

SYSTEM = ("You are the intake clerk of a factory maintenance team. You receive a technician's voice note "
          "about a machine problem. Transcribe it exactly, identify the language (Indian languages are common: "
          "Hindi, Kannada, Tamil, Telugu, English or mixed), translate to English and list the concrete symptoms "
          "(sounds, smells, heat, when it happens, what changed). Do not invent symptoms.")


def _whisper(wav: bytes) -> tuple[str, str] | None:
    """Optional fallback STT if Gemma native audio is unavailable."""
    try:
        from faster_whisper import WhisperModel  # type: ignore
    except ImportError:
        return None
    model = WhisperModel(WHISPER_MODEL, device="auto", compute_type="int8")
    segs, info = model.transcribe(io.BytesIO(wav))
    return " ".join(s.text for s in segs).strip(), info.language


class IntakeClerk(Agent):
    name = "intake"
    title = "Intake Clerk"
    system = SYSTEM

    def run(self) -> dict | None:
        wav = self.ctx.voice_wav
        if not wav:
            return None
        self.say("start", "Listening to the technician's voice note...")
        if gemma.audio_supported():
            r: IntakeReport = self.ask("Transcribe and analyse this voice note.", IntakeReport,
                                       [gemma.Attachment("audio", wav, "technician voice note")], max_tokens=800)
            out = r.model_dump()
        else:
            w = _whisper(wav)
            if not w:
                self.say("error", "Voice note skipped: Gemma native audio unavailable and faster-whisper not installed.")
                return None
            text, lang = w
            self.say("tool", f"Fallback speech-to-text (Whisper {WHISPER_MODEL}) transcribed the note ({lang}).")
            r = self.ask(f"Voice note transcript (language code {lang}):\n{text}\n\nAnalyse it.", IntakeReport, max_tokens=800)
            out = r.model_dump()
        self.say("output", f"Technician said ({out['language']}): \"{out['english_translation']}\". "
                           f"Symptoms: {', '.join(out['symptoms']) or 'none stated'}.", data=out)
        return out
