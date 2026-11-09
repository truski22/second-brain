import os
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from tenet_harness import Registry, RunRequest
from tenet_harness.providers import OllamaProvider
from tenet_harness.runtime import Runtime
from tenet_harness.storage import Store
from second_brain_app.agent import definition
from second_brain_app.config import Settings
from second_brain_app.domain.clock import Clock
from second_brain_app.domain.memory import Memory
from second_brain_app.domain.reminders import Reminders

pytestmark = pytest.mark.skipif(os.getenv("SECOND_BRAIN_EVAL") != "1",
                                reason="Opt-in local Ollama/Chroma integration.")


@pytest.mark.parametrize("repeat", range(3))
def test_real_memory_and_reminder_lifecycle(tmp_path, repeat):
    settings = Settings(tmp_path)
    store = Store(settings.db_path)
    clock = Clock("Europe/Madrid", lambda: datetime(2026, 9, 29, 12, tzinfo=ZoneInfo("Europe/Madrid")))
    provider = OllamaProvider(settings.model, settings.ollama_url, settings.model_timeout)
    memory = Memory(settings, store, clock, provider)
    reminders = Reminders(store, clock)
    registry = Registry()
    registry.register(definition(clock, reminders, memory))
    runtime = Runtime(registry, provider, store)

    def turn(number, text, thread="t"):
        run_id = f"positive-{repeat}-{number}"
        runtime.submit(RunRequest(run_id=run_id, thread_id=thread, agent_id="second-brain", text=text))
        runtime.wait(run_id, 310)
        run = store.run(run_id)
        assert run["status"] == "completed"
        deadline = time.monotonic() + 125
        while store.memory_status(run_id) in {"pending", "running"} and time.monotonic() < deadline:
            time.sleep(.1)
        assert store.memory_status(run_id) == "completed"
        return run["reply"]
    try:
        turn(1, "Mi veterinaria se llama Casilda.")
        assert any("Casilda" in item["text"] for item in memory.list())
        assert "Casilda" in turn(2, "¿Cómo se llama mi veterinaria?", thread="fresh")
        turn(3, "Recuérdame comprar pilas mañana.")
        assert len(reminders.pending()) == 1
        assert reminders.pending()[0]["due_date"] == "2026-09-30"
        turn(4, "Ya he comprado las pilas.")
        assert reminders.pending() == []
        for fact in memory.list():
            memory.delete(fact["id"])
        assert memory.list() == []
    finally:
        runtime.close()
