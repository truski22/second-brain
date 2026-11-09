import asyncio
import json
import logging
import os
import secrets
import sys
import time
import webbrowser
from contextlib import asynccontextmanager
from dataclasses import replace
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from tenet_harness import Registry, RunEvent, RunRequest
from tenet_harness.providers import OllamaProvider
from tenet_harness.routing import CombinedRouter, EmbeddingRouter, KeywordRouter
from tenet_harness.runtime import BusyError, Runtime, TERMINAL
from tenet_harness.storage import Store
from second_brain_app.agent import definition
from second_brain_app.config import Settings
from second_brain_app.domain.clock import Clock
from second_brain_app.domain.memory import Memory
from second_brain_app.domain.reminders import Reminders
from second_brain_app.messages import SPANISH
from second_brain_app.integrations.gitlab import GitLabIntegration
from second_brain_app.integrations.secrets import KeyringSecrets

log = logging.getLogger(__name__)


class BootstrapRequest(BaseModel):
    token: str = Field(min_length=20, max_length=100)


class UserSettings(BaseModel):
    model: str = Field(min_length=1, max_length=120)
    timezone: str = Field(default="", max_length=80)


class IntegrationValues(BaseModel):
    values: dict[str, str] = Field(max_length=10)


class SpeechRequest(BaseModel):
    text: str = Field(min_length=1, max_length=12000)


def create_app(*, token: str, port: int, settings: Settings | None = None,
               provider=None, memory_factory=Memory, secret_store=None, http_transport=None) -> FastAPI:
    os.environ["LANGCHAIN_TRACING_V2"] = "false"
    os.environ["LANGSMITH_TRACING"] = "false"
    os.environ["ANONYMIZED_TELEMETRY"] = "False"
    settings = settings or Settings.load()
    sessions: set[str] = set()
    bootstrap_tokens = {token: time.monotonic() + 300}
    origin = f"http://127.0.0.1:{port}"
    assets = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2])) / "frontend" / "dist"

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        store = Store(settings.db_path, legacy_agent_id="second-brain")
        overrides = store.get_settings()
        effective = replace(settings, **{k: v for k, v in overrides.items() if k in {"model", "timezone"}})
        clock = Clock(effective.timezone)
        models = provider or OllamaProvider(effective.model, effective.ollama_url, effective.model_timeout,
                                            effective.context_window, effective.embedding_model)
        memory = memory_factory(effective, store, clock, models)
        reminders = Reminders(store, clock)
        # New integrations only need to be added here; the runtime and UI discover them.
        integrations = {i.id: i for i in (GitLabIntegration(store, secret_store or KeyringSecrets(), http_transport),)}
        embed = getattr(models, "embed", None)
        router = CombinedRouter(KeywordRouter(), EmbeddingRouter(embed)) if embed else KeywordRouter()
        registry = Registry()
        registry.register(definition(clock, reminders, memory,
                                     tuple(i.toolset() for i in integrations.values()), router))
        runtime = Runtime(registry, models, store, effective.max_tools, effective.run_timeout,
                          effective.context_window, messages=SPANISH)
        runtime.adopt_thread("desktop", "second-brain", "Conversación anterior")
        app.state.integrations = integrations
        app.state.store, app.state.runtime = store, runtime
        app.state.clock, app.state.memory, app.state.reminders = clock, memory, reminders
        app.state.settings = effective
        from second_brain_app.voice import Voice
        app.state.voice = Voice(effective)
        try:
            yield
        finally:
            await asyncio.to_thread(runtime.close)
            for integration in integrations.values():
                integration.close()

    app = FastAPI(title="Second Brain local API", version="0.1.0", lifespan=lifespan,
                  docs_url=None, redoc_url=None)

    @app.middleware("http")
    async def local_session(request: Request, call_next):
        host = request.headers.get("host", "")
        if host != f"127.0.0.1:{port}":
            return JSONResponse({"detail": "Host not allowed."}, status_code=403)
        supplied_origin = request.headers.get("origin")
        if supplied_origin and supplied_origin != origin:
            return JSONResponse({"detail": "Origin not allowed."}, status_code=403)
        if request.url.path.startswith("/api/"):
            auth = request.headers.get("authorization", "")
            if not auth.startswith("Bearer ") or auth[7:] not in sessions:
                return JSONResponse({"detail": "Sesión caducada. Abre la app desde su lanzador."}, status_code=401)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; media-src 'self' blob:; connect-src 'self'; "
            "frame-ancestors 'none'; base-uri 'none'"
        )
        return response

    @app.exception_handler(BusyError)
    async def busy_error(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=409)

    @app.exception_handler(ValueError)
    async def value_error(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=422)

    @app.exception_handler(Exception)
    async def service_error(request, exc):
        log.error("Request failed at %s (%s)", request.url.path, type(exc).__name__)
        return JSONResponse({"detail": "Operación fallida. Consulta los registros locales."}, status_code=503)

    @app.get("/health")
    def health():
        return {"status": "ready"}

    @app.post("/auth")
    def authenticate(body: BootstrapRequest):
        expiry = bootstrap_tokens.pop(body.token, 0)
        if time.monotonic() > expiry:
            raise HTTPException(401, "Inicio de sesión caducado. Reinicia el lanzador.")
        session = secrets.token_urlsafe(32)
        sessions.add(session)
        return {"session": session}

    @app.post("/api/browser")
    def browser_link():
        value = secrets.token_urlsafe(32)
        bootstrap_tokens[value] = time.monotonic() + 60
        if not webbrowser.open(f"{origin}/#token={value}"):
            bootstrap_tokens.pop(value, None)
            raise ValueError("No se pudo abrir el navegador predeterminado.")
        return {"opened": True}

    @app.get("/api/status")
    def status():
        effective = app.state.settings
        ready, models, issue = False, [], None
        try:
            with httpx.Client(timeout=3, trust_env=False) as client:
                response = client.get(effective.ollama_url + "/api/tags")
                response.raise_for_status()
                models = [item["name"] for item in response.json()["models"]]
                ready = effective.model in models and effective.embedding_model in models
                # Ollama reports untagged names as :latest.
                ready = all(name in models or name + ":latest" in models
                            for name in (effective.model, effective.embedding_model))
                if not ready:
                    issue = "Faltan modelos locales. Consulta la instalación en README."
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            log.warning("Ollama readiness unavailable (%s)", type(exc).__name__)
            issue = "Ollama no está disponible."
        return {"clock": app.state.clock.context(), "model": effective.model,
                "configured_timezone": effective.timezone,
                "models": models, "ollama_ready": ready, "issue": issue,
                "data_dir": str(effective.data_dir), "voice_ready": app.state.voice.ready(),
                "active_run": next(iter(app.state.runtime.active_run_ids), None)}

    @app.get("/api/agents")
    def agents():
        return app.state.runtime.registry.list()

    @app.get("/api/conversations")
    def conversations():
        return app.state.store.conversations()

    def require_conversation(thread_id: str):
        if not app.state.store.conversation(thread_id):
            raise HTTPException(404, "Conversación no encontrada.")

    @app.get("/api/conversations/{thread_id}/messages")
    def history(thread_id: str):
        require_conversation(thread_id)
        return app.state.runtime.history(thread_id)

    @app.delete("/api/conversations/{thread_id}", status_code=204)
    def delete_conversation(thread_id: str):
        require_conversation(thread_id)
        app.state.runtime.delete_conversation(thread_id)

    @app.post("/api/runs")
    def submit(body: RunRequest):
        try:
            return app.state.runtime.submit(body)
        except KeyError:
            raise HTTPException(404, "Agente no encontrado.") from None

    def require_run(run_id):
        run = app.state.store.run(run_id)
        if run is None:
            raise HTTPException(404, "Ejecución no encontrada.")
        return run

    @app.get("/api/runs/{run_id}")
    def get_run(run_id: str):
        run = require_run(run_id)
        return {**run, "memory_status": app.state.store.memory_status(run_id)}

    @app.post("/api/runs/{run_id}/cancel", status_code=202)
    def cancel(run_id: str):
        require_run(run_id)
        app.state.runtime.cancel(run_id)
        return {"status": "cancellation_requested"}

    @app.get("/api/runs/{run_id}/events", response_model=list[RunEvent])
    async def events(run_id: str, request: Request, after: int = Query(0, ge=0)):
        require_run(run_id)

        async def stream():
            cursor = after
            while not await request.is_disconnected():
                batch = await asyncio.to_thread(app.state.store.events, run_id, cursor)
                for event in batch:
                    cursor = event["sequence"]
                    yield json.dumps(event, ensure_ascii=False) + "\n"
                run = await asyncio.to_thread(app.state.store.run, run_id)
                memory_status = await asyncio.to_thread(app.state.store.memory_status, run_id)
                if run is None or (run["status"] in TERMINAL and memory_status not in {"pending", "running"}):
                    if not batch:
                        # A worker may have published its terminal event between the first
                        # event query and the status query. Drain that tail before closing.
                        tail = await asyncio.to_thread(app.state.store.events, run_id, cursor)
                        if not tail:
                            break
                        for event in tail:
                            cursor = event["sequence"]
                            yield json.dumps(event, ensure_ascii=False) + "\n"
                await asyncio.sleep(0.1)
        return StreamingResponse(stream(), media_type="application/x-ndjson")

    @app.get("/api/reminders")
    def pending():
        return app.state.reminders.pending()

    @app.post("/api/reminders/{reminder_id}/complete")
    def complete(reminder_id: str):
        return app.state.reminders.complete(reminder_id)

    @app.get("/api/memories")
    def memories(offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100),
                 query: str = Query("", max_length=1000)):
        return app.state.memory.search(query) if query.strip() else app.state.memory.list(offset, limit)

    @app.delete("/api/memories/{memory_id}", status_code=204)
    def delete_memory(memory_id: str):
        app.state.memory.delete(memory_id)

    def require_integration(integration_id: str):
        integration = app.state.integrations.get(integration_id)
        if integration is None:
            raise HTTPException(404, "Integración no encontrada.")
        return integration

    @app.get("/api/integrations")
    def integrations():
        return [integration.status() for integration in app.state.integrations.values()]

    @app.put("/api/integrations/{integration_id}")
    def connect_integration(integration_id: str, body: IntegrationValues):
        return require_integration(integration_id).connect(body.values)

    @app.delete("/api/integrations/{integration_id}", status_code=204)
    def disconnect_integration(integration_id: str):
        require_integration(integration_id).disconnect()

    @app.put("/api/settings")
    def update_settings(body: UserSettings):
        runtime = app.state.runtime
        with runtime.exclusive():
            effective = replace(app.state.settings, model=body.model, timezone=body.timezone)
            with httpx.Client(timeout=3, trust_env=False) as client:
                response = client.get(effective.ollama_url + "/api/tags")
                response.raise_for_status()
                names = [model["name"] for model in response.json()["models"]]
            if body.model not in names:
                raise ValueError("Selecciona un modelo instalado en Ollama.")
            app.state.store.save_settings(body.model_dump())
            app.state.settings = effective
            runtime.provider.model = body.model
            app.state.clock.timezone = body.timezone
            return body

    @app.post("/api/voice/transcribe")
    async def transcribe(request: Request):
        if request.headers.get("content-type", "").split(";")[0] not in {"audio/webm", "audio/wav", "audio/ogg"}:
            raise HTTPException(415, "Formato de audio no compatible.")
        audio = bytearray()
        async for chunk in request.stream():
            audio.extend(chunk)
            if len(audio) > 10 * 1024 * 1024:
                raise HTTPException(413, "Grabación demasiado grande (máximo 10 MiB).")
        if not audio:
            raise HTTPException(422, "Grabación vacía.")
        text = await asyncio.to_thread(app.state.voice.transcribe, bytes(audio))
        return {"text": text}

    @app.post("/api/voice/speak")
    def speak(body: SpeechRequest):
        return Response(app.state.voice.speak(body.text), media_type="audio/wav")

    if (assets / "assets").exists():
        app.mount("/assets", StaticFiles(directory=assets / "assets"), name="assets")

    @app.get("/")
    def home():
        if not (assets / "index.html").exists():
            return JSONResponse({"detail": "Frontend no compilado. Ejecuta npm run build en frontend."},
                                status_code=503)
        return FileResponse(assets / "index.html")

    return app
