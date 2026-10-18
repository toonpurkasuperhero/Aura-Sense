"""Persistence: SQLite for telemetry, machines and cases, with an in-memory
ring buffer per node for fast live charts."""
from __future__ import annotations

import json
import shutil
import sqlite3
import threading
import uuid
from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Optional

from .config import DB_PATH, KNOWLEDGE_DIR, ROOT, UPLOAD_DIR
from .models import Case, MachineProfile, Telemetry, TraceEvent, utcnow

RING_SIZE = 1800  # ~1 h at one sample every 2 s


class Store:
    def __init__(self, path=DB_PATH):
        self._lock = threading.RLock()
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.executescript(
            """
            CREATE TABLE IF NOT EXISTS telemetry (node_id TEXT, ts TEXT, body TEXT);
            CREATE INDEX IF NOT EXISTS ix_tel ON telemetry(node_id, ts);
            CREATE TABLE IF NOT EXISTS machines (node_id TEXT PRIMARY KEY, body TEXT);
            CREATE TABLE IF NOT EXISTS cases (id TEXT PRIMARY KEY, node_id TEXT, status TEXT,
                                              opened_at TEXT, body TEXT);
            CREATE TABLE IF NOT EXISTS sim (node_id TEXT PRIMARY KEY, body TEXT);
            """
        )
        self._ring: dict[str, deque] = {}
        self._seed_machines()
        self._warm_ring()

    # ------------------------------------------------------------ machines
    def _seed_machines(self):
        seed = KNOWLEDGE_DIR / "machine_profiles.json"
        if not seed.exists():
            return
        with self._lock:
            have = {r[0] for r in self._db.execute("SELECT node_id FROM machines")}
            for m in json.loads(seed.read_text()):
                demo = m.pop("demo_baseline", {})
                if m["node_id"] in have:
                    continue
                prof = MachineProfile(**m)
                # Seed a healthy baseline photo + sound from the open demo assets, if present.
                for field, rel in (("baseline_image", demo.get("image")), ("baseline_audio", demo.get("audio"))):
                    src = ROOT / "demo_assets" / rel if rel else None
                    if src and src.exists():
                        dst = UPLOAD_DIR / f"baseline_{prof.node_id}" / src.name
                        dst.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy(src, dst)
                        setattr(prof, field, f"baseline_{prof.node_id}/{src.name}")
                self.save_machine(prof)

    def save_machine(self, m: MachineProfile):
        with self._lock:
            self._db.execute("INSERT OR REPLACE INTO machines VALUES (?,?)", (m.node_id, m.model_dump_json()))
            self._db.commit()

    def get_machine(self, node_id: str) -> MachineProfile:
        with self._lock:
            row = self._db.execute("SELECT body FROM machines WHERE node_id=?", (node_id,)).fetchone()
        if row:
            return MachineProfile.model_validate_json(row[0])
        # Unknown node that started sending data: auto-register it.
        m = MachineProfile(node_id=node_id, name=node_id.replace("_", " ").title())
        self.save_machine(m)
        return m

    def list_machines(self) -> list[MachineProfile]:
        with self._lock:
            rows = self._db.execute("SELECT body FROM machines ORDER BY node_id").fetchall()
        return [MachineProfile.model_validate_json(r[0]) for r in rows]

    # ------------------------------------------------------------ telemetry
    def _warm_ring(self):
        since = (utcnow() - timedelta(hours=1)).isoformat()
        with self._lock:
            rows = self._db.execute(
                "SELECT node_id, body FROM telemetry WHERE ts > ? ORDER BY ts", (since,)
            ).fetchall()
        for node_id, body in rows:
            self._ring.setdefault(node_id, deque(maxlen=RING_SIZE)).append(json.loads(body))

    def add_telemetry(self, t: Telemetry) -> dict:
        if t.ts is None:
            t.ts = utcnow()
        if t.ts.tzinfo is None:
            t.ts = t.ts.replace(tzinfo=timezone.utc)
        rec = json.loads(t.model_dump_json())
        with self._lock:
            self._db.execute("INSERT INTO telemetry VALUES (?,?,?)", (t.node_id, t.ts.isoformat(), json.dumps(rec)))
            self._db.commit()
            self._ring.setdefault(t.node_id, deque(maxlen=RING_SIZE)).append(rec)
        self.get_machine(t.node_id)  # auto-register
        return rec

    def series(self, node_id: str, minutes: float = 10) -> list[dict]:
        cutoff = utcnow() - timedelta(minutes=minutes)
        ring = list(self._ring.get(node_id, []))
        return [r for r in ring if datetime.fromisoformat(r["ts"]) >= cutoff]

    def latest(self, node_id: str) -> Optional[dict]:
        ring = self._ring.get(node_id)
        return ring[-1] if ring else None

    # ------------------------------------------------------------ cases
    def new_case(self, node_id: str, trigger: Optional[dict], reason: str, status="ALERT") -> Case:
        cid = f"C-{utcnow().strftime('%m%d-%H%M%S')}-{uuid.uuid4().hex[:4]}"
        c = Case(id=cid, node_id=node_id, status=status, trigger=trigger, trigger_reason=reason)
        self.save_case(c)
        return c

    def save_case(self, c: Case):
        c.updated_at = utcnow()
        with self._lock:
            self._db.execute(
                "INSERT OR REPLACE INTO cases VALUES (?,?,?,?,?)",
                (c.id, c.node_id, c.status, c.opened_at.isoformat(), c.model_dump_json()),
            )
            self._db.commit()

    def get_case(self, cid: str) -> Optional[Case]:
        with self._lock:
            row = self._db.execute("SELECT body FROM cases WHERE id=?", (cid,)).fetchone()
        return Case.model_validate_json(row[0]) if row else None

    def list_cases(self, node_id: Optional[str] = None, open_only=False, limit=200) -> list[Case]:
        q, args = "SELECT body FROM cases", []
        conds = []
        if node_id:
            conds.append("node_id=?")
            args.append(node_id)
        if open_only:
            conds.append("status NOT IN ('RESOLVED')")
        if conds:
            q += " WHERE " + " AND ".join(conds)
        q += " ORDER BY opened_at DESC LIMIT ?"
        args.append(limit)
        with self._lock:
            rows = self._db.execute(q, args).fetchall()
        return [Case.model_validate_json(r[0]) for r in rows]

    def open_case_for(self, node_id: str) -> Optional[Case]:
        for c in self.list_cases(node_id=node_id, open_only=True, limit=5):
            return c
        return None

    def append_trace(self, cid: str, ev: TraceEvent):
        with self._lock:
            c = self.get_case(cid)
            if c:
                c.trace.append(ev)
                self.save_case(c)

    def update_case(self, cid: str, **fields) -> Optional[Case]:
        with self._lock:
            c = self.get_case(cid)
            if not c:
                return None
            for k, v in fields.items():
                setattr(c, k, v)
            self.save_case(c)
            return c

    def delete_case(self, cid: str):
        with self._lock:
            self._db.execute("DELETE FROM cases WHERE id=?", (cid,))
            self._db.commit()

    # ------------------------------------------------------------ simulator control
    def get_sim(self, node_id: str) -> dict:
        with self._lock:
            row = self._db.execute("SELECT body FROM sim WHERE node_id=?", (node_id,)).fetchone()
        return json.loads(row[0]) if row else {"scenario": "normal", "severity": 0.0, "since": None}

    def set_sim(self, node_id: str, body: dict):
        with self._lock:
            self._db.execute("INSERT OR REPLACE INTO sim VALUES (?,?)", (node_id, json.dumps(body)))
            self._db.commit()


store = Store()
