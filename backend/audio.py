"""Audio handling for machine sounds and voice notes.

Gemma 4 E4B hears the clip natively. In addition we compute a few classic
acoustic-condition-monitoring features (impulsiveness, envelope modulation,
band energies, spectral distance from the healthy baseline). These numbers are
given to Gemma as extra evidence, which makes the audio reasoning far more
reliable than listening alone, and they are the fallback if native audio fails.
"""
from __future__ import annotations

import io
from typing import Optional

import numpy as np
import soundfile as sf
from PIL import Image, ImageDraw
from scipy.signal import butter, hilbert, resample_poly, sosfiltfilt, stft
from scipy.stats import kurtosis

SR = 16000
MAX_SECONDS = 10.0


def load(data: bytes, max_seconds: float = MAX_SECONDS) -> np.ndarray:
    """Decode WAV/FLAC/OGG/MP3 bytes to mono float32 at 16 kHz (machine clips max 10 s)."""
    x, sr = sf.read(io.BytesIO(data), dtype="float32", always_2d=True)
    x = x.mean(axis=1)
    if sr != SR:
        g = np.gcd(int(sr), SR)
        x = resample_poly(x, SR // g, int(sr) // g).astype(np.float32)
    n = int(max_seconds * SR)
    if len(x) > n:  # keep the loudest 10 s window (the machine, not the silence before)
        hop = SR // 2
        energies = [np.sum(x[i:i + n] ** 2) for i in range(0, len(x) - n + 1, hop)]
        i = int(np.argmax(energies)) * hop
        x = x[i:i + n]
    return x


def to_wav(x: np.ndarray) -> bytes:
    peak = float(np.max(np.abs(x))) or 1.0
    buf = io.BytesIO()
    sf.write(buf, (x / peak * 0.9).astype(np.float32), SR, format="WAV", subtype="PCM_16")
    return buf.getvalue()


BANDS = [(20, 250), (250, 1000), (1000, 3000), (3000, 6000), (6000, 8000)]
BAND_NAMES = ["20-250 Hz (rumble/1x)", "250-1k Hz (hum/harmonics)", "1-3 kHz (rattle/whine)",
              "3-6 kHz (squeal/bearing)", "6-8 kHz (hiss/friction)"]


def _spectrum(x: np.ndarray):
    f, _, Z = stft(x, fs=SR, nperseg=2048, noverlap=1024)
    p = np.mean(np.abs(Z) ** 2, axis=1)
    return f, p


def features(x: np.ndarray) -> dict:
    if len(x) < SR // 4:
        return {"error": "clip too short"}
    rms = float(np.sqrt(np.mean(x ** 2)) + 1e-12)
    f, p = _spectrum(x)
    ptot = float(p.sum()) + 1e-20
    centroid = float((f * p).sum() / ptot)
    cum = np.cumsum(p) / ptot
    rolloff = float(f[np.searchsorted(cum, 0.85)])
    flatness = float(np.exp(np.mean(np.log(p + 1e-20))) / (np.mean(p) + 1e-20))
    bands = []
    for lo, hi in BANDS:
        m = (f >= lo) & (f < hi)
        bands.append(float(p[m].sum() / ptot))
    # tonal peaks
    idx = np.argsort(p[5:])[::-1][:40] + 5
    peaks = []
    for i in sorted(idx, key=lambda k: -p[k]):
        if all(abs(f[i] - q) > 30 for q in peaks):
            peaks.append(float(f[i]))
        if len(peaks) == 5:
            break
    # impulsiveness + envelope modulation (classic bearing/looseness detection)
    sos = butter(4, [2000, 7000], btype="band", fs=SR, output="sos")
    hb = sosfiltfilt(sos, x)
    env = np.abs(hilbert(hb))
    env = env - env.mean()
    ef = np.fft.rfftfreq(len(env), 1 / SR)
    es = np.abs(np.fft.rfft(env * np.hanning(len(env))))
    m = (ef > 3) & (ef < 400)
    env_peak_hz = float(ef[m][np.argmax(es[m])]) if m.any() else 0.0
    env_prom = float(es[m].max() / (np.median(es[m]) + 1e-12)) if m.any() else 0.0
    return {
        "duration_s": round(len(x) / SR, 1),
        "rms_dbfs": round(20 * np.log10(rms), 1),
        "crest_factor": round(float(np.max(np.abs(x)) / rms), 2),
        "kurtosis": round(float(kurtosis(x, fisher=False)), 2),
        "highband_kurtosis": round(float(kurtosis(hb, fisher=False)), 2),
        "spectral_centroid_hz": round(centroid),
        "rolloff85_hz": round(rolloff),
        "spectral_flatness": round(flatness, 3),
        "band_energy_pct": {n: round(100 * b, 1) for n, b in zip(BAND_NAMES, bands)},
        "tonal_peaks_hz": [round(v) for v in peaks],
        "envelope_mod_hz": round(env_peak_hz, 1),
        "envelope_mod_prominence": round(env_prom, 1),
        "_logspec": np.log10(p + 1e-12).tolist(),
    }


def compare(base: dict, cur: dict) -> dict:
    """Quantify how far the current sound has drifted from the healthy baseline."""
    a, b = np.array(base["_logspec"]), np.array(cur["_logspec"])
    n = min(len(a), len(b))
    a, b = a[:n] - a[:n].mean(), b[:n] - b[:n].mean()
    cos = float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-12))
    novelty = float(np.clip((1 - cos) * 4, 0, 1))
    band_shift = {k: round(cur["band_energy_pct"][k] - base["band_energy_pct"][k], 1)
                  for k in cur["band_energy_pct"]}
    return {
        "spectral_similarity": round(cos, 3),
        "novelty_score": round(novelty, 2),
        "loudness_change_db": round(cur["rms_dbfs"] - base["rms_dbfs"], 1),
        "kurtosis_change": round(cur["highband_kurtosis"] - base["highband_kurtosis"], 2),
        "centroid_shift_hz": cur["spectral_centroid_hz"] - base["spectral_centroid_hz"],
        "band_shift_pct_points": band_shift,
        "verdict": ("very different from healthy baseline" if novelty > 0.6 else
                    "noticeably different from baseline" if novelty > 0.3 else "close to healthy baseline"),
    }


def public(feat: dict) -> dict:
    return {k: v for k, v in feat.items() if not k.startswith("_")}


def interpret(feat: dict, rpm: Optional[float]) -> list[str]:
    """Plain rules that turn numbers into hints for the model and the UI."""
    hints = []
    if feat.get("highband_kurtosis", 0) > 6:
        hints.append("High-frequency band is impulsive (kurtosis > 6): typical of bearing defects, "
                     "rubbing or loose parts striking.")
    bp = feat.get("band_energy_pct", {})
    if bp.get(BAND_NAMES[3], 0) + bp.get(BAND_NAMES[4], 0) > 25:
        hints.append("Strong energy above 3 kHz: squeal/friction (dry bearing, belt slip, cavitation hiss).")
    if rpm and feat.get("envelope_mod_prominence", 0) > 6:
        order = feat["envelope_mod_hz"] / (rpm / 60)
        hints.append(f"Sound is amplitude-modulated at {feat['envelope_mod_hz']} Hz (~{order:.1f}x running speed): "
                     "periodic knocking/thumping linked to rotation.")
    if feat.get("spectral_flatness", 0) > 0.3:
        hints.append("Broadband, noise-like spectrum: turbulence, cavitation or general wear.")
    return hints


def _colormap(v: np.ndarray) -> np.ndarray:
    """Small inferno-like colormap without matplotlib."""
    stops = np.array([[0, 0, 4], [40, 11, 84], [101, 21, 110], [159, 42, 99], [212, 72, 66],
                      [245, 125, 21], [250, 193, 39], [252, 255, 164]], dtype=float)
    pos = v * (len(stops) - 1)
    i = np.clip(pos.astype(int), 0, len(stops) - 2)
    t = (pos - i)[..., None]
    return (stops[i] * (1 - t) + stops[i + 1] * t).astype(np.uint8)


def spectrogram_png(clips: list[tuple[str, np.ndarray]], width=896) -> bytes:
    """Stacked spectrogram panels (e.g. baseline vs current), labelled, as PNG."""
    panels = []
    for label, x in clips:
        f, t, Z = stft(x, fs=SR, nperseg=512, noverlap=384)
        S = 20 * np.log10(np.abs(Z) + 1e-9)
        S = np.clip((S - (S.max() - 80)) / 80, 0, 1)[::-1]
        img = Image.fromarray(_colormap(S)).resize((width, 256))
        d = ImageDraw.Draw(img)
        d.rectangle([0, 0, 360, 18], fill=(0, 0, 0))
        d.text((4, 3), f"{label}  (0-8 kHz, 10 s)", fill=(255, 255, 255))
        for khz in (2, 4, 6):
            y = int(256 * (1 - khz / 8))
            d.line([(width - 30, y), (width, y)], fill=(255, 255, 255))
            d.text((width - 28, y + 2), f"{khz}k", fill=(255, 255, 255))
        panels.append(img)
    out = Image.new("RGB", (width, 256 * len(panels) + 4 * (len(panels) - 1)), (255, 255, 255))
    for i, p in enumerate(panels):
        out.paste(p, (0, i * 260))
    buf = io.BytesIO()
    out.save(buf, format="PNG")
    return buf.getvalue()
