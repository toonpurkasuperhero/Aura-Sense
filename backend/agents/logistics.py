"""Logistics Coordinator: turns the approved diagnosis into a work order, parts
list, cost estimate and picks + messages the best repair centre."""
from __future__ import annotations

from .. import knowledge
from ..config import DOWNTIME_COST_PER_HOUR_INR
from ..models import WorkOrder
from .base import Agent, js, unnumber

SYSTEM = ("You are the maintenance planner / logistics coordinator of a small Indian factory. You convert an "
          "approved diagnosis into an actionable work order: priority, downtime estimate, skills, ordered tasks, "
          "parts with realistic Indian market prices in INR, and the best repair centre from the provided list "
          "(or 'in_house' if a local technician can do it with common tools). Write the vendor WhatsApp message "
          "in short, polite Indian-English business style with machine, fault, urgency and parts.")


PRIORITY_FOR = {"LOW": ["P4-Planned", "P3-This week"], "MEDIUM": ["P3-This week", "P2-24h"],
                "HIGH": ["P2-24h", "P1-Immediate"], "CRITICAL": ["P1-Immediate"]}


class LogisticsCoordinator(Agent):
    name = "logistics"
    title = "Logistics Coordinator"
    system = SYSTEM

    def run(self, diagnosis: dict, audit: dict) -> dict:
        m = self.ctx.machine
        self.say("start", "Planning the work order, parts and repair centre...")
        cands = knowledge.rank_centres(knowledge.keywords_for(diagnosis.get("fault", ""), m.machine_type))
        self.say("tool", "Repair-centre search: " + "; ".join(
            f"{c['id']} {c['name']} ({c['distance_km']} km, match {c['specialty_match']}, ~{c['avg_response_hours']} h)"
            for c in cands), data={"candidates": cands})
        cost_h = m.downtime_cost_per_hour_inr or DOWNTIME_COST_PER_HOUR_INR
        prompt = f"""MACHINE: {m.name} ({m.machine_type}, {m.power_kw} kW, {m.rated_rpm} rpm), criticality {m.criticality},
downtime cost about Rs {cost_h:.0f}/hour. Site: {knowledge.site()['name']}.

APPROVED DIAGNOSIS:
{js(diagnosis)}

SAFETY AUDIT:
{js(audit)}

CANDIDATE REPAIR CENTRES (choose by id):
{js([{k: c[k] for k in ('id', 'name', 'area', 'specialties', 'distance_km', 'avg_response_hours', 'visit_charge_inr', 'rating')} for c in cands])}

PARTS PRICE HINTS (INR):
{js(knowledge.price_hints())}

Create the work order. Include the safety steps as the first tasks. Priority must match severity and time to failure."""
        w: WorkOrder = self.ask(prompt, WorkOrder, max_tokens=1200)
        out = w.model_dump()
        out["tasks"] = unnumber(out["tasks"])
        allowed = PRIORITY_FOR.get(diagnosis.get("severity"), list(PRIORITY_FOR["MEDIUM"]))
        if out["priority"] not in allowed:
            self.say("info", f"Priority {out['priority']} adjusted to {allowed[0]} to match severity {diagnosis.get('severity')}.")
            out["priority"] = allowed[0]
        ids ={c["id"] for c in cands}
        if out["service_centre_id"] not in ids and out["service_centre_id"] != "in_house":
            out["service_centre_id"] = cands[0]["id"]
        out["candidates"] = cands
        out["downtime_cost_per_hour_inr"] = cost_h
        self.say("output", f"{out['priority']} work order '{out['title']}', ~{out['est_downtime_hours']} h downtime, "
                           f"~Rs {out['est_total_cost_inr']:.0f}; assigned to {out['service_centre_id']}.", data=out)
        return out
