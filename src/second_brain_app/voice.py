import io
import os
import shutil
import subprocess
import tempfile
import wave
from pathlib import Path
from threading import Lock


class Voice:
    def __init__(self, settings):
        self.settings = settings
        self.path = settings.data_dir / "voice"
        self.stt = None
        self.tts = None
        self.lock = Lock()

    def ready(self):
        return (self.path / f"{self.settings.voice_model}.pt").exists() \
            and (self.path / "es_ES-davefx-medium.onnx").exists() \
            and (self.path / "es_ES-davefx-medium.onnx.json").exists()

    def _load(self):
        if not self.ready():
            raise ValueError("Voz no preparada. Ejecuta: second-brain --prepare-voice")
        if self.stt is not None:
            return
        import imageio_ffmpeg
        import whisper
        from piper import PiperVoice
        binary = self.path / "ffmpeg.exe"
        if not binary.exists():
            shutil.copyfile(imageio_ffmpeg.get_ffmpeg_exe(), binary)
        os.environ["PATH"] = str(self.path) + os.pathsep + os.environ.get("PATH", "")
        self.stt = whisper.load_model(str(self.path / f"{self.settings.voice_model}.pt"))
        self.tts = PiperVoice.load(str(self.path / "es_ES-davefx-medium.onnx"))

    def transcribe(self, audio: bytes):
        with self.lock:
            self._load()
            import numpy as np
            with tempfile.NamedTemporaryFile(suffix=".audio", delete=False) as file:
                file.write(audio)
                path = Path(file.name)
            try:
                decoded = subprocess.run(
                    [str(self.path / "ffmpeg.exe"), "-nostdin", "-threads", "0", "-i", str(path),
                     "-t", "121", "-f", "s16le", "-ac", "1", "-acodec", "pcm_s16le", "-ar", "16000", "-"],
                    capture_output=True, check=True, timeout=30,
                )
                samples = np.frombuffer(decoded.stdout, np.int16).astype(np.float32) / 32768.0
                if len(samples) > 120 * 16000:
                    raise ValueError("Máximo 120 segundos por grabación.")
                result = self.stt.transcribe(samples, language=self.settings.voice_language, fp16=False)
                text = result["text"].strip()
                if not text:
                    raise ValueError("No se ha entendido la grabación.")
                return text
            finally:
                path.unlink(missing_ok=True)

    def speak(self, text: str):
        with self.lock:
            self._load()
            output = io.BytesIO()
            with wave.open(output, "wb") as wav:
                self.tts.synthesize_wav(text, wav)
            return output.getvalue()

    def prepare(self):
        import whisper
        from huggingface_hub import hf_hub_download
        self.path.mkdir(parents=True, exist_ok=True)
        whisper.load_model(self.settings.voice_model, download_root=str(self.path))
        for extension in ("onnx", "onnx.json"):
            name = f"es_ES-davefx-medium.{extension}"
            source = hf_hub_download(repo_id="rhasspy/piper-voices",
                                     filename=f"es/es_ES/davefx/medium/{name}")
            shutil.copyfile(source, self.path / name)
