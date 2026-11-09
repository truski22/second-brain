from datetime import datetime, timezone
from threading import Event
from time import monotonic

from tenet_harness.contracts import RunContext
from tenet_harness.storage import Store
from second_brain_app.agent import definition
from second_brain_app.agent import AddReminder, CompleteReminder, NoArgs
from second_brain_app.domain.clock import Clock
from second_brain_app.domain.reminders import Reminders
from conftest import FakeMemory


def test_deterministic_completion_and_unverified_claim(tmp_path):
    clock = Clock(now=lambda: datetime(2026, 9, 29, tzinfo=timezone.utc))
    reminders = Reminders(Store(tmp_path / "test.sqlite"), clock)
    reminders.add("comprar pilas", "mañana", "1")
    agent = definition(clock, reminders, FakeMemory())
    events = []
    ctx = RunContext("r", "t", "Ya he comprado las pilas.", lambda kind, **kwargs: events.append(kind),
                     Event(), monotonic() + 60)
    assert "Marcado como terminado" in agent.preflight(ctx)
    assert reminders.pending() == []
    assert "complete_reminder" in ctx.successful_tools
    assert events == ["tool_start", "tool_result", "tool_start", "tool_result"]
    ctx.successful_tools.clear()
    assert "No he verificado" in agent.finalize(ctx, "He completado la tarea.")


def test_negative_or_conditional_completion_not_automated(tmp_path):
    clock = Clock(now=lambda: datetime(2026, 9, 29, tzinfo=timezone.utc))
    reminders = Reminders(Store(tmp_path / "test.sqlite"), clock)
    reminders.add("comprar pilas", "", "1")
    agent = definition(clock, reminders, FakeMemory())
    for text in ("No he comprado las pilas", "Ya he comprado pan pero no pilas", "¿Ya he comprado pilas?"):
        ctx = RunContext("r", "t", text, lambda *args, **kwargs: None, Event(), monotonic() + 60)
        assert agent.preflight(ctx) is None
        assert len(reminders.pending()) == 1


def test_question_cannot_authorize_task_mutation(tmp_path):
    import pytest
    clock = Clock(now=lambda: datetime(2026, 9, 29, tzinfo=timezone.utc))
    reminders = Reminders(Store(tmp_path / "test.sqlite"), clock)
    item = reminders.add("comprar pilas", "", "1")
    agent = definition(clock, reminders, FakeMemory())
    tools = {tool.name: tool for tool in agent.tools}
    ctx = RunContext("r", "t", "¿Qué pilas necesito?", lambda *args, **kwargs: None, Event(), monotonic() + 60)
    tools["list_reminders"].execute(ctx, NoArgs())
    with pytest.raises(ValueError):
        tools["complete_reminder"].execute(ctx, CompleteReminder(reminder_id=item["id"]))
    with pytest.raises(ValueError):
        tools["add_reminder"].execute(ctx, AddReminder(task="comprar pilas"))
    assert len(reminders.pending()) == 1


def test_external_action_claims_are_rejected(tmp_path):
    clock = Clock(now=lambda: datetime(2026, 9, 29, tzinfo=timezone.utc))
    agent = definition(clock, Reminders(Store(tmp_path / "test.sqlite"), clock), FakeMemory())
    ctx = RunContext("r", "t", "Apruébalo", lambda *args, **kwargs: None, Event(), monotonic() + 60)
    assert "solo lectura" in agent.finalize(ctx, 'Entendido, he aprobado el PR "Fix login".')
    assert agent.finalize(ctx, "El PR está aprobado por Ana.") == "El PR está aprobado por Ana."


def test_external_write_requests_answered_without_model(tmp_path):
    from tenet_harness.contracts import Toolset
    clock = Clock(now=lambda: datetime(2026, 9, 29, tzinfo=timezone.utc))
    reminders = Reminders(Store(tmp_path / "test.sqlite"), clock)
    agent = definition(clock, reminders, FakeMemory(), (Toolset("gitlab", "GitLab", (), external=True),))

    def ask(text):
        return agent.preflight(RunContext("r", "t", text, lambda *a, **k: None, Event(), monotonic() + 60))
    assert "solo lectura" in ask("Apruébalo, por favor")
    assert "solo lectura" in ask("haz el merge de ese MR")
    assert "read-only" in ask("Please approve it")
    assert "solo lectura" in ask("¿Puedes aprobarlo?")
    assert ask("¿Quién tiene que aprobar el MR 7?") is None
    assert ask("¿Quién aprueba los MRs de app?") is None
    assert ask("¿Qué MRs tengo pendientes?") is None
