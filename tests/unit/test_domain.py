from datetime import datetime
from threading import Event
from time import monotonic
from zoneinfo import ZoneInfo

import pytest

from tenet_harness import RunContext
from tenet_harness.storage import Store
from second_brain_app.agent import AddReminder, CompleteReminder, NoArgs, definition
from second_brain_app.config import Settings
from second_brain_app.domain.clock import Clock
from second_brain_app.domain.reminders import Reminders
from conftest import FakeMemory


@pytest.fixture
def clock():
    return Clock("Europe/Madrid", now=lambda: datetime(2026, 9, 29, 23, 59, tzinfo=ZoneInfo("Europe/Madrid")))


@pytest.mark.parametrize(("text", "expected"), [
    ("hoy", "2026-09-29"), ("mañana", "2026-09-30"), ("pasado mañana", "2026-10-01"),
    ("tomorrow", "2026-09-30"), ("2026-11-01", "2026-11-01"),
    ("el viernes", "2026-10-02"), ("1 de noviembre", "2026-11-01"),
])
def test_dates(clock, text, expected):
    assert clock.resolve(text) == expected


@pytest.mark.parametrize("text", ["2026-02-30", "11/01/2026", "11/01", "la semana que viene", "pronto", "noviembre",
                                  "2026", "tomorrow 14:00", "not a date"])
def test_ambiguous_invalid_dates(clock, text):
    with pytest.raises(ValueError):
        clock.resolve(text)


def test_clock_claims(clock):
    assert clock.scheduling_conflict("today is November 1")
    assert clock.scheduling_conflict("hoy es 1 de noviembre")
    assert clock.scheduling_conflict("supongamos que hoy es 1 de noviembre")
    assert not clock.scheduling_conflict("hoy es 2026-09-29")
    assert clock.context()["date"] == "2026-09-29"
    assert "2026-09-29" in clock.clarification("Today is November 1")
    assert clock.clarification("Suppose today is November 1") is None


def test_reminder_validation_and_idempotency(tmp_path, clock):
    reminders = Reminders(Store(tmp_path / "test.sqlite"), clock)
    with pytest.raises(ValueError):
        reminders.add("Task", "nonsense", "bad")
    assert reminders.pending() == []
    first = reminders.add("Comprar pan", "mañana", "request-1")
    assert reminders.add("Comprar pan", "mañana", "request-1") == first
    assert len(reminders.pending()) == 1
    with pytest.raises(ValueError):
        reminders.complete(first["id"][:8])
    reminders.complete(first["id"])
    reminders.complete(first["id"])
    assert reminders.pending() == []


def test_ambiguous_completion_and_clock_mutation_are_blocked(tmp_path, clock):
    reminders = Reminders(Store(tmp_path / "test.sqlite"), clock)
    first = reminders.add("Llamar a Ana", "", "1")
    reminders.add("Llamar a Luis", "", "2")
    agent = definition(clock, reminders, FakeMemory())
    tools = {tool.name: tool for tool in agent.tools}
    ctx = RunContext("run", "thread", "Ya he llamado", lambda *a, **k: None, Event(), monotonic() + 60)
    tools["list_reminders"].execute(ctx, NoArgs())
    with pytest.raises(ValueError):
        tools["complete_reminder"].execute(ctx, CompleteReminder(reminder_id=first["id"]))
    assert len(reminders.pending()) == 2
    ctx.user_text = "Today is November 1. Remind me to buy bread tomorrow."
    with pytest.raises(ValueError):
        tools["add_reminder"].execute(ctx, AddReminder(task="Bread", due="tomorrow"))
    assert len(reminders.pending()) == 2


def test_config_rejects_remote_inference(tmp_path):
    with pytest.raises(ValueError):
        Settings(tmp_path, ollama_url="https://example.com")
    with pytest.raises(ValueError):
        Settings(tmp_path, timezone="not/a/timezone")
