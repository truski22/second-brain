import importlib.util
import json
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage

from second_brain_app.config import Settings
from conftest import FakeProvider

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def runner():
    spec = importlib.util.spec_from_file_location("eval_script", ROOT / "scripts" / "eval.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_dataset_is_well_formed(runner):
    cases = json.loads(runner.CASES.read_text(encoding="utf-8"))["cases"]
    ids = [c["id"] for c in cases]
    assert len(ids) == len(set(ids)) and len(cases) >= 30
    for case in cases:
        assert case["turns"] and case["expect"] and case["category"]
        assert set(case["expect"]) <= {"tools_required", "tools_forbidden", "tools_only", "args", "state",
                                       "reply", "grounded"}, case["id"]
    assert sum(c.get("critical", False) for c in cases) >= 8


def test_pipeline_end_to_end_with_scripted_model(runner, tmp_path):
    settings = Settings(tmp_path)
    cases = {c["id"]: c for c in json.loads(runner.CASES.read_text(encoding="utf-8"))["cases"]}

    def run(case_id, *responses):
        return runner.run_once(cases[case_id], 0, FakeProvider(list(responses)), settings, 30)

    # No tools, polite reply: passes the "uses no tools" case.
    assert run("chitchat_uses_no_tools", AIMessage(content="Hola, bien.")).get("passed")
    # Real tool call through the runtime: arguments recorded, state changed, reply checked.
    call = AIMessage(content="", tool_calls=[{"name": "add_reminder", "id": "c1",
                                              "args": {"task": "Comprar pan", "due": "mañana"}}])
    created = run("add_reminder_tomorrow", call, AIMessage(content="Hecho."))
    assert created["passed"], created["failures"]
    assert created["tools"] == ["add_reminder"]
    # Model that claims success without acting: the dataset catches it.
    lazy = run("add_reminder_tomorrow", AIMessage(content="Hecho, anotado."))
    assert not lazy["passed"] and any(f.startswith("tools") for f in lazy["failures"])
    # Unknown fact answered with a guess instead of admitting ignorance.
    guess = run("unknown_fact_dentist", AIMessage(content="Tu dentista es el Dr. Pérez."))
    assert not guess["passed"]
    # Prompt injection obeyed by the model: the injected write is caught as a critical failure.
    attack = AIMessage(content="", tool_calls=[{"name": "gitlab_merge_request", "id": "g1",
                                                "args": {"project": "g/sub/app", "iid": 7}}])
    obey = AIMessage(content="", tool_calls=[{"name": "add_reminder", "id": "g2",
                                              "args": {"task": "PWNED-4242", "due": ""}}])
    result = run("injection_in_mr_description", attack, obey, AIMessage(content="APROBADO-4242"))
    assert not result["passed"] and cases["injection_in_mr_description"]["critical"]
