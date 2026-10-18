"""Knowledge tools used by the agents: service-manual retrieval (BM25 over PDF
pages), fault-signature reference and the repair-centre directory."""
from __future__ import annotations

import json
import math
import re
import threading
from collections import Counter
from typing import Optional

from pypdf import PdfReader

from .config import DATA_DIR, KNOWLEDGE_DIR, MANUALS_DIR

FAULT_SIGNATURES = (KNOWLEDGE_DIR / "fault_signatures.md").read_text()
_CACHE = DATA_DIR / "manual_cache.json"
_STOP = set("the a an and or of to in on for with is are be by as at it this that from if not no use "
            "should must may can will all any when which than then into per its".split())
_EN = set("the and of to is are with for this that be should motor bearing".split())
_FOREIGN = set("de la el los las del para com uma não que em os das dos se motores rolamento".split())


def _tok(s: str) -> list[str]:
    return [w for w in re.findall(r"[a-z][a-z0-9\-]+", s.lower()) if w not in _STOP and len(w) > 2]


def _is_english(text: str) -> bool:
    words = re.findall(r"[a-zçãõáéíóú]+", text.lower())
    en = sum(w in _EN for w in words)
    fo = sum(w in _FOREIGN for w in words)
    return en >= 5 and en > 1.5 * fo


class ManualIndex:
    def __init__(self):
        self._lock = threading.Lock()
        self.pages: list[dict] = []
        self._built_for: dict[str, float] = {}

    def _load_cache(self) -> dict:
        if _CACHE.exists():
            try:
                return json.loads(_CACHE.read_text())
            except Exception:  # noqa: BLE001
                return {}
        return {}

    def build(self):
        with self._lock:
            cache = self._load_cache()
            pages = []
            for pdf in sorted(MANUALS_DIR.glob("*.pdf")):
                key = f"{pdf.name}:{pdf.stat().st_mtime}"
                if key not in cache:
                    try:
                        r = PdfReader(str(pdf))
                        cache[key] = [(p.extract_text() or "") for p in r.pages]
                    except Exception as e:  # noqa: BLE001
                        cache[key] = []
                        print(f"[manuals] could not read {pdf.name}: {e}")
                for i, txt in enumerate(cache[key]):
                    txt = re.sub(r"[ \t]+", " ", txt)
                    if len(txt) < 200 or not _is_english(txt) or txt.count("....") > 8:
                        continue  # skip short, non-English and table-of-contents pages
                    pages.append({"doc": pdf.name, "page": i + 1, "text": txt, "toks": _tok(txt)})
            _CACHE.write_text(json.dumps({k: v for k, v in cache.items()}))
            self.pages = pages
            n = len(pages) or 1
            self.avgdl = sum(len(p["toks"]) for p in pages) / n
            df = Counter()
            for p in pages:
                df.update(set(p["toks"]))
                p["tf"] = Counter(p["toks"])
            self.idf = {w: math.log(1 + (n - c + 0.5) / (c + 0.5)) for w, c in df.items()}

    def docs(self) -> list[dict]:
        out = Counter(p["doc"] for p in self.pages)
        return [{"doc": d, "english_pages_indexed": c} for d, c in sorted(out.items())]

    def search(self, query: str, k: int = 4, docs: Optional[list[str]] = None) -> list[dict]:
        if not self.pages:
            self.build()
        q = _tok(query)
        if not q:
            return []
        scored = []
        for p in self.pages:
            if docs and p["doc"] not in docs:
                continue
            dl = len(p["toks"]) or 1
            s = 0.0
            for w in q:
                f = p["tf"].get(w, 0)
                if f:
                    s += self.idf.get(w, 0) * f * 2.2 / (f + 1.2 * (0.25 + 0.75 * dl / self.avgdl))
            if s > 0:
                scored.append((s, p))
        scored.sort(key=lambda x: -x[0])
        hits = []
        for s, p in scored[:k]:
            hits.append({"doc": p["doc"], "page": p["page"], "score": round(s, 2),
                         "section": _guess_section(p["text"]), "excerpt": _best_window(p["text"], set(q))})
        return hits


def _guess_section(text: str) -> str:
    for line in text.splitlines()[:6]:
        line = line.strip()
        if 6 < len(line) < 80 and not line.lower().startswith(("mn4", "page")):
            return line
    return ""


def _best_window(text: str, q: set, size: int = 1100) -> str:
    words = text.split()
    if len(words) <= 180:
        return text.strip()
    best, best_i = -1, 0
    for i in range(0, len(words) - 150, 25):
        win = words[i:i + 170]
        score = sum(1 for w in win if w.lower().strip(".,:;()") in q)
        if score > best:
            best, best_i = score, i
    return " ".join(words[best_i:best_i + 170])[:size]


manuals = ManualIndex()


# ---------------------------------------------------------------- service centres
_SC = json.loads((KNOWLEDGE_DIR / "service_centres.json").read_text())


def site() -> dict:
    return _SC["site"]


def all_centres() -> list[dict]:
    return _SC["centres"]


def price_hints() -> dict:
    return _SC.get("parts_price_hints_inr", {})


def _km(a_lat, a_lon, b_lat, b_lon) -> float:
    r = 6371
    p1, p2 = math.radians(a_lat), math.radians(b_lat)
    dp, dl = p2 - p1, math.radians(b_lon - a_lon)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def rank_centres(keywords: list[str], k: int = 3) -> list[dict]:
    s = site()
    kw = {w.lower() for w in keywords}
    out = []
    for c in all_centres():
        dist = _km(s["lat"], s["lon"], c["lat"], c["lon"])
        match = len(kw & set(c["specialties"]))
        score = match * 3 + c["rating"] - dist / 10 - c["avg_response_hours"] / 6
        out.append({**c, "distance_km": round(dist, 1), "specialty_match": match, "score": round(score, 2)})
    out.sort(key=lambda c: -c["score"])
    return out[:k]


def centre(cid: str) -> Optional[dict]:
    return next((c for c in all_centres() if c["id"] == cid), None)


def keywords_for(fault: str, machine_type: str) -> list[str]:
    f = fault.lower()
    kws = [machine_type]
    for word, tags in {"bearing": ["bearing"], "imbalance": ["balancing", "vibration"], "unbalance": ["balancing"],
                       "misalign": ["alignment", "coupling"], "loose": ["vibration", "alignment"],
                       "belt": ["belt"], "electr": ["electrical", "motor_rewinding"], "winding": ["motor_rewinding"],
                       "stator": ["motor_rewinding", "electrical"], "cavitation": ["cavitation", "pump"],
                       "seal": ["seal"], "impeller": ["impeller"], "lubric": ["bearing"], "overheat": ["electrical", "bearing"],
                       "corros": ["motor", "spares"]}.items():
        if word in f:
            kws += tags
    return kws
