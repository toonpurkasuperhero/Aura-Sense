"""Mock ESP32 sentinel nodes.

Synthesises tri-axial accelerometer data at 1 kHz with physically motivated fault
signatures, then runs exactly the same edge pipeline as the firmware
(RMS, peak, crest, kurtosis, FFT top peaks, baseline learning, z-score alerts) and
POSTs the JSON to the backend every 2 s. The scenario for each node is read from
the backend (/api/sim/<node>), so the dashboard's "Inject fault" buttons drive it.

Usage:
    python simulator/mock_esp32.py                       # all demo nodes
    python simulator/mock_esp32.py --nodes motor_01 --scenario motor_01=imbalance:0.8
"""
from __future__ import annotations

import argparse
import math
import random
import threading
import time
from datetime import datetime, timezone

import numpy as np
import requests

FS = 1000          # MPU6050 practical sample rate on ESP32
N = 1024           # samples per window (~1 s)
ABS_ALERT_G = 0.3  # combined RMS limit that always alerts, whatever the learned baseline
SCENARIOS = ["normal", "imbalance", "misalignment", "looseness", "bearing", "electrical", "overheat",
             "cavitation", "belt_slip", "fire", "humid"]

NODES = {
    "motor_01": {"rpm": 1440, "temp_amb": 34.0, "temp_run": 46.0, "current": 7.2, "sound": 310},
    "fan_02": {"rpm": 960, "temp_amb": 33.0, "temp_run": 41.0, "current": 4.6, "sound": 380},
    "pump_03": {"rpm": 2900, "temp_amb": 32.0, "temp_run": 44.0, "current": 3.3, "sound": 420},
}


class Node:
    def __init__(self, node_id: str, cfg: dict, backend: str, learn_windows: int, local: str | None):
        self.id, self.cfg, self.backend = node_id, cfg, backend
        self.f1 = cfg["rpm"] / 60.0
        self.temp = cfg["temp_run"]
        self.hum = 55.0
        self.learn = learn_windows
        self.base_vals: list[float] = []
        self.base_temp: list[float] = []
        self.base_sound: list[float] = []
        self.base_cur: list[float] = []
        self.base = None
        self.over = 0
        self.local = local  # "scenario:severity" override from CLI
        self.t = 0.0
        self.rng = np.random.default_rng(abs(hash(node_id)) % 2**32)

    # -------------------------------------------------------------- scenario
    def scenario(self) -> tuple[str, float]:
        if self.local:
            s, _, v = self.local.partition(":")
            return s, float(v or 0.8)
        try:
            d = requests.get(f"{self.backend}/api/sim/{self.id}", timeout=2).json()
        except requests.RequestException:
            return "normal", 0.0
        sev = float(d.get("severity", 0))
        ramp = float(d.get("ramp_seconds") or 0)
        if ramp > 0 and d.get("since"):
            el = (datetime.now(timezone.utc) - datetime.fromisoformat(d["since"])).total_seconds()
            sev *= min(1.0, max(0.0, el / ramp))
        return d.get("scenario", "normal"), sev

    # -------------------------------------------------------------- physics-ish synthesis
    def synth(self, scen: str, s: float) -> tuple[np.ndarray, float, float, float]:
        t = self.t + np.arange(N) / FS
        self.t += N / FS
        f1 = self.f1 * (1 - 0.02 * s if scen == "belt_slip" else 1)
        w = 2 * np.pi * f1
        rnd = self.rng.normal
        x = 0.030 * np.sin(w * t) + 0.010 * rnd(size=N)
        y = 0.028 * np.sin(w * t + 1.2) + 0.010 * rnd(size=N)
        z = 0.015 * np.sin(w * t + 0.4) + 0.008 * rnd(size=N)
        cur_k, temp_k, sound_k, hum_target, flame = 1.0, 0.0, 1.0, 55.0, False
        if scen == "imbalance":
            a = 0.55 * s
            x += a * np.sin(w * t); y += a * np.sin(w * t + np.pi / 2); z += 0.08 * a * np.sin(w * t)
            sound_k += 0.4 * s; temp_k += 3 * s
        elif scen == "misalignment":
            x += 0.15 * s * np.sin(w * t) + 0.35 * s * np.sin(2 * w * t + 0.3)
            y += 0.12 * s * np.sin(w * t + 1) + 0.30 * s * np.sin(2 * w * t + 1.1)
            z += 0.35 * s * np.sin(w * t) + 0.30 * s * np.sin(2 * w * t)
            temp_k += 8 * s; cur_k += 0.06 * s; sound_k += 0.3 * s
        elif scen == "looseness":
            for k in range(1, 7):
                ph = self.rng.uniform(0, 2 * np.pi)
                x += 0.14 * s / k ** 0.4 * np.sin(k * w * t + ph)
                y += 0.10 * s / k ** 0.4 * np.sin(k * w * t + ph + 0.5)
            x += 0.08 * s * np.sin(0.5 * w * t)
            imp = (np.sin(w * t) > 0.995).astype(float) * 0.6 * s
            x += imp; y += 0.5 * imp
            sound_k += 0.6 * s
        elif scen == "bearing":
            bpfo = 3.58 * f1  # 6205-type outer race defect frequency
            period = int(FS / bpfo)
            ring = np.exp(-np.arange(40) / 6.0) * np.sin(2 * np.pi * 330 * np.arange(40) / FS)
            imp = np.zeros(N)
            start = self.rng.integers(0, period)
            imp[start::period] = 1.0
            burst = np.convolve(imp, ring)[:N] * 1.4 * s
            x += burst; y += 0.8 * burst; z += 0.3 * burst
            x += 0.05 * s * rnd(size=N)
            temp_k += 18 * s; sound_k += 0.9 * s; cur_k += 0.05 * s
        elif scen == "electrical":
            e = 2 * np.pi * 100 * t
            x += 0.25 * s * np.sin(e); y += 0.25 * s * np.sin(e + 2)
            temp_k += 14 * s; cur_k += 0.22 * s; sound_k += 0.25 * s
        elif scen == "overheat":
            temp_k += 28 * s; cur_k += 0.08 * s
        elif scen == "cavitation":
            x += 0.18 * s * rnd(size=N); y += 0.15 * s * rnd(size=N); z += 0.1 * s * rnd(size=N)
            sound_k += 1.0 * s; cur_k += 0.08 * s * math.sin(self.t)
        elif scen == "fire":
            temp_k += 30 * s; sound_k += 0.3 * s; flame = s >= 0.3
            x += 0.05 * s * rnd(size=N)
        elif scen == "humid":
            hum_target = 55 + 40 * s
        elif scen == "belt_slip":
            fb = f1 * 0.38
            x += 0.12 * s * np.sin(2 * np.pi * fb * t); y += 0.1 * s * np.sin(2 * np.pi * 2 * fb * t)
            cur_k -= 0.25 * s; sound_k += 0.5 * s; temp_k += 4 * s
        # first-order thermal response towards target
        target = self.cfg["temp_run"] + temp_k
        self.temp += (target - self.temp) * 0.08 + self.rng.normal(0, 0.05)
        current = self.cfg["current"] * cur_k * (1 + self.rng.normal(0, 0.01))
        sound = self.cfg["sound"] * sound_k * (1 + self.rng.normal(0, 0.03))
        self.hum += (hum_target - self.hum) * 0.15 + self.rng.normal(0, 0.3)
        self.flame = flame
        self.sound_event = sound_k > 1.5
        return np.vstack([x, y, z]), round(self.temp), sound, current  # DHT11: 1 °C resolution

    # -------------------------------------------------------------- edge feature pipeline (mirrors firmware)
    def features(self, acc: np.ndarray) -> dict:
        acc = acc - acc.mean(axis=1, keepdims=True)
        rms = np.sqrt((acc ** 2).mean(axis=1))
        mag = np.sqrt((acc ** 2).sum(axis=0))
        comb = float(np.sqrt((rms ** 2).sum()))
        peak = float(np.abs(acc).max())
        radial = acc[0]
        spec = np.abs(np.fft.rfft(radial * np.hanning(N))) * 2 / (N / 2)
        spec += np.abs(np.fft.rfft(acc[2] * np.hanning(N))) * 2 / (N / 2) * 0.5
        freqs = np.fft.rfftfreq(N, 1 / FS)
        spec[:3] = 0
        peaks = []
        for i in np.argsort(spec)[::-1]:
            if spec[i] < 0.01:
                break
            if all(abs(freqs[i] - p["hz"]) > 3 for p in peaks):
                peaks.append({"hz": round(float(freqs[i]), 1), "amp": round(float(spec[i]), 4)})
            if len(peaks) == 5:
                break
        k = float(((mag - mag.mean()) ** 4).mean() / (mag.var() ** 2 + 1e-12))
        return {"rms": rms, "comb": comb, "peak": peak, "crest": peak / (comb + 1e-9), "kurt": k, "peaks": peaks}

    def poll_command(self):
        try:
            cmd = requests.get(f"{self.backend}/api/nodes/{self.id}/command", timeout=2).json()
        except requests.RequestException:
            return
        if cmd.get("relearn"):
            print(f"[{self.id}] re-learning baseline")
            self.base, self.over = None, 0
            self.base_vals, self.base_temp, self.base_sound, self.base_cur = [], [], [], []

    def step(self) -> dict:
        self.poll_command()
        scen, sev = self.scenario()
        acc, temp, sound, current = self.synth(scen, sev)
        f = self.features(acc)
        status, reason, z = "OK", None, None
        if f["comb"] > ABS_ALERT_G:
            # Absolute guard: alert even if the baseline was learned on an already-faulty machine.
            status, reason = "ALERT", f"Vibration {f['comb']:.2f} g RMS exceeds absolute limit {ABS_ALERT_G} g"
        if self.base is None:
            self.base_vals.append(f["comb"]); self.base_temp.append(temp)
            self.base_sound.append(sound); self.base_cur.append(current)
            status = "LEARNING" if status != "ALERT" else status
            if len(self.base_vals) >= self.learn:
                m = float(np.mean(self.base_vals))
                self.base = {"rms": m, "std": max(float(np.std(self.base_vals)), 0.15 * m),
                             "temp": float(np.mean(self.base_temp)), "sound": float(np.mean(self.base_sound)),
                             "cur": float(np.mean(self.base_cur))}
        else:
            b = self.base
            z = (f["comb"] - b["rms"]) / b["std"]
            dT = temp - b["temp"]
            self.over = self.over + 1 if z > 3 else 0
            dom = f["peaks"][0] if f["peaks"] else None
            if self.over >= 3 or dT > 10:
                status = "ALERT"
                parts = []
                if self.over >= 3:
                    parts.append(f"Vibration {f['comb'] / b['rms']:.1f}x baseline RMS (z={z:.1f})")
                    if dom:
                        parts.append(f"dominant {dom['hz']} Hz ({dom['hz'] / self.f1:.2f}x)")
                if dT > 10:
                    parts.append(f"temperature +{dT:.1f} °C over baseline")
                reason = "; ".join(parts)
            elif status == "ALERT":
                pass
            elif self.hum > 85:
                status, reason = "WARN", f"Humidity {self.hum:.0f}% (condensation risk)"
            elif z > 2 or dT > 6:
                status, reason = "WARN", f"z={z:.1f}, dT={dT:+.1f} °C"
        if self.flame:
            status, reason = "ALERT", "FLAME DETECTED near machine" + (f"; {reason}" if reason else "")
        b = self.base or {}
        return {
            "node_id": self.id, "ts": datetime.now(timezone.utc).isoformat(), "status": status, "reason": reason,
            "vib": {"rms_g": {"x": round(float(f["rms"][0]), 4), "y": round(float(f["rms"][1]), 4),
                              "z": round(float(f["rms"][2]), 4)},
                    "peak_g": round(f["peak"], 3), "crest": round(f["crest"], 2), "kurtosis": round(f["kurt"], 2),
                    "fft_peaks": f["peaks"], "baseline_rms": round(b["rms"], 4) if b else None,
                    "zscore": round(z, 2) if z is not None else None},
            "temp_c": round(temp, 2), "temp_baseline_c": round(b["temp"], 2) if b else None,
            "sound_level": round(sound, 1), "sound_baseline": round(b["sound"], 1) if b else None,
            "humidity_pct": round(self.hum, 1), "flame": self.flame,
            "flame_level": round(min(100, 92 + self.rng.normal(0, 2)), 1) if self.flame else round(abs(self.rng.normal(4, 1.5)), 1),
            "sound_event": self.sound_event,
            "rpm_hint": self.cfg["rpm"], "fw": f"sim-1.1 ({scen}:{sev:.2f})",
        }


def run_node(node: Node, interval: float):
    while True:
        t0 = time.time()
        payload = node.step()
        try:
            r = requests.post(f"{node.backend}/api/telemetry", json=payload, timeout=5)
            j = r.json()
            if payload["status"] in ("WARN", "ALERT"):
                print(f"[{node.id}] {payload['status']} {payload['reason']} -> {j}")
        except requests.RequestException as e:
            print(f"[{node.id}] backend unreachable: {e}")
        time.sleep(max(0.0, interval - (time.time() - t0)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", default="http://127.0.0.1:8000")
    ap.add_argument("--nodes", nargs="*", default=list(NODES))
    ap.add_argument("--interval", type=float, default=2.0)
    ap.add_argument("--learn", type=int, default=15, help="windows used to learn the baseline")
    ap.add_argument("--scenario", nargs="*", default=[], help="node=scenario:severity overrides")
    a = ap.parse_args()
    over = dict(s.split("=", 1) for s in a.scenario)
    threads = []
    for nid in a.nodes:
        node = Node(nid, NODES.get(nid, NODES["motor_01"]), a.backend, a.learn, over.get(nid))
        th = threading.Thread(target=run_node, args=(node, a.interval), daemon=True)
        th.start()
        threads.append(th)
        time.sleep(random.uniform(0.1, 0.5))
    print(f"Simulating {a.nodes} -> {a.backend} (Ctrl+C to stop)")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
