# AuraSense IoT — two-tier edge sensing + Gemma 4 multimodal machine diagnosis

**Hacktoberfest Hack Day Bengaluru 2026 · Track 1 (Best Use of Gemma 4) · G3 Multimodal + G1 Multi-Agent**

A low-cost ESP32 box clips onto any old machine and watches its vibration, temperature, sound and current 24/7.
When something drifts, it raises an alert. The technician then adds a photo, a 10 s sound clip and an optional
voice note in any language. A team of **Gemma 4 agents running locally** fuses all of it:

- what failed, where, how urgent, and why;
- a safety-audited repair plan, with citations to the real service manual;
- a work order with parts and cost;
- a WhatsApp message to the right repair centre;
- a shift log and a 5-Why root-cause analysis;
- a message for the operator in Hindi or Kannada.

No cloud is used, so there is no per-call cost and no data leaves the factory.

```
ESP32 sentinel ──HTTP JSON──► FastAPI backend ──► Agent team (all Gemma 4 E4B via Ollama) ──► Web control room (HTML/CSS/JS)
 MPU6050 FFT/RMS               alert state machine     Intake Clerk     (voice note: AUDIO)
 DS18B20 temp                  telemetry store         Signal Analyst   (telemetry + order analysis)
 MAX9814 sound                 evidence uploads        Diagnostician    (photos + ROI crop + baseline photo
 ACS712 current                manual index (BM25)                       + machine AUDIO + spectrogram + manuals)
 baseline + z-score alerts                             Safety Auditor ⇄ Diagnostician (critique → revise loop)
                                                       Logistics Coordinator (work order, parts, repair centre)
                                                       Reporter (shift log, 5-Why, local-language message)
```

## Quick start

```bash
cd aurasense
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
ollama pull gemma4:e4b             # ~10 GB; E4B = text + image + audio
./scripts/run_all.sh               # Ollama + backend/UI :8000 + simulator
# open http://localhost:8000  (phones on the same Wi-Fi: http://<laptop-ip>:8000)
./scripts/run_all.sh stop
```

On this machine, Ollama was installed without sudo into `~/.local/ollama`. `run_all.sh` finds it automatically.
Use `./scripts/run_all.sh --no-sim` once the real ESP32 is posting.

Headless end-to-end test (needs a running backend and simulator):
```bash
.venv/bin/python scripts/smoke_test.py --node fan_02 --scenario imbalance            # Hindi voice note
.venv/bin/python scripts/smoke_test.py --node motor_01 --scenario misalignment --voice audio/voice_note_en.mp3 --language Kannada
.venv/bin/python scripts/smoke_test.py --node pump_03 --scenario bearing --voice ""
```
Measured on an RTX 2000 Ada (16 GB), a full agent run takes about **45–62 s** (5–7 Gemma calls).

## Web control room
Served by the backend at `http://localhost:8000`. It is plain HTML/CSS/JavaScript with no build step, and Chart.js is
stored locally so it works without internet. It has a dark theme with a light toggle, and the layout adapts to phones
so the technician can capture evidence on site.

| Page | What it shows |
|---|---|
| Plant overview | KPIs, live machine cards (health gauge, vibration sparkline, alert reason), demo fault injection |
| Live machine | Vibration / FFT with 1×–6× order lines / temperature / current charts, edge-analytics hints, healthy baseline |
| Diagnose | ① Evidence: photos (camera, upload, demo), drag-to-mark region, in-browser WAV recording, voice note, language ② Agent room: live pipeline and agent conversation (critique → revision) ③ Diagnosis ④ Action: approve, WhatsApp/SMS, PDF ⑤ Report |
| Ask a photo | Mark any region on a photo and ask Gemma 4 |
| Work orders | Case history, AI accuracy from feedback, savings, CSV export |
| System | Engine status, manual search and upload, repair-centre directory |

Mic recording in the browser needs `localhost` or HTTPS. On a phone opened over the LAN IP, use **Upload**, which
lets the phone's recorder or camera app attach the file.

## Where Gemma 4 does the work

| Agent / feature | Gemma 4 input modalities | Output (JSON schema enforced) |
|---|---|---|
| Intake Clerk | **audio** (voice note, any language) | transcript, language, English translation, symptoms |
| Signal Analyst | text (telemetry, FFT orders, rule hints, history) | top-3 candidate faults, trend, what to photograph/record |
| **Diagnostician** | **image** (photo with ROI outlined, zoomed ROI crop, healthy baseline photo, spectrogram) + **audio** (machine sound) + text (telemetry, DSP features, manual excerpts, history) | fault, component, severity, confidence, evidence per modality, cross-modal reasoning, differential, repair steps, parts, manual citations |
| Safety Auditor | text | APPROVE / REVISE + issues, LOTO, PPE (plus hard rules in code) |
| Diagnostician (revision) | same as above + auditor objections | corrected diagnosis |
| Logistics Coordinator | text (+ ranked repair centres, price hints) | work order, priority, parts and cost, chosen centre, vendor WhatsApp message |
| Reporter | text | shift log, 5-Why, preventive actions, operator message in English + local script |
| Ask about a photo | **image** (full + ROI crop) | region description, defects, severity, answer |

**Trust features:**
- Every Gemma call is logged in the Agent Room with its token counts and attachments.
- Manual citations are checked against the pages that were actually retrieved, and the quote is verified on that page.
- Hard safety and consistency rules can force a revision.
- A human must approve before anything is dispatched.
- Technician feedback ("AI was wrong, actual cause was X") is stored and fed back into future prompts as lessons.

## Audio strategy
Gemma 4 E4B accepts audio natively. Ollama 0.40.x takes WAV as a base64 entry in the message's `images` list, and
this was verified with real clips. To make the audio reasoning more reliable, the backend also computes
acoustic-condition-monitoring features:
- high-band kurtosis;
- envelope (modulation) frequency;
- band energies;
- spectral distance from the healthy baseline recording;
- a baseline-vs-current spectrogram image.

If native audio ever fails (a known intermittent Ollama issue), the system falls back automatically to the
spectrogram plus these features. Voice notes can then use `faster-whisper` if it is installed. `AURA_AUDIO_MODE`
can be `auto`, `native` or `spectrogram`.

## Feature status (vs. IMPLEMENTATION_PLAN.md §2A)
| Area | Implemented | Not implemented (roadmap) |
|---|---|---|
| A. Sensing | A1–A9: RMS/peak/crest/kurtosis, on-device FFT + harmonics, DS18B20, MAX9814, optional current sensor, auto-baseline + z-score + absolute limit, LED/buzzer, offline buffer + replay, remote re-learn | A10 battery deep-sleep, A11 ESP32-CAM, A12 TinyML |
| B. AI diagnosis | B1–B9, B11 health score, B12 trend-based remaining life; B10 thermal photos are accepted as ordinary images | dedicated thermal-camera calibration |
| C. Knowledge | C1 manual retrieval + verified citations (ABB Baldor MN408, WEG IOM, pump IOM; upload more in the UI), C2 fault-signature library, C3 machine history, C4 feedback lessons | — |
| D. Agents | D1–D7 + Intake Clerk + Manual Librarian; visible trace; human approval | — |
| E. Action | E1 repair-centre ranking, E2 WhatsApp/SMS deep links, E3 PDF service ticket (with Devanagari/Kannada), E4 ntfy/Telegram push (needs config), E5 Hindi/Kannada/Tamil/Telugu/Marathi operator messages | E6 spoken alerts |
| F. Dashboard | F1–F6 plant overview, live charts + FFT orders, case lifecycle, guided checklist, work-order history, savings counter; F7 CSV export + REST API | F8 multi-site roles |

## Configuration (environment variables, all optional)
| Variable | Default | Purpose |
|---|---|---|
| `GEMMA_MODEL` | `gemma4:e4b` | Ollama model tag |
| `OLLAMA_URL` | `http://127.0.0.1:11434` | |
| `AURA_AUDIO_MODE` | `auto` | `native` / `spectrogram` |
| `AURA_THINK` | `0` | `1` enables Gemma thinking mode for the Diagnostician (slower) |
| `NTFY_TOPIC` | – | phone push via ntfy.sh (install the ntfy app and subscribe to the topic). **No account needed** |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | – | push alerts via a Telegram bot |

**No API keys are required.** Everything runs locally.

## Data sources (all open, no login)
- **Machine sounds:** MIMII dataset (Hitachi, Zenodo 3384388, CC BY-SA 4.0). Real normal and abnormal fan and pump
  recordings. See `demo_assets/audio/CREDITS.md`.
- **Machine photos:** Wikimedia Commons. Each file's licence and author are in `demo_assets/images/CREDITS.md`.
- **Service manuals:** ABB Baldor-Reliance MN408, WEG IOM 50033244 and a CSC centrifugal pump IOM. These are
  public PDFs, re-downloadable with `scripts/fetch_assets.py`.
- **Voice notes:** generated with gTTS (English and Hindi).
- **Repair centres:** `backend/knowledge/service_centres.json` is a **sample** with placeholder phone numbers.
  Replace it with your real vendors.

## Honest limitations
- The MPU6050 at about 1 kHz sees only up to about 500 Hz. Early bearing-defect frequencies are higher, which is
  why the phone audio (16 kHz) is part of the diagnosis.
- MIMII anomalies are subtle. Gemma's listening alone is not a reliable classifier for them, which is why the
  numbers from the acoustic DSP features matter.
- Remaining life is a linear trend extrapolation with a stated fit quality, not a trained prognostic model.
- All outputs are labelled as AI suggestions, and a human approves before dispatch.

## Layout
```
backend/      FastAPI app, Gemma client, DSP, telemetry analytics, knowledge, agents/, PDF tickets
frontend/     web control room: plain HTML/CSS/JS served by the backend (no build step, works offline)
simulator/    mock ESP32 nodes with physical fault signatures (the UI can inject faults)
firmware/     ESP32 Arduino sketch + wiring guide
demo_assets/  open-licence photos, MIMII sounds, voice notes
scripts/      run_all.sh, smoke_test.py, fetch_assets.py
```
