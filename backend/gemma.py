"""Thin client for Gemma 4 running locally in Ollama.

Gemma 4 E4B accepts text, images and audio. Ollama takes both images and WAV
audio as base64 entries in the message's `images` list (verified on Ollama
0.40.x). Structured outputs are enforced with a JSON schema via `format`.
"""
from __future__ import annotations

import base64
import json
import logging
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Optional, Type

import requests
from pydantic import BaseModel, ValidationError

from .config import (AUDIO_MODE, GEMMA_MODEL, GEMMA_NUM_CTX, GEMMA_TEMPERATURE,
                     GEMMA_TIMEOUT_S, OLLAMA_URL)

log = logging.getLogger("aurasense.gemma")
_lock = threading.Lock()  # Ollama serves one request at a time on a laptop GPU anyway


@dataclass
class Attachment:
    kind: str          # "image" | "audio"
    data: bytes
    label: str         # human-readable label used in the prompt manifest


@dataclass
class GemmaResult:
    text: str
    parsed: Optional[BaseModel] = None
    duration_s: float = 0.0
    prompt_tokens: int = 0
    output_tokens: int = 0
    attachments: list[str] = field(default_factory=list)


class GemmaError(RuntimeError):
    pass


def _b64(b: bytes) -> str:
    return base64.b64encode(b).decode()


def status() -> dict:
    try:
        v = requests.get(f"{OLLAMA_URL}/api/version", timeout=3).json().get("version")
        tags = requests.get(f"{OLLAMA_URL}/api/tags", timeout=3).json().get("models", [])
        have = any(m.get("name", "").startswith(GEMMA_MODEL) for m in tags)
        loaded = requests.get(f"{OLLAMA_URL}/api/ps", timeout=3).json().get("models", [])
        return {"ollama": v, "model": GEMMA_MODEL, "model_present": have,
                "model_loaded": any(m.get("name", "").startswith(GEMMA_MODEL) for m in loaded),
                "audio_native": audio_supported()}
    except Exception as e:  # noqa: BLE001
        return {"ollama": None, "model": GEMMA_MODEL, "model_present": False, "error": str(e)}


_audio_ok: Optional[bool] = None


def audio_supported() -> bool:
    """Whether Gemma native audio input works (False once a native call has failed)."""
    if AUDIO_MODE == "native":
        return True
    if AUDIO_MODE == "spectrogram":
        return False
    return bool(_audio_ok) if _audio_ok is not None else True


def mark_audio_failed():
    global _audio_ok
    _audio_ok = False
    log.warning("Gemma native audio failed; falling back to spectrogram + DSP features")


def warmup():
    """Load the model into GPU memory so the first demo call is fast."""
    try:
        requests.post(f"{OLLAMA_URL}/api/generate",
                      json={"model": GEMMA_MODEL, "prompt": "ok", "stream": False, "keep_alive": "2h",
                            "options": {"num_predict": 1}}, timeout=GEMMA_TIMEOUT_S)
    except Exception as e:  # noqa: BLE001
        log.warning("warmup failed: %s", e)


STYLE = ("\n\nOutput style: plain text only. Never use LaTeX, '$' math, markdown or emojis inside JSON strings. "
         "Write units plainly, e.g. '15.6 Hz', '0.97x', '+13 °C'.")

_LATEX = [(re.compile(r"\t?ext\{([^}]*)\}"), r"\1"), (re.compile(r"\\text\{([^}]*)\}"), r"\1"),
          (re.compile(r"\\(?:mathrm|mathbf)\{([^}]*)\}"), r"\1"), (re.compile(r"\^\{?\\circ\}?"), "°"),
          (re.compile(r"\\times"), "x"), (re.compile(r"\\sim"), "~"), (re.compile(r"\\approx"), "≈"),
          (re.compile(r"\\%"), "%"), (re.compile(r"\\geq?"), ">="), (re.compile(r"\\leq?"), "<="),
          (re.compile(r"\$"), "")]


def clean(obj):
    """Strip LaTeX-isms the model sometimes emits, recursively."""
    if isinstance(obj, str):
        for pat, rep in _LATEX:
            obj = pat.sub(rep, obj)
        return obj.replace("\t", " ").strip()
    if isinstance(obj, list):
        return [clean(v) for v in obj]
    if isinstance(obj, dict):
        return {k: clean(v) for k, v in obj.items()}
    return obj


def _extract_json(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text).rstrip("`").strip()
    m = re.search(r"\{.*\}", text, re.S)
    return m.group(0) if m else text


def chat(system: str, user: str, attachments: Optional[list[Attachment]] = None,
         schema: Optional[Type[BaseModel]] = None, temperature: float = GEMMA_TEMPERATURE,
         think: bool = False, max_tokens: int = 2048, retries: int = 1) -> GemmaResult:
    """One Gemma call. Attachments are listed in a manifest at the top of the user
    message so the model knows which image/audio is which."""
    attachments = attachments or []
    if any(a.kind == "audio" for a in attachments) and not audio_supported():
        attachments = [a for a in attachments if a.kind != "audio"]
    manifest = ""
    if attachments:
        lines = [f"  [{i + 1}] {a.kind.upper()}: {a.label}" for i, a in enumerate(attachments)]
        manifest = "ATTACHMENTS (in this order):\n" + "\n".join(lines) + "\n\n"
    msg = {"role": "user", "content": manifest + user}
    if attachments:
        msg["images"] = [_b64(a.data) for a in attachments]
    body = {
        "model": GEMMA_MODEL,
        "stream": False,
        "think": think,
        "keep_alive": "2h",
        "messages": [{"role": "system", "content": system + STYLE}, msg],
        "options": {"temperature": temperature, "num_ctx": GEMMA_NUM_CTX, "num_predict": max_tokens},
    }
    if schema is not None:
        body["format"] = schema.model_json_schema()

    last_err: Optional[Exception] = None
    for attempt in range(retries + 1):
        t0 = time.time()
        try:
            with _lock:
                r = requests.post(f"{OLLAMA_URL}/api/chat", json=body, timeout=GEMMA_TIMEOUT_S)
            if r.status_code != 200:
                raise GemmaError(f"Ollama HTTP {r.status_code}: {r.text[:300]}")
            j = r.json()
            text = j.get("message", {}).get("content", "")
            res = GemmaResult(text=text, duration_s=round(time.time() - t0, 1),
                              prompt_tokens=j.get("prompt_eval_count", 0),
                              output_tokens=j.get("eval_count", 0),
                              attachments=[f"{a.kind}:{a.label}" for a in attachments])
            if schema is not None:
                raw = json.loads(_extract_json(text))
                res.parsed = schema.model_validate(clean(raw))
            return res
        except (ValidationError, json.JSONDecodeError) as e:
            last_err = e
            log.warning("Gemma JSON invalid (attempt %d): %s", attempt + 1, e)
            body["options"]["temperature"] = 0.1
        except requests.RequestException as e:
            last_err = e
            # A runner crash during audio processing is a known Ollama issue: retry without audio.
            if any(a.kind == "audio" for a in attachments) and AUDIO_MODE == "auto":
                mark_audio_failed()
                return chat(system, user, attachments, schema, temperature, think, max_tokens, retries)
        except GemmaError as e:
            last_err = e
            if "audio" in str(e).lower() and any(a.kind == "audio" for a in attachments):
                mark_audio_failed()
                return chat(system, user, attachments, schema, temperature, think, max_tokens, retries)
    raise GemmaError(f"Gemma call failed: {last_err}")
