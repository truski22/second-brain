import hashlib
import json
from threading import RLock

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field, StrictStr

from tenet_harness.storage import Store, timestamp


class Facts(BaseModel):
    facts: list[StrictStr] = Field(max_length=12)


class Memory:
    def __init__(self, settings, store: Store, clock, provider):
        self.settings, self.store, self.clock, self.provider = settings, store, clock, provider
        self._vector = None
        self.lock = RLock()
        with store.connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS memory_tombstones (id TEXT PRIMARY KEY)")
            db.execute("CREATE TABLE IF NOT EXISTS memory_extractions (run_id TEXT PRIMARY KEY, facts TEXT NOT NULL)")

    @property
    def vector(self):
        with self.lock:
            if self._vector is None:
                from chromadb.config import Settings as ChromaSettings
                from langchain_chroma import Chroma
                from langchain_ollama import OllamaEmbeddings
                path = self.settings.data_dir / "second_brain_memory"
                self._vector = Chroma(
                    collection_name="memories",
                    embedding_function=OllamaEmbeddings(
                        model=self.settings.embedding_model, base_url=self.settings.ollama_url,
                        client_kwargs={"timeout": self.settings.model_timeout, "trust_env": False}),
                    persist_directory=str(path), collection_metadata={"hnsw:space": "cosine"},
                    client_settings=ChromaSettings(anonymized_telemetry=False, is_persistent=True),
                )
            return self._vector

    def search(self, query: str, minimum: float = 0.50) -> list[dict]:
        with self.lock:
            return [{"id": doc.id, "text": doc.page_content, "metadata": doc.metadata,
                     "score": min(1, max(0, score))}
                    for doc, score in self.vector.similarity_search_with_relevance_scores(query, k=4)
                    if score >= minimum]

    def list(self, offset: int = 0, limit: int = 50):
        with self.lock:
            rows = self.vector.get(limit=limit, offset=offset, include=["documents", "metadatas"])
            return [{"id": key, "text": text, "metadata": metadata or {}}
                    for key, text, metadata in zip(rows["ids"], rows["documents"], rows["metadatas"])]

    def delete(self, memory_id: str):
        with self.lock:
            with self.store.connect() as db:
                db.execute("INSERT OR IGNORE INTO memory_tombstones VALUES (?)", (memory_id,))
            self.vector.delete(ids=[memory_id])

    def memorize(self, job: dict):
        if self.clock.scheduling_conflict(job["user_text"]):
            return []
        system = SystemMessage(content=(
            'Extract durable personal facts explicitly stated by the user. Return {"facts": ["..."]}. '
            "Use the user's language and perspective. Short replies may be resolved using the previous "
            "assistant question, but never copy facts asserted only by the assistant. Do not save questions, "
            "requests, instructions, tasks, task completion, hypothetical statements, or claims about today's "
            "date. Do not infer missing names or dates. Preserve corrections explicitly. "
            "Each fact must be self-contained, at most 1000 characters; at most 12 facts. "
            "Use the trusted current date for relative personal-event dates: "
            + json.dumps(self.clock.context())
        ))
        with self.store.connect() as db:
            cached = db.execute("SELECT facts FROM memory_extractions WHERE run_id=?", (job["run_id"],)).fetchone()
        if cached:
            facts = Facts.model_validate_json(cached[0]).facts
        else:
            response = self.provider.chat(structured=True).invoke([
                system, HumanMessage(content=json.dumps({
                    "previous_assistant_question": job["previous_reply"], "user_message": job["user_text"],
                }, ensure_ascii=False)),
            ])
            if not isinstance(response.content, str):
                raise ValueError("Memory extractor did not return JSON text.")
            facts = Facts.model_validate_json(response.content).facts
        if any(not f.strip() or len(f) > 1000 for f in facts):
            raise ValueError("Memory extractor returned an invalid fact.")
        if not cached:
            with self.store.connect() as db:
                db.execute("INSERT INTO memory_extractions VALUES (?,?)",
                           (job["run_id"], Facts(facts=facts).model_dump_json()))
        saved = []
        with self.lock:
            for fact in facts:
                fact = fact.strip()
                memory_id = hashlib.sha256(f"{job['run_id']}\0{fact}".encode()).hexdigest()
                with self.store.connect() as db:
                    deleted = db.execute("SELECT 1 FROM memory_tombstones WHERE id=?", (memory_id,)).fetchone()
                if deleted:
                    continue
                existing = self.vector.get(ids=[memory_id])
                if existing["ids"]:
                    continue
                best = self.vector.similarity_search_with_relevance_scores(fact, k=1)
                # Exact normalized equality avoids treating a correction as a near-duplicate.
                if best and best[0][0].page_content.casefold().strip() == fact.casefold():
                    continue
                metadata = {"created_at": timestamp(), "source_run": job["run_id"],
                            "source_conversation": job["thread_id"], "source": "user_statement"}
                self.vector.add_texts([fact], metadatas=[metadata], ids=[memory_id])
                saved.append({"id": memory_id, "text": fact, "metadata": metadata})
        return saved
