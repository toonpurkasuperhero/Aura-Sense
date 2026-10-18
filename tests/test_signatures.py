"""Each simulated fault must be recognised by the edge order-analysis rules.

    .venv/bin/python -m pytest tests -q
"""
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "simulator"))

from backend import telemetry_analysis as ta  # noqa: E402
from backend.models import MachineProfile  # noqa: E402
from mock_esp32 import NODES, Node  # noqa: E402

CFG = {"motor_01": ("motor", 1440), "pump_03": ("pump", 2900), "fan_02": ("fan", 960)}
EXPECT = {
    "normal": "normal band",
    "imbalance": "IMBALANCE",
    "misalignment": "MISALIGNMENT",
    "looseness": "LOOSENESS",
    "bearing": "BEARING",
    "electrical": "ELECTRICAL",
    "overheat": "temperature",
}


def series(scenario: str, node_id="motor_01", severity=0.8, seed=0, n=5) -> list[dict]:
    node = Node(node_id, NODES[node_id], "http://unused", learn_windows=10, local="normal:0")
    node.poll_command = lambda: None
    node.rng = np.random.default_rng(seed)
    for _ in range(10):
        node.step()
    node.local = f"{scenario}:{severity}"
    out = [node.step() for _ in range(35)]  # let the thermal response settle
    return out[-n:]


def hints_for(scenario: str, node_id: str, seed=0) -> tuple[str, dict]:
    m = MachineProfile(node_id=node_id, name="m", machine_type=CFG[node_id][0], rated_rpm=CFG[node_id][1], line_hz=50)
    s = series(scenario, node_id, seed=seed)
    return " ".join(ta.window_hints(s, m) + ta.other_hints(s[-1])), s[-1]


def test_every_fault_on_every_machine():
    for node_id in CFG:
        for scenario, expect in EXPECT.items():
            h, last = hints_for(scenario, node_id)
            assert expect.lower() in h.lower(), f"{node_id}/{scenario}: {h}"
            if scenario != "normal":
                assert last["status"] == "ALERT", f"{node_id}/{scenario} did not alert"


def test_cavitation_vs_looseness_vs_bearing_over_seeds():
    """Broadband (cavitation) must not be confused with looseness or bearing, over many seeds."""
    for node_id in CFG:
        cav = sum("CAVITATION" in hints_for("cavitation", node_id, seed)[0] or
                  "Broadband" in hints_for("cavitation", node_id, seed)[0] for seed in range(10))
        assert cav >= 8, f"{node_id}: cavitation recognised only {cav}/10"
        for other in ("looseness", "bearing", "imbalance", "misalignment"):
            fp = sum("Broadband" in hints_for(other, node_id, seed)[0] for seed in range(10))
            assert fp == 0, f"{node_id}/{other}: falsely broadband {fp}/10"
