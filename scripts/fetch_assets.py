"""Re-download the open demo assets (no logins needed).

  * MIMII industrial machine sounds (Zenodo, CC BY-SA 4.0) - only a few clips are
    pulled out of the multi-GB zips using HTTP range requests (remotezip).
  * Machine photos from Wikimedia Commons (licences recorded in CREDITS.md).
  * Public motor / pump service manuals (ABB Baldor MN408, WEG IOM, CSC pump IOM).
  * Sample technician voice notes (English / Hindi) generated with gTTS.

    pip install remotezip gTTS
    python scripts/fetch_assets.py
"""
from __future__ import annotations

import io
import json
import re
import urllib.parse
import urllib.request
from pathlib import Path

import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parent.parent
IMG, AUD = ROOT / "demo_assets/images", ROOT / "demo_assets/audio"
MAN = ROOT / "backend/knowledge/manuals"
UA = {"User-Agent": "AuraSenseHackathon/1.0"}

COMMONS = {
    "motor_belt_drive_dusty.jpg": ("File:Industrial Electric Motor and Drive Mechanism.jpg", 90),
    "fan_motor_rusted.jpg": ("File:Motore ventilatore centrifugo Sisme K48407 M00465.jpg", 0),
    "pump_housing_corroded.jpg": ("File:Clean pump.JPG", 0),
    "pump_centrifugal.jpg": ("File:Centrifugal pump.JPG", 0),
    "bearing_overheating_marks.jpg": ("File:Cologne Germany Overheating-marks-at-a-bearing-shell-01.jpg", 0),
    "bearing_damage.jpg": ("File:BEARING DAMAGE - NARA - 17500147.jpg", 0),
    "fan_burnt_short.jpg": ("File:Broken fan burned by circuit short.jpg", 0),
    "fan_damaged.jpg": ("File:Damaged basement fan.jpg", 0),
    "stator_windings.jpg": ("File:Stator windings.jpg", 0),
    "rusted_engine.jpg": ("File:Rusted engine - Crossness Pumping Station 2025-08-17.jpg", 0),
    "motor_3phase_healthy.jpg": ("File:Three Phase Induction Motor.jpg", 0),
    "exhaust_fan_healthy.jpg": ("File:Industrial Exhaust Fan.jpg", 0),
}
MANUALS = {
    "ABB_Baldor_MN408_AC_Induction_Motor_Manual.pdf": "https://www.baldor.com/api/products/ECP49354T-4/drawings/MN408",
    "WEG_50033244_Electric_Motor_IOM.pdf": "https://static.weg.net/medias/downloadcenter/ha6/h39/WEG-WMO-safe-area-50033244-manual-pt-en-es.pdf",
    "Centrifugal_Pump_CSC_IOM.pdf": "https://cdn.shopify.com/s/files/1/0018/9716/8963/files/CSC_IOM_Manual.pdf",
}


def get(url: str) -> bytes:
    return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=120).read()


def images():
    from PIL import Image
    IMG.mkdir(parents=True, exist_ok=True)
    rows = ["# Demo image credits (Wikimedia Commons)\n", "| File | Source | Author | License |", "|---|---|---|---|"]
    for out, (title, rot) in COMMONS.items():
        q = urllib.parse.urlencode({"action": "query", "titles": title, "prop": "imageinfo",
                                    "iiprop": "url|extmetadata", "iiurlwidth": 1024, "format": "json"})
        d = json.loads(get("https://commons.wikimedia.org/w/api.php?" + q))
        ii = next(iter(d["query"]["pages"].values()))["imageinfo"][0]
        data = get(ii.get("thumburl") or ii["url"])
        im = Image.open(io.BytesIO(data)).convert("RGB")
        if rot:
            im = im.rotate(rot, expand=True)
        im.save(IMG / out, quality=90)
        m = ii["extmetadata"]
        artist = re.sub("<[^>]+>", "", m.get("Artist", {}).get("value", "unknown")).strip()
        rows.append(f"| {out} | {ii['descriptionurl']} | {artist} | {m.get('LicenseShortName', {}).get('value')} |")
        print("image", out)
    (IMG / "CREDITS.md").write_text("\n".join(rows) + "\n")


def sounds():
    from remotezip import RemoteZip
    from scipy.signal import resample_poly
    AUD.mkdir(parents=True, exist_ok=True)
    for machine in ("fan", "pump"):
        url = f"https://zenodo.org/api/records/3384388/files/6_dB_{machine}.zip/content"
        with RemoteZip(url) as z:
            for cls in ("normal", "abnormal"):
                for i in (0, 1):
                    name = f"{machine}/id_00/{cls}/0000000{i}.wav"
                    x, sr = sf.read(io.BytesIO(z.read(name)))
                    x = x[:, 0] if x.ndim > 1 else x
                    if sr != 16000:
                        x = resample_poly(x, 16000, sr)
                    x = x / (np.abs(x).max() + 1e-9) * 0.9
                    out = AUD / f"{machine}_{cls}_{i + 1}.wav"
                    sf.write(out, x.astype(np.float32), 16000, subtype="PCM_16")
                    print("sound", out.name)


def voice_notes():
    from gtts import gTTS
    gTTS("The exhaust fan started shaking a lot since this morning. It makes a rhythmic thumping sound every "
         "rotation, and the frame near the motor is vibrating. No burning smell.", lang="en", tld="co.in"
         ).save(AUD / "voice_note_en.mp3")
    gTTS("सुबह से पंखा बहुत ज़्यादा हिल रहा है। हर चक्कर में धप धप की आवाज़ आ रही है और मोटर के पास का फ्रेम काँप रहा है। "
         "जलने की कोई गंध नहीं है।", lang="hi", tld="co.in").save(AUD / "voice_note_hi.mp3")
    print("voice notes")


def manuals():
    MAN.mkdir(parents=True, exist_ok=True)
    for name, url in MANUALS.items():
        if not (MAN / name).exists():
            (MAN / name).write_bytes(get(url))
            print("manual", name)


if __name__ == "__main__":
    manuals()
    images()
    sounds()
    voice_notes()
