import io
import wave
from types import SimpleNamespace

import pytest

from second_brain_app.config import Settings
from second_brain_app.voice import Voice


def prepared(tmp_path):
    voice = Voice(Settings(tmp_path))
    voice.path.mkdir()
    for name in ("small.pt", "es_ES-davefx-medium.onnx", "es_ES-davefx-medium.onnx.json"):
        (voice.path / name).touch()
    voice.stt = SimpleNamespace(transcribe=lambda samples, **kwargs: {"text": " Hola "})
    return voice


def test_missing_assets_fail_without_download(tmp_path):
    voice = Voice(Settings(tmp_path))
    assert not voice.ready()
    with pytest.raises(ValueError, match="prepare-voice"):
        voice.transcribe(b"audio")


def test_transcription_limit_and_temporary_cleanup(tmp_path, monkeypatch):
    voice = prepared(tmp_path)
    paths = []

    def decode(command, **kwargs):
        paths.append(command[command.index("-i") + 1])
        return SimpleNamespace(stdout=b"\0\0" * 16000)
    monkeypatch.setattr("second_brain_app.voice.subprocess.run", decode)
    assert voice.transcribe(b"fake encoded audio") == "Hola"
    from pathlib import Path
    assert all(not Path(path).exists() for path in paths)
    monkeypatch.setattr("second_brain_app.voice.subprocess.run",
                        lambda *a, **k: SimpleNamespace(stdout=b"\0\0" * (121 * 16000)))
    with pytest.raises(ValueError, match="120"):
        voice.transcribe(b"too long")


def test_synthesis_produces_wav(tmp_path):
    voice = prepared(tmp_path)

    def synthesize(text, output):
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(16000)
        output.writeframes(b"\0\0" * 100)
    voice.tts = SimpleNamespace(synthesize_wav=synthesize)
    audio = voice.speak("Hola")
    with wave.open(io.BytesIO(audio)) as wav:
        assert wav.getnframes() == 100
