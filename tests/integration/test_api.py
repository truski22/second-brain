import sys

import pytest
from fastapi.testclient import TestClient

from second_brain_app.api import create_app
from second_brain_app.config import Settings
from second_brain_app.integrations.secrets import MemorySecrets
from conftest import TOKEN, FakeMemory, FakeProvider, gitlab_api


@pytest.fixture
def client(tmp_path):
    app = create_app(token="test-bootstrap-token-123456", port=8765, settings=Settings(tmp_path),
                     provider=FakeProvider(), memory_factory=FakeMemory, secret_store=MemorySecrets(),
                     http_transport=gitlab_api([]))
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        yield client


def auth(client):
    response = client.post("/auth", json={"token": "test-bootstrap-token-123456"})
    assert response.status_code == 200
    client.headers["Authorization"] = "Bearer " + response.json()["session"]


def test_local_auth_origin_and_lazy_voice(client):
    assert client.get("/health").status_code == 200
    assert client.get("/api/conversations").status_code == 401
    assert client.get("/health", headers={"host": "evil.example"}).status_code == 403
    assert client.post("/auth", json={"token": "test-bootstrap-token-123456"},
                       headers={"origin": "http://evil.example"}).status_code == 403
    auth(client)
    assert client.get("/api/conversations").json() == []
    assert client.post("/auth", json={"token": "test-bootstrap-token-123456"}).status_code == 401
    assert "whisper" not in sys.modules
    assert "piper" not in sys.modules


def test_run_stream_history_and_delete(client):
    auth(client)
    request = {"run_id": "r1", "thread_id": "t1", "agent_id": "second-brain", "text": "Hola"}
    assert client.post("/api/runs", json=request).status_code == 200
    response = client.get("/api/runs/r1/events")
    assert response.status_code == 200
    assert '"type": "reply"' in response.text
    assert '"type": "done"' in response.text
    assert '"type": "memory_saved"' in response.text
    assert client.get("/api/runs/r1").json()["status"] == "completed"
    assert client.post("/api/runs", json=request).json()["id"] == "r1"
    assert len(client.get("/api/conversations/t1/messages").json()) == 2
    assert client.delete("/api/conversations/t1").status_code == 204
    assert client.get("/api/conversations/t1/messages").status_code == 404


def test_audio_limits_and_validation(client):
    auth(client)
    assert client.post("/api/voice/transcribe", content=b"audio",
                       headers={"content-type": "text/plain"}).status_code == 415
    assert client.post("/api/voice/transcribe", content=b"x" * (10 * 1024 * 1024 + 1),
                       headers={"content-type": "audio/webm"}).status_code == 413
    assert client.post("/api/runs", json={"run_id": "r", "thread_id": "t", "agent_id": "second-brain", "text": " "}).status_code == 422


def test_integrations_connect_and_disconnect(client):
    auth(client)
    [gitlab] = client.get("/api/integrations").json()
    assert gitlab["id"] == "gitlab" and not gitlab["connected"]
    assert {field["name"] for field in gitlab["fields"]} == {"url", "token"}
    bad = client.put("/api/integrations/gitlab", json={"values": {"url": "https://git.example", "token": "x" * 20}})
    assert bad.status_code == 422
    ok = client.put("/api/integrations/gitlab", json={"values": {"url": "https://git.example", "token": TOKEN}})
    assert ok.status_code == 200 and ok.json()["account"] == "me"
    assert "gitlab" in [t["id"] for t in client.get("/api/agents").json()[0]["toolsets"] if t["available"]]
    assert client.delete("/api/integrations/gitlab").status_code == 204
    assert not client.get("/api/integrations").json()[0]["connected"]
    assert client.put("/api/integrations/jira", json={"values": {}}).status_code == 404
