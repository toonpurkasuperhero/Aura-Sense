"""Shared agent plumbing: every agent talks to Gemma through `Agent.ask`, and
every step is written to the case's trace so the UI can show the conversation."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Callable, Optional, Type

from pydantic import BaseModel

from .. import gemma
from ..models import Case, MachineProfile, TraceEvent

Emit = Callable[[TraceEvent], None]


@dataclass
class Context:
    """The shared 'case file' (blackboard) that agents read from and write to."""
    case: Case
    machine: MachineProfile
    latest: Optional[dict]
    series: list[dict]
    emit: Emit
    images: list[bytes] = field(default_factory=list)       # prepared current photos
    roi_crop: Optional[bytes] = None
    roi_overlay: Optional[bytes] = None
    baseline_image: Optional[bytes] = None
    audio_wav: Optional[bytes] = None
    baseline_audio_wav: Optional[bytes] = None
    spectrogram_png: Optional[bytes] = None
    voice_wav: Optional[bytes] = None
    acoustic: Optional[dict] = None
    history_text: str = ""
    manual_hits: list[dict] = field(default_factory=list)


class Agent:
    name = "agent"
    title = "Agent"
    system = ""

    def __init__(self, ctx: Context):
        self.ctx = ctx

    def say(self, kind: str, content: str, data: Optional[dict] = None, duration: Optional[float] = None):
        self.ctx.emit(TraceEvent(agent=self.name, kind=kind, content=content, data=data, duration_s=duration))

    def ask(self, user: str, schema: Type[BaseModel], attachments: Optional[list[gemma.Attachment]] = None,
            think: bool = False, max_tokens: int = 2048) -> BaseModel:
        res = gemma.chat(self.system, user, attachments=attachments, schema=schema, think=think,
                         max_tokens=max_tokens)
        self.say("info", f"Gemma 4 call: {res.prompt_tokens} prompt tokens, {res.output_tokens} output tokens, "
                         f"{len(res.attachments)} attachment(s) [{', '.join(res.attachments)}]",
                 data={"attachments": res.attachments}, duration=res.duration_s)
        return res.parsed


_NUM = re.compile(r"^\s*(?:step\s*)?\d+\s*[\.\):-]\s*", re.I)


def unnumber(items: list[str]) -> list[str]:
    """The UI/PDF numbers steps itself; drop numbering the model added."""
    return [_NUM.sub("", s).strip() for s in items if s and s.strip()]


def js(obj) -> str:
    if isinstance(obj, BaseModel):
        obj = obj.model_dump()
    return json.dumps(obj, ensure_ascii=False, indent=1)
