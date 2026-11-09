from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage
from pydantic import ValidationError

from tenet_harness.storage import Store
from second_brain_app.config import Settings
from second_brain_app.domain.clock import Clock
from second_brain_app.domain.memory import Memory
from conftest import FakeModel


class Vector:
    def __init__(self):
        self.records = {}

    def get(self, ids=None, **kwargs):
        ids = [key for key in (ids or self.records) if key in self.records]
        return {"ids": ids, "documents": [self.records[key][0] for key in ids],
                "metadatas": [self.records[key][1] for key in ids]}

    def similarity_search_with_relevance_scores(self, text, k):
        return [(SimpleNamespace(id=key, page_content=value[0], metadata=value[1]), 0.99)
                for key, value in list(self.records.items())[:k]]

    def add_texts(self, texts, metadatas, ids):
        self.records.update({key: (text, meta) for key, text, meta in zip(ids, texts, metadatas)})

    def delete(self, ids):
        for key in ids:
            self.records.pop(key, None)


def memory(tmp_path, response):
    model = FakeModel([AIMessage(content=response)])
    provider = SimpleNamespace(chat=lambda structured=False: model)
    service = Memory(Settings(tmp_path), Store(tmp_path / "test.sqlite"),
                     Clock(now=lambda: datetime(2026, 9, 29, tzinfo=timezone.utc)), provider)
    service._vector = Vector()
    return service, model


def test_memory_provenance_deletion_retry_and_corrections(tmp_path):
    service, model = memory(tmp_path, '{"facts":["Mi jefe es Luis"]}')
    service.vector.add_texts(["Mi jefe es Marcos"], [{"created_at": "2026-01-01"}], ["legacy"])
    job = {"run_id": "r1", "thread_id": "t", "user_text": "Mi nuevo jefe es Luis", "previous_reply": ""}
    saved = service.memorize(job)
    assert len(saved) == 1
    assert saved[0]["metadata"]["source_conversation"] == "t"
    service.delete(saved[0]["id"])
    assert service.memorize(job) == []
    assert len(model.calls) == 1
    assert service.vector.get()["ids"] == ["legacy"]


@pytest.mark.parametrize("response", ['{"facts":123}', '{"facts":[7]}', '{"facts":[""]}', "not json"])
def test_invalid_extraction_fails_explicitly(tmp_path, response):
    service, _ = memory(tmp_path, response)
    with pytest.raises((ValueError, ValidationError)):
        service.memorize({"run_id": "r", "thread_id": "t", "user_text": "Mi jefe es Luis", "previous_reply": ""})
    assert service.vector.get()["ids"] == []
