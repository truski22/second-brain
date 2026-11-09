from threading import Event
from time import monotonic

import pytest

from tenet_harness import RunContext, ToolError
from tenet_harness.storage import Store
from second_brain_app.integrations.gitlab import GitLabIntegration, Item, MyMergeRequests
from second_brain_app.integrations.secrets import MemorySecrets
from conftest import TOKEN, gitlab_api

@pytest.fixture
def gitlab(tmp_path):
    requests = []
    store, secrets = Store(tmp_path / "t.sqlite"), MemorySecrets()
    integration = GitLabIntegration(store, secrets, gitlab_api(requests))
    yield integration, store, secrets, requests
    integration.close()


def ctx():
    return RunContext("r", "t", "x", lambda *a, **k: None, Event(), monotonic() + 60)


def test_connect_validates_and_keeps_token_out_of_sqlite(gitlab):
    integration, store, secrets, _ = gitlab
    assert not integration.available()
    with pytest.raises(ValueError, match="https"):
        integration.connect({"url": "http://git.example", "token": TOKEN})
    with pytest.raises(ValueError, match="token"):
        integration.connect({"url": "https://git.example", "token": "glpat-wrong-token-1111"})
    status = integration.connect({"url": "https://git.example/", "token": TOKEN})
    assert status["connected"] and status["account"] == "me" and status["url"] == "https://git.example"
    assert secrets.get("gitlab.token") == TOKEN
    assert TOKEN not in str(store.get_settings())
    integration.disconnect()
    assert not integration.available() and secrets.get("gitlab.token") is None


def test_read_tools_compact_and_encode_projects(gitlab):
    integration, _, _, requests = gitlab
    integration.connect({"url": "https://git.example", "token": TOKEN})
    tools = {tool.name: tool for tool in integration.toolset().tools}
    assert all(tool.effect == "read" for tool in tools.values())
    listed = tools["gitlab_my_merge_requests"].execute(ctx(), MyMergeRequests(role="reviewer")).data
    assert requests[-1].url.params["reviewer_username"] == "me"
    assert listed[0]["project"] == "g/sub/app" and listed[0]["iid"] == 7 and "description" not in listed[0]
    detail = tools["gitlab_merge_request"].execute(ctx(), Item(project="g/sub/app", iid=7)).data
    assert detail["pipeline"] == {"id": 99, "status": "failed"} and len(detail["description"]) < 1600
    url = tools["gitlab_merge_request"].execute(
        ctx(), Item(project="https://git.example/g/sub/app/-/merge_requests/7", iid=7))
    assert url.data["iid"] == 7
    with pytest.raises(ToolError, match="No existe"):
        tools["gitlab_issue"].execute(ctx(), Item(project="g/other", iid=1))


def test_tools_fail_clearly_when_disconnected(gitlab):
    integration, _, _, _ = gitlab
    todos = next(t for t in integration.toolset().tools if t.name == "gitlab_todos")
    with pytest.raises(ToolError, match="no está conectado"):
        todos.execute(ctx(), todos.schema())
