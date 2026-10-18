import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backend.agents.reporter import script_purity  # noqa: E402


def test_script_purity_flags_mixed_scripts():
    garbled = "มอเตอร์ कंपनสูง. ಈಗ ಕನ್ವೇಯರ್ ಬೆಲ್ಟ್ ಮೇಲಿನ ಭಾರವನ್ನು ಕಡಿಮೆ ಮಾಡಿ."
    assert script_purity(garbled, "Kannada") < 0.95
    assert script_purity("ಕಂಪನ ಹೆಚ್ಚಾದರೆ ಯಂತ್ರವನ್ನು ಓಡಿಸಬೇಡಿ. LOTO ಮಾಡಿ.", "Kannada") >= 0.95
    assert script_purity("पंखा बहुत ज़्यादा हिल रहा है।", "Hindi") >= 0.95
