import os
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    model: str = "qwen2.5:7b"
    embedding_model: str = "bge-m3"
    ollama_url: str = "http://127.0.0.1:11434"
    timezone: str = ""
    model_timeout: float = 120
    run_timeout: float = 300
    max_tools: int = 20
    context_window: int = 8192
    voice_model: str = "small"
    voice_language: str = "es"

    def __post_init__(self):
        url = urlparse(self.ollama_url)
        if url.scheme != "http" or url.hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("Ollama must use an HTTP loopback URL (local-only policy).")
        if url.username or url.password or url.query or url.fragment:
            raise ValueError("Ollama URL must not contain credentials, query or fragment.")
        if self.timezone:
            try:
                ZoneInfo(self.timezone)
            except ZoneInfoNotFoundError as exc:
                raise ValueError("Zona horaria desconocida. Usa un identificador como Europe/Madrid.") from exc
        if not 1 <= self.max_tools <= 40 or not 1 <= self.model_timeout <= 300:
            raise ValueError("Invalid execution limits.")
        if not 1 <= self.run_timeout <= 900:
            raise ValueError("Invalid run timeout.")
        if not 4096 <= self.context_window <= 131072:
            raise ValueError("Invalid context window.")

    @property
    def db_path(self) -> Path:
        return self.data_dir / "second_brain.sqlite"

    @classmethod
    def load(cls):
        if not getattr(sys, "frozen", False):
            load_dotenv(Path(__file__).resolve().parents[2] / ".env")
        default = Path(os.getenv("LOCALAPPDATA", Path.home() / ".local" / "share")) / "SecondBrain"
        load_dotenv(default / ".env")
        return cls(
            data_dir=Path(os.getenv("SECOND_BRAIN_DATA_DIR") or default).expanduser().resolve(),
            model=os.getenv("SECOND_BRAIN_MODEL", "qwen2.5:7b"),
            embedding_model=os.getenv("SECOND_BRAIN_EMBEDDING_MODEL", "bge-m3"),
            ollama_url=os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434"),
            timezone=os.getenv("SECOND_BRAIN_TIMEZONE", ""),
            model_timeout=float(os.getenv("SECOND_BRAIN_MODEL_TIMEOUT", "120")),
            run_timeout=float(os.getenv("SECOND_BRAIN_RUN_TIMEOUT", "300")),
            max_tools=int(os.getenv("SECOND_BRAIN_MAX_TOOLS", "20")),
            context_window=int(os.getenv("SECOND_BRAIN_CONTEXT_WINDOW", "8192")),
            voice_model=os.getenv("SECOND_BRAIN_VOICE_MODEL", "small"),
            voice_language=os.getenv("SECOND_BRAIN_VOICE_LANGUAGE", "es"),
        )
