"""Deterministic analysis of edge telemetry: order analysis of FFT peaks,
health score, trend / remaining-useful-life estimate and a compact text summary
for the Signal Analyst agent."""
from __future__ import annotations

import re

from datetime import datetime
from typing import Optional

import numpy as np

from .models import MachineProfile


def running_hz(t: dict, m: MachineProfile) -> Optional[float]:
    rpm = t.get("rpm_hint") or m.rated_rpm
    return rpm / 60.0 if rpm else None


def order_hints(t: dict, m: MachineProfile) -> list[str]:
    """Map FFT peaks to multiples of running speed and to classic fault signatures."""
    f1 = running_hz(t, m)
    peaks = (t.get("vib") or {}).get("fft_peaks") or []
    hints = []
    if not f1 or not peaks:
        return hints
    orders = []
    for p in peaks:
        o = p["hz"] / f1
        orders.append((o, p["amp"], p["hz"]))
    top = max(orders, key=lambda q: q[1])
    harmonics = sorted({round(o) for o, a, _ in orders if abs(o - round(o)) < 0.12 and round(o) >= 1})

    def amp_at(n):
        return max([a for o, a, _ in orders if abs(o - n) < 0.12] or [0])

    a1, a2 = amp_at(1), amp_at(2)
    amps = [a for _, a, _ in orders]
    # Broadband = flat spectrum whose peaks (ignoring the ever-present 1x) mostly fall OFF the
    # running-speed harmonics. Looseness is also "many peaks" but they sit on integer orders.
    rest = [o for o, _, _ in orders if abs(o - 1) > 0.12]
    harmonicity = (sum(1 for o in rest if abs(o - round(o)) < 0.12 and round(o) >= 2) / len(rest)) if rest else 1.0
    broadband = len(amps) >= 4 and max(amps) / max(min(amps), 1e-9) < 2.5 and harmonicity < 0.5
    if broadband:
        hints.append(f"Running speed 1x = {f1:.1f} Hz. No dominant peak: the tallest bin ({top[2]:.1f} Hz) is "
                     f"only {max(amps) / min(amps):.1f}x the smallest of the top {len(amps)} peaks.")
    else:
        hints.append(f"Running speed 1x = {f1:.1f} Hz. Dominant peak {top[2]:.1f} Hz = {top[0]:.2f}x.")
    v = t.get("vib") or {}
    rms = v.get("rms_g") or {}
    if v.get("baseline_rms") and rms:
        ratio = float(np.sqrt(sum(x * x for x in rms.values()))) / v["baseline_rms"]
        if ratio < 1.5:
            hints.append("Overall vibration is within the normal band of the learned baseline; "
                         "spectral shape alone is not evidence of a fault.")
            return hints
    # A flat spectrum (many peaks of similar height) is random/broadband energy: order-based
    # rules would just pick whichever random bin is tallest, so they are skipped.
    if broadband:
        hints.append("Broadband, random vibration: many peaks of similar height with no dominant order. "
                     + ("Typical of pump CAVITATION / flow turbulence (check suction pressure, strainer, tank level)."
                        if m.machine_type == "pump" else "Typical of rubbing, turbulence or general looseness."))
    else:
        strong_harm = [h for h in harmonics if h >= 2 and amp_at(h) > 0.3 * max(a1, 1e-9)]
        if len(strong_harm) >= 3:
            hints.append(f"Series of harmonics {harmonics}x: signature of mechanical LOOSENESS (or rub).")
        elif a2 >= 0.5 * max(a1, 1e-9):
            hints.append("Strong 2x relative to 1x: signature of MISALIGNMENT (check axial vibration) or bent shaft.")
        elif a1 > 0 and a1 >= 0.6 * top[1] and len(strong_harm) <= 1:
            hints.append("Dominant 1x with little 2x: classic signature of IMBALANCE.")
        sub = [o for o, a, _ in orders if 0.35 < o < 0.65 and a > 0.2 * top[1]]
        if sub:
            hints.append("Sub-synchronous ~0.5x component: looseness/rub or oil whirl.")
        nonint = [hz for o, a, hz in orders if o > 3.2 and abs(o - round(o)) > 0.15 and a > 0.15 * top[1]]
        if nonint:
            hints.append(f"Non-integer high-order peaks {[round(h, 1) for h in nonint]} Hz: "
                         "possible BEARING defect frequencies.")
    line = m.line_hz or 50
    if any(abs(hz - 2 * line) < 1.5 for _, _, hz in orders):
        hints.append(f"Peak at 2x line frequency ({2 * line:.0f} Hz): ELECTRICAL issue (stator / soft foot / unbalanced supply).")
    rms = (t.get("vib") or {}).get("rms_g") or {}
    if rms:
        radial = max(rms.get("x", 0), rms.get("y", 0))
        if rms.get("z", 0) > 0 and radial > 0 and rms["z"] / radial > 0.8 and a2 > 0.3 * a1:
            hints.append("Axial (Z) vibration comparable to radial: supports MISALIGNMENT.")
    return hints


def _family(h: str) -> str:
    """Hint 'type' with the numbers stripped, so the same rule firing in different windows votes together."""
    return re.sub(r"[-+]?[\d.]+", "#", re.sub(r"\[.*?\]", "[]", h).split(":")[0])[:60]


def window_hints(series: list[dict], m: MachineProfile, n: int = 5) -> list[str]:
    """Persistence vote: a rule hint is reported only if the same rule fired in >= 2 of the last n
    readings (single 1-second windows are noisy). Each hint is annotated with its vote count."""
    recent = [r for r in series[-n:] if r.get("status") != "LEARNING"]
    if not recent:
        return []
    per = [order_hints(r, m) for r in recent]
    bb = [hs for hs in per if any("Broadband" in h for h in hs)]
    head_src = bb[-1] if len(bb) >= 2 else per[-1]
    out = [head_src[0]] if head_src else []
    latest: dict[str, str] = {}
    votes: dict[str, int] = {}
    for hs in per:
        for fam in {_family(h) for h in hs[1:]}:
            votes[fam] = votes.get(fam, 0) + 1
        for h in hs[1:]:
            latest[_family(h)] = h
    need = min(2, len(recent))
    for fam, v in votes.items():
        if v >= need and fam != _family(out[0] if out else ""):
            out.append(f"{latest[fam]} [seen in {v}/{len(recent)} recent windows]")
    return out


FAULT_WORDS = {"IMBALANCE": ["imbalance", "unbalance"], "MISALIGNMENT": ["misalign"], "LOOSENESS": ["loose"],
               "BEARING": ["bearing"], "ELECTRICAL": ["electric", "stator", "rotor bar", "winding", "supply"],
               "CAVITATION": ["cavitation", "turbulen", "flow", "suction"]}


def persistent_signatures(series: list[dict], m: MachineProfile, n: int = 5, min_votes: int = 3) -> dict:
    """Fault signatures seen in at least `min_votes` of the last n readings -> {key: votes}."""
    recent = [r for r in series[-n:] if r.get("status") != "LEARNING"]
    per = [" ".join(order_hints(r, m)) for r in recent]
    out = {}
    for key in FAULT_WORDS:
        votes = sum(1 for h in per if key in h)
        if votes >= min_votes:
            out[key] = votes
    return out


def guide_severity(t: dict) -> Optional[str]:
    """Severity suggested by the fault-signature guide from baseline ratio and temperature rise."""
    v = t.get("vib") or {}
    rms = v.get("rms_g") or {}
    base = v.get("baseline_rms")
    sev = None
    if base and rms:
        ratio = float(np.sqrt(sum(x * x for x in rms.values()))) / base
        sev = "HIGH" if ratio > 4 else "MEDIUM" if ratio > 2 else "LOW"
    if t.get("flame"):
        return "CRITICAL"
    if t.get("temp_c") is not None and t.get("temp_baseline_c") is not None:
        dT = t["temp_c"] - t["temp_baseline_c"]
        if dT > 25:
            sev = "CRITICAL"
        elif dT > 15 and sev in (None, "LOW", "MEDIUM"):
            sev = "HIGH"
    return sev


def other_hints(t: dict) -> list[str]:
    h = []
    if t.get("flame"):
        h.append("FLAME DETECTED by the IR flame sensor next to the machine: fire / burning insulation / "
                 "overheated bearing or belt. Treat as CRITICAL - stop and isolate the machine now.")
    elif (t.get("flame_level") or 0) > 40:
        h.append(f"IR flame sensor reads {t['flame_level']:.0f}/100 without tripping: strong heat/IR source nearby.")
    hum = t.get("humidity_pct")
    if hum is not None and hum > 85:
        h.append(f"Relative humidity {hum:.0f}% (>85%): condensation risk - winding insulation failure, "
                 "corrosion of bearings/terminals, electrical tracking.")
    if t.get("sound_event"):
        h.append("Sound sensor tripped its loudness threshold: sudden bang, squeal or knocking.")
    v = t.get("vib") or {}
    rms = v.get("rms_g") or {}
    if v.get("baseline_rms") and rms:
        ratio = float(np.sqrt(sum(x * x for x in rms.values()))) / v["baseline_rms"]
        h.append(f"Combined vibration is {ratio:.1f}x the learned baseline -> severity guide suggests "
                 f"{guide_severity(t)}.")
    if v.get("crest") and v["crest"] > 5:
        h.append(f"Crest factor {v['crest']:.1f} (>5): impacting, typical of bearing damage or looseness.")
    if v.get("kurtosis") and v["kurtosis"] > 5:
        h.append(f"Vibration kurtosis {v['kurtosis']:.1f} (>5): impulsive signal, early bearing damage.")
    if t.get("temp_c") is not None and t.get("temp_baseline_c") is not None:
        d = t["temp_c"] - t["temp_baseline_c"]
        if d > 10:
            h.append(f"Temperature near the machine +{d:.1f} °C over baseline: friction (bearing/lubrication), overload or cooling problem.")
    if t.get("current_a") and t.get("current_baseline_a"):
        r = t["current_a"] / t["current_baseline_a"]
        if r > 1.15:
            h.append(f"Motor current {100 * (r - 1):.0f}% above baseline: mechanical overload, friction or electrical fault.")
        if r < 0.8:
            h.append(f"Motor current {100 * (1 - r):.0f}% below baseline: load loss (belt slip, broken coupling, pump running dry).")
    if t.get("sound_level") and t.get("sound_baseline"):
        r = t["sound_level"] / max(t["sound_baseline"], 1e-9)
        if r > 1.3:
            h.append(f"Sound level {100 * (r - 1):.0f}% above baseline.")
    return h


def health_score(t: Optional[dict]) -> int:
    """0-100 machine health from the latest edge reading."""
    if not t:
        return 100
    if t.get("flame"):
        return 0
    s = 100.0
    if t.get("humidity_pct") is not None:
        s -= min(8, max(0, t["humidity_pct"] - 85) * 0.8)
    v = t.get("vib") or {}
    z = v.get("zscore") or 0
    s -= min(55, max(0, z - 1.5) * 7)
    if v.get("crest"):
        s -= min(10, max(0, v["crest"] - 4) * 3)
    if t.get("temp_c") is not None and t.get("temp_baseline_c") is not None:
        s -= min(25, max(0, t["temp_c"] - t["temp_baseline_c"] - 4) * 1.6)
    if t.get("current_a") and t.get("current_baseline_a"):
        s -= min(15, abs(t["current_a"] / t["current_baseline_a"] - 1) * 60)
    if t.get("sound_level") and t.get("sound_baseline"):
        s -= min(10, max(0, t["sound_level"] / max(t["sound_baseline"], 1e-9) - 1.2) * 15)
    return int(max(0, min(100, round(s))))


def rul_estimate(series: list[dict], threshold: int = 40) -> dict:
    """Fit a line to the recent health score and extrapolate when it will cross
    the 'must repair' threshold. Simple, explainable and honest about confidence."""
    if len(series) < 15:
        return {"status": "insufficient_data"}
    ts = np.array([datetime.fromisoformat(r["ts"]).timestamp() for r in series])
    hs = np.array([health_score(r) for r in series], dtype=float)
    ts = ts - ts[0]
    slope, icpt = np.polyfit(ts, hs, 1)
    cur = float(hs[-5:].mean())
    if cur <= threshold:
        return {"status": "below_threshold", "health_now": round(cur), "slope_per_hour": round(slope * 3600, 1)}
    if slope >= -1e-4:
        return {"status": "stable", "health_now": round(cur), "slope_per_hour": round(slope * 3600, 1)}
    secs = (threshold - cur) / slope
    r2 = float(np.corrcoef(ts, hs)[0, 1] ** 2) if hs.std() > 0 else 0.0
    return {"status": "degrading", "health_now": round(cur), "slope_per_hour": round(slope * 3600, 1),
            "hours_to_threshold": round(secs / 3600, 2), "fit_r2": round(r2, 2),
            "note": "Linear extrapolation of the last readings; confidence follows fit_r2."}


def summarize(series: list[dict], latest: Optional[dict], m: MachineProfile) -> str:
    """Compact, number-rich text summary of the last minutes of telemetry."""
    if not latest:
        return "No telemetry available."
    lines = [f"Machine: {m.name} ({m.machine_type}), rated {m.rated_rpm or '?'} rpm, "
             f"{m.power_kw or '?'} kW, line {m.line_hz} Hz, location: {m.location or 'n/a'}."]
    v = latest.get("vib", {})
    r = v.get("rms_g", {})
    lines.append(f"Latest edge status: {latest.get('status')} ({latest.get('reason') or 'no reason given'}).")
    lines.append(f"Vibration RMS g: x={r.get('x', 0):.3f} y={r.get('y', 0):.3f} z(axial)={r.get('z', 0):.3f}; "
                 f"peak {v.get('peak_g', 0):.2f} g; crest {v.get('crest', 0):.2f}; kurtosis {v.get('kurtosis')}; "
                 f"baseline RMS {v.get('baseline_rms')}; z-score {v.get('zscore')}.")
    if v.get("fft_peaks"):
        lines.append("FFT peaks (Hz:amp g): " + ", ".join(f"{p['hz']:.1f}:{p['amp']:.3f}" for p in v["fft_peaks"]))
    lines.append(f"Temperature {latest.get('temp_c')} °C (baseline {latest.get('temp_baseline_c')}); "
                 f"sound-level index {latest.get('sound_level')} (raw microphone ADC units, not dB; "
                 f"baseline {latest.get('sound_baseline')}); "
                 f"current {latest.get('current_a')} A (baseline {latest.get('current_baseline_a')}); "
                 f"humidity {latest.get('humidity_pct')} %RH; moisture {latest.get('moisture_pct')} %; flame sensor {'TRIPPED' if latest.get('flame') else 'clear'} "
                 f"(IR level {latest.get('flame_level')}); sound threshold {'tripped' if latest.get('sound_event') else 'not tripped'}.")
    if series:
        z = [s.get("vib", {}).get("zscore") or 0 for s in series]
        temps = [s.get("temp_c") for s in series if s.get("temp_c") is not None]
        n_alert = sum(1 for s in series if s.get("status") == "ALERT")
        lines.append(f"Window: {len(series)} readings; z-score min/mean/max {min(z):.1f}/{np.mean(z):.1f}/{max(z):.1f}; "
                     f"{n_alert} ALERT readings.")
        if len(temps) > 3:
            lines.append(f"Temperature went {temps[0]:.1f} -> {temps[-1]:.1f} °C over the window.")
    return "\n".join(lines)
