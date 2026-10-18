"""End-to-end smoke test against a running backend + simulator.

1. sets the healthy baseline (photo + sound) for a machine
2. injects a fault in the simulator and waits for the Tier-1 ALERT case
3. uploads photo + machine sound + voice note + region of interest
4. runs the multi-agent Gemma pipeline and prints the live trace
5. downloads the PDF ticket

    python scripts/smoke_test.py --node fan_02 --scenario imbalance
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
A = ROOT / "demo_assets"

PRESETS = {
    "fan_02": {"baseline_img": "images/exhaust_fan_healthy.jpg", "baseline_wav": "audio/fan_normal_1.wav",
               "img": "images/fan_damaged.jpg", "wav": "audio/fan_abnormal_1.wav", "roi": "0.35,0.25,0.68,0.62",
               "q": "Is anything wrong with the fan hub and blades inside this box?"},
    "motor_01": {"baseline_img": "images/motor_3phase_healthy.jpg", "baseline_wav": "audio/fan_normal_2.wav",
                 "img": "images/motor_belt_drive_dusty.jpg", "wav": "audio/fan_abnormal_2.wav", "roi": "",
                 "q": ""},
    "pump_03": {"baseline_img": "images/pump_centrifugal.jpg", "baseline_wav": "audio/pump_normal_1.wav",
                "img": "images/pump_housing_corroded.jpg", "wav": "audio/pump_abnormal_1.wav", "roi": "",
                "q": ""},
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", default="http://127.0.0.1:8000")
    ap.add_argument("--node", default="fan_02")
    ap.add_argument("--scenario", default="imbalance")
    ap.add_argument("--voice", default="audio/voice_note_hi.mp3")
    ap.add_argument("--language", default="Hindi")
    a = ap.parse_args()
    B, p = a.backend, PRESETS[a.node]

    print("1) baseline")
    with open(A / p["baseline_img"], "rb") as fi, open(A / p["baseline_wav"], "rb") as fa:
        requests.post(f"{B}/api/machines/{a.node}/baseline", files={"image": fi, "audio": fa}).raise_for_status()

    print("2) inject fault and wait for Tier-1 alert")
    requests.put(f"{B}/api/sim/{a.node}", json={"scenario": a.scenario, "severity": 0.8, "ramp_seconds": 6})
    case_id = None
    for _ in range(60):
        cs = requests.get(f"{B}/api/cases", params={"open": True, "node_id": a.node}).json()
        if cs:
            case_id = cs[0]["id"]
            break
        time.sleep(1)
    if not case_id:
        sys.exit("no alert case opened - is the simulator running?")
    print("   case", case_id, cs[0]["reason"])

    print("3) evidence")
    files = [("images", open(A / p["img"], "rb")), ("audio", open(A / p["wav"], "rb"))]
    if a.voice:
        files.append(("voice_note", open(A / a.voice, "rb")))
    r = requests.post(f"{B}/api/cases/{case_id}/evidence", files=files,
                      data={"roi": p["roi"], "roi_question": p["q"], "language": a.language,
                            "notes": "Checked after the alert. Fan running."})
    r.raise_for_status()

    print("4) diagnose")
    requests.post(f"{B}/api/cases/{case_id}/diagnose").raise_for_status()
    seen, t0 = 0, time.time()
    while True:
        c = requests.get(f"{B}/api/cases/{case_id}").json()
        for ev in c["trace"][seen:]:
            dur = f" ({ev['duration_s']} s)" if ev.get("duration_s") else ""
            print(f"   [{ev['agent']:>15} | {ev['kind']:<8}]{dur} {ev['content'][:400]}")
        seen = len(c["trace"])
        if not c["running"] and c["status"] in ("DIAGNOSED", "ERROR"):
            break
        if time.time() - t0 > 900:
            sys.exit("timeout")
        time.sleep(2)
    print("STATUS", c["status"], "in", round(time.time() - t0), "s")
    if c["status"] == "DIAGNOSED":
        d = c["diagnosis"]
        print("DIAGNOSIS:", d["severity"], d["fault"], "|", d["component"], "| conf", d["confidence"])
        print("WORK ORDER:", c["work_order"]["title"], c["work_order"]["priority"], c["work_order"].get("whatsapp_link", "")[:80])
        print("OPERATOR (local):", c["report"]["operator_message_local"])
        pdf = requests.get(f"{B}/api/cases/{case_id}/ticket.pdf")
        out = ROOT / "data" / f"ticket_{case_id}.pdf"
        out.write_bytes(pdf.content)
        print("5) ticket saved:", out, len(pdf.content), "bytes")
    requests.put(f"{B}/api/sim/{a.node}", json={"scenario": "normal", "severity": 0})


if __name__ == "__main__":
    main()
