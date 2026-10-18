"""Central configuration. Everything can be overridden with environment variables."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = ROOT / "backend"
KNOWLEDGE_DIR = BACKEND_DIR / "knowledge"
MANUALS_DIR = KNOWLEDGE_DIR / "manuals"
DATA_DIR = Path(os.getenv("AURA_DATA_DIR", ROOT / "data"))
UPLOAD_DIR = DATA_DIR / "uploads"
DB_PATH = DATA_DIR / "aurasense.db"

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")
GEMMA_MODEL = os.getenv("GEMMA_MODEL", "gemma4:e4b")
GEMMA_TEMPERATURE = float(os.getenv("GEMMA_TEMPERATURE", "0.2"))
GEMMA_NUM_CTX = int(os.getenv("GEMMA_NUM_CTX", "16384"))
GEMMA_TIMEOUT_S = int(os.getenv("GEMMA_TIMEOUT_S", "300"))

# Audio strategy: "auto" probes Gemma native audio once, then falls back to
# spectrogram-image + DSP features (still reasoned over by Gemma).
AUDIO_MODE = os.getenv("AURA_AUDIO_MODE", "auto")  # auto | native | spectrogram
# Speech-to-text fallback for technician voice notes when Gemma native audio is unavailable.
WHISPER_MODEL = os.getenv("AURA_WHISPER_MODEL", "base")

# Optional notification channels (all off unless configured).
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
NTFY_TOPIC = os.getenv("NTFY_TOPIC", "")  # e.g. "aurasense-yourteam-1234" on ntfy.sh
NTFY_SERVER = os.getenv("NTFY_SERVER", "https://ntfy.sh")

# Business assumptions for the ROI counter (₹).
DOWNTIME_COST_PER_HOUR_INR = float(os.getenv("AURA_DOWNTIME_COST_INR", "25000"))
AVG_BREAKDOWN_HOURS = float(os.getenv("AURA_AVG_BREAKDOWN_HOURS", "8"))

for d in (DATA_DIR, UPLOAD_DIR, MANUALS_DIR):
    d.mkdir(parents=True, exist_ok=True)
