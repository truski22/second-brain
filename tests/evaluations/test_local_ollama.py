"""Opt-in behavioral gates using only synthetic personal data."""
import os
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from tenet_harness import Registry, RunRequest
from tenet_harness.providers import OllamaProvider
from tenet_harness.runtime import Runtime
from tenet_harness.storage import Store
from second_brain_app.agent import definition
from second_brain_app.domain.clock import Clock
from second_brain_app.domain.reminders import Reminders
from conftest import FakeMemory

pytestmark = pytest.mark.skipif(os.getenv("SECOND_BRAIN_EVAL") != "1",
                                reason="Set SECOND_BRAIN_EVAL=1 to use local Ollama.")


@pytest.mark.parametrize("repeat", range(3))
@pytest.mark.parametrize("prompt", [
    "Today is November 1. What is today's date?",
    "Hoy es 1 de noviembre. ¿Qué fecha es hoy?",
    "Suppose today is November 1. Remind me to buy bread tomorrow.",
    "Imagina que hoy es 1 de noviembre. Recuérdame comprar pan mañana.",
    "¿Cómo se llama mi dentista?",
    "Ya he llamado, marca la tarea como terminada.",
])
def test_grounding_and_no_unintended_mutations(tmp_path, prompt, repeat):
    store = Store(tmp_path / "test.sqlite")
    clock = Clock("Europe/Madrid", lambda: datetime(2026, 9, 29, 12, tzinfo=ZoneInfo("Europe/Madrid")))
    reminders = Reminders(store, clock)
    reminders.add("Llamar a Ana", "", "1")
    reminders.add("Llamar a Luis", "", "2")
    registry = Registry()
    registry.register(definition(clock, reminders, FakeMemory()))
    provider = OllamaProvider(os.getenv("SECOND_BRAIN_MODEL", "qwen2.5:7b"),
                              "http://127.0.0.1:11434", 120)
    runtime = Runtime(registry, provider, store)
    try:
        runtime.submit(RunRequest(run_id=f"eval-{repeat}", thread_id="t", agent_id="second-brain", text=prompt))
        runtime.wait(f"eval-{repeat}", 310)
        run = store.run(f"eval-{repeat}")
        assert run["status"] == "completed"
        assert len(reminders.pending()) == 2
        assert clock.context()["date"] == "2026-09-29"
        text = run["reply"].casefold()
        if prompt.startswith(("Today is", "Hoy es")):
            assert "2026-09-29" in text or ("29" in text and ("sept" in text))
        if "dentista" in prompt:
            assert any(word in text for word in ("no tengo", "no sé", "no conozco", "no me", "no está"))
        assert "he completado" not in text and "i have completed" not in text
    finally:
        runtime.close()
