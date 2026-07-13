"""Live hardware checks — NOT run by default (`pytest` only collects tests/unit).

Run on the Pi with:  pytest tests/integration -v

These exercise the real NPU, the real Piper voice and the real wake-word model.
Each test skips rather than fails when its dependency is absent, so this file is
safe to run on a laptop.
"""
import math
import os
import subprocess
import wave

import pytest

pytestmark = pytest.mark.integration

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _npu_available() -> bool:
    if not os.path.exists("/dev/hailo0"):
        return False
    try:
        import requests
        return requests.get("http://127.0.0.1:8000/api/tags", timeout=3).status_code == 200
    except Exception:
        return False


requires_npu = pytest.mark.skipif(not _npu_available(), reason="Hailo NPU / hailo-ollama unavailable")


def _synthesise(text: str, out_path: str) -> str:
    """Render `text` with the BMO Piper voice; skip the test if Piper is missing."""
    from core.config import PIPER_CMD, PIPER_MODEL
    if not (os.path.exists(PIPER_CMD) and os.path.exists(PIPER_MODEL)):
        pytest.skip("Piper binary or BMO voice model not installed")
    subprocess.run(
        [PIPER_CMD, "--model", PIPER_MODEL, "--output_file", out_path],
        input=text.encode(), capture_output=True, check=True, timeout=120,
    )
    return out_path


def _to_16k_mono(src: str, dst: str) -> str:
    import numpy as np
    import soundfile as sf
    from scipy.signal import resample_poly

    audio, sr = sf.read(src, dtype="float32")
    if audio.ndim > 1:
        audio = audio[:, 0]
    g = math.gcd(16000, sr)
    audio = resample_poly(audio, 16000 // g, sr // g)
    sf.write(dst, audio.astype("float32"), 16000)
    return dst


def test_piper_renders_the_bmo_voice(tmp_path):
    out = _synthesise("Hello friend!", str(tmp_path / "v.wav"))
    with wave.open(out) as w:
        assert w.getnframes() > 0


def test_wake_word_fires_on_hey_bmo_and_ignores_other_speech(tmp_path):
    import numpy as np
    import soundfile as sf
    from openwakeword.model import Model

    from core.config import WAKE_WORD_MODEL, WAKE_WORD_THRESHOLD
    if not os.path.exists(WAKE_WORD_MODEL):
        pytest.skip("wakeword.onnx not present")

    def peak_score(phrase: str) -> float:
        raw = _synthesise(phrase, str(tmp_path / "p.wav"))
        audio, _ = sf.read(_to_16k_mono(raw, str(tmp_path / "p16.wav")), dtype="float32")
        pcm = (np.clip(audio, -1, 1) * 32767).astype(np.int16)
        pad = np.zeros(16000, dtype=np.int16)
        pcm = np.concatenate([pad, pcm, pad])
        model = Model(wakeword_model_paths=[WAKE_WORD_MODEL])
        return max(
            max(model.predict(pcm[i:i + 1280]).values())
            for i in range(0, len(pcm) - 1280, 1280)
        )

    assert peak_score("Hey BMO!") >= WAKE_WORD_THRESHOLD
    assert peak_score("Please pass the butter.") < WAKE_WORD_THRESHOLD


@requires_npu
def test_llm_answers_in_character_without_leaking_reasoning(tmp_path, monkeypatch):
    import core.llm as llm

    monkeypatch.setattr(llm, "MEMORY_FILE", str(tmp_path / "memory.json"))
    brain = llm.Brain()
    spoken = " ".join(brain.stream_think("Hi BMO! What is your favourite colour?"))

    assert spoken.strip(), "BMO said nothing"
    assert "trouble thinking" not in spoken.lower(), "LLM unreachable"
    # The reasoning filter must hold across chunk boundaries.
    assert "<think>" not in spoken.lower() and "</think>" not in spoken.lower()
    # And reasoning must not be persisted back into history.
    assert all(
        "<think>" not in m["content"].lower()
        for m in brain.history if m["role"] == "assistant"
    )


@requires_npu
def test_timer_request_is_parsed_without_the_llm(tmp_path, monkeypatch):
    import core.llm as llm
    from core.llm import extract_json_object

    monkeypatch.setattr(llm, "MEMORY_FILE", str(tmp_path / "memory.json"))
    brain = llm.Brain()
    out = " ".join(brain.stream_think("Remind me in 30 seconds to stir the soup"))

    action, _ = extract_json_object(out)
    assert action["action"] == "set_timer"
    assert action["minutes"] == pytest.approx(0.5)   # seconds, not minutes
    assert action["message"] == "Stir the soup!"     # not the prompt's example text


def test_cpu_transcription_round_trips_synthesised_speech(tmp_path):
    from core.config import WHISPER_CMD, WHISPER_MODEL
    from core.stt import _transcribe_cpu

    if not (os.path.exists(WHISPER_CMD) and os.path.exists(WHISPER_MODEL)):
        pytest.skip("whisper.cpp binary or ggml model not installed")

    raw = _synthesise("What is your favourite colour?", str(tmp_path / "q.wav"))
    heard = _transcribe_cpu(_to_16k_mono(raw, str(tmp_path / "q16.wav")))
    assert "colour" in heard.lower() or "color" in heard.lower()
