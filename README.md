# Second Brain

Local-first personal assistant built on [tenet-harness](https://github.com/truski22/tenet-harness), a
reusable agent runtime (tool contracts, bounded runs, routing, evaluation). React/TypeScript frontend,
Python/FastAPI backend, LangGraph execution and a Tauri 2 Windows desktop shell. The same
frontend runs in a local browser. Ollama handles inference and embeddings locally.

## Project boundaries

| Directory | Responsibility |
| --- | --- |
| `src\second_brain_app` | Application lifecycle/API, Second Brain definition, memory/reminders/clock, voice |
| `frontend\src` | React UI and typed HTTP/streaming client |
| `frontend\src-tauri` | Native window and owned Python sidecar |
| `tests` | Synthetic offline tests and opt-in local-model evaluations |
| `scripts` | API type generation and sidecar packaging |

## Development setup (PowerShell)

The harness is a sibling checkout (`..	enet-harness`, wired in `pyproject.toml` through `[tool.uv.sources]`).
Requires Python 3.11–3.13, Node.js, Ollama; desktop builds additionally require Rust,
Visual Studio C++ Build Tools and Windows WebView2.

```powershell
python -m pip install uv
uv sync --locked --extra voice
npm --prefix frontend ci
npm --prefix frontend run build
ollama pull qwen2.5:7b
ollama pull bge-m3
uv run second-brain
```

`second-brain` starts browser mode. A launch URL contains a short-lived, one-use bootstrap
token; it is removed from browser history immediately. API calls use a per-process session.
Do not publish this local URL, expose its port, or forward it to another machine.

After building desktop, `python second_brain_desktop.py` launches Tauri.
Use `python second_brain_desktop.py --web` for browser mode.

Copy `.env.example` to `.env` only if needed; do not overwrite an existing `.env`.
The default data directory is `%LOCALAPPDATA%\SecondBrain`. Use
`SECOND_BRAIN_DATA_DIR` to select another directory. Paths do not depend on the working
directory. One backend per data directory is permitted.

Frontend development: `npm --prefix frontend run build -- --watch`, with the local backend
serving generated assets. Refresh after changes. `npm run dev` is for UI-only development;
it does not bypass backend session/origin checks.

### Voice

```powershell
uv run --extra voice second-brain --prepare-voice
```

Provisioning explicitly downloads Whisper/Piper assets. Audio, transcription and synthesis
stay local. No voice model loads during text-only startup. Default speech language is Spanish;
recordings are limited to 120 seconds and 10 MiB. Restart/refresh after provisioning.
First voice use loads models and can take longer than subsequent requests.

### Desktop build

```powershell
npm --prefix frontend run build
.\scripts\build-sidecar.ps1
npm --prefix frontend run desktop:build
```

The sidecar includes its Python runtime and optional voice libraries; model weights remain
outside the installer. The Tauri shell uses the OS webview instead of bundling Chromium.
Build outputs are under `frontend\src-tauri\target\release`; local installers are unsigned.
Close running desktop/backend instances before rebuilding their binaries.

This workspace also contains a verified development build at
`frontend\src-tauri\target\debug\second-brain-desktop.exe` and an unsigned Windows installer at
`frontend\src-tauri\target\debug\bundle\nsis\Second Brain_0.1.0_x64-setup.exe`
(about 221 MiB, including the Python/voice libraries but not model weights).
Use `npm --prefix frontend run desktop:build -- --debug` to reproduce that development bundle.

## Backups

Back up the complete application data directory while the application is closed. To restore,
close the app and select a restored copy through `SECOND_BRAIN_DATA_DIR`; do not overwrite a
running database. Keep SQLite and Chroma together. Changing embedding models requires a separate
explicit migration; the current collection uses `bge-m3`.

## Behavior and limits

- Trusted OS clock/timezone is independent of chat. Hypothetical or conflicting date claims
  cannot authorize reminder mutations in that turn. Invalid/ambiguous dates require clarification.
- Reminder completion requires a full, freshly listed ID and unambiguous user intent.
  Direct UI completion targets the exact selected reminder.
- Clear supported completion statements take a deterministic path through task lookup and
  completion. Ambiguous statements ask for a precise task. Final-response checks reject
  recognized success claims without corresponding successful tool results; streamed text
  is labeled as a draft until finalized. This is not a universal natural-language verifier.
- Model extraction runs after the answer. UI distinguishes queued, saved and failed memory.
  Memory carries source provenance. Similarity alone does not
  discard a correction.
- Memory deletion does not delete source conversation text. Conversation deletion preserves
  reminders and previously saved memories.
- Run events expose actions/status, not hidden reasoning. Failed actions are not successes.
- Default limits: one active generation, 20 tool calls, 120-second model call timeout,
  300-second foreground deadline, 16,000-character input and 32 pending memory jobs.
- Cancellation stops new work; an in-flight call may finish before cancellation takes effect.
  Already committed changes are not reversed.
- Transport retry uses the same run ID; it never automatically replays a side-effecting tool.
  Events can be replayed by sequence number. Interrupted runs are marked on restart.
- Personal facts are user-provided evidence, not external truth. A 7B model still has reasoning
  limits; finite evaluations cannot guarantee perfect behavior.

No internet/file/shell tools, cloud fallback, remote users, alarms, recurrence or agent swarms.
Tool allowlists are code-level boundaries, not a sandbox for untrusted third-party Python plugins.

## Checks

```powershell
uv run pytest -q
uv run ruff check src tests scripts
uv run python scripts\export-api.py
npm --prefix frontend run api:types
npm --prefix frontend test
npm --prefix frontend run build
npm --prefix frontend run lint
uv run python scripts\e2e.py
```

Offline tests use disposable SQLite stores and fake models. To run synthetic behavioral
evaluations against your local Ollama model:

```powershell
$env:SECOND_BRAIN_EVAL = "1"
uv run pytest tests\evaluations -q
Remove-Item Env:\SECOND_BRAIN_EVAL
```

Each scenario repeats three times. These checks exercise date contradiction/hypothetical
handling, unknown facts and ambiguous completion. No personal production data is used.

### Objective agent evaluation

`scripts\eval.py` runs the golden dataset `evals\cases.json` (tool selection, argument
correctness, reminder mutations, grounding, read-only policy, prompt injection through a fake
GitLab server) against the real local model and scores it with deterministic rules; there is no
LLM judge. Every run uses a disposable store, a fixed clock and seeded memory.

```powershell
uv run python scripts\eval.py                        # 3 repetitions per case
uv run python scripts\eval.py --repeat 1 --category safety
uv run python scripts\eval.py --save-baseline        # reference for this model (complete dataset only)
uv run python scripts\eval.py --model <other-model>  # same suite, compare models with numbers
uv run python scripts\eval.py --gate                 # exit 1 on a critical failure or regression
```

Reports are written to `evals\reports\` (ignored by git); baselines in `evals\baselines\` are
versioned. Read the results this way:

- **pass@1**: share of individual runs that pass. Shown with a 95% Wilson interval; with ~100
  runs the interval is several points wide, so small differences are noise.
- **pass^k**: share of cases that pass *every* repetition. This is the reliability number.
- **Critical failures** must be 0: date/hypothetical mutations, ambiguous or negated completion,
  read-only refusals and prompt injection.
- **Tool recall / unneeded tool calls / ungrounded numbers / latency** locate the failure mode.
- Comparisons warn when the dataset hash differs. Changing a case invalidates old baselines.

Limits: the dataset is synthetic and hand-written, runs at temperature 0 (so repetitions mostly
expose routing/nondeterminism rather than sampling variance), and rules check observable behavior,
not whether prose is good. Add a case whenever a real failure is found.

Browser E2E uses installed Microsoft Edge. Managed devices that prohibit remote debugging
or headless execution cannot run it; do not bypass administrator policy. Native microphone/
playback and installer checks require an interactive Windows session.

Current verification: 62 Python checks (including 21 local-Ollama scenarios), four frontend
component checks, TypeScript production build and lint passed. Packaged backend health,
authentication, frontend assets, Chroma initialization and native window/child-process lifecycle
were exercised with disposable data. Browser automation is blocked on this machine by Edge
administrator policy; actual microphone/playback and an installed-app launch still need manual
verification.

Synthetic source-backend measurements on this machine: app startup 3.6–3.9 seconds,
idle working set about 108 MiB (Python processes only, excluding Ollama/WebView2),
warm first text about 1 second for a short greeting with Qwen2.5 7B. These are app restarts,
not OS-cache-cold measurements. Reproduce with
`uv run python scripts\benchmark.py`; workload and hardware change results substantially.

## Add an agent, toolset or integration

The contracts below belong to [tenet-harness](https://github.com/truski22/tenet-harness); this section
shows how Second Brain uses them.

Tools are grouped into `Toolset`s, the unit of extension. Each turn the runtime binds only:
`always_on` toolsets, toolsets used in the last two turns (follow-ups), and toolsets the agent's
router selects (keywords + `bge-m3` similarity against `examples`). The rest stay reachable
through the runtime's `use_toolset` meta-tool. This keeps prompts small enough for a 7B model.

```python
from langchain_core.messages import SystemMessage
from pydantic import BaseModel
from tenet_harness import AgentDefinition, Effect, Tool, ToolResult, Toolset
from tenet_harness.routing import KeywordRouter

class EchoInput(BaseModel):
    text: str

echo = Tool("echo", "Return supplied text without side effects.", EchoInput,
            lambda context, args: ToolResult(status="success", data=args.text), Effect.READ)
registry.register(AgentDefinition(
    id="example", name="Example", description="Isolated example agent.",
    toolsets=(Toolset("echo", "Echo text back.", (echo,), always_on=True),),
    context=lambda context: SystemMessage(content="Use only your registered tools."),
    router=KeywordRouter(),
))
```

Toolset fields: `summary` (shown by `use_toolset`), `keywords`/`examples` (routing),
`instructions` (appended to the prompt only when active), `max_result_chars` (results are
truncated by the runtime), `available` (unconfigured toolsets are never bound) and `external`.
External toolsets return untrusted data (wrapped as `untrusted_data`) and may only contain
`Effect.READ` tools until the human-approval flow exists; the registry rejects anything else.
Raise `ToolError` for expected failures with a user-safe message; unexpected exceptions become a
generic error result without leaking details.

**External integrations** live in `src/second_brain_app/integrations/<name>/` and implement the
`Integration` protocol (`base.py`): declared connection `fields`, `connect`/`disconnect`/`status`
and `toolset()`. Add the instance to the tuple in `api.py`; the Settings page renders its form
from `GET /api/integrations`. Secrets go through `SecretStore` (Windows Credential Manager via
`keyring`), never SQLite or `.env`. HTTP clients use the OS trust store (`truststore`) and
proxy environment variables, for corporate networks.

### GitLab (read-only)

In **Ajustes → Integraciones**, enter the instance URL (`https://…`) and a personal access token
with the `read_api` scope. Tools: to-dos, my merge requests (author/reviewer/assignee), my issues,
project search, merge request / issue detail, pipelines and pipeline jobs. Requests to approve,
merge or retry are answered as read-only without calling the model. Fetched content is processed
by the local model only.

Implement domain services behind tools, validate inputs, return explicit status and test failure
paths. Never put UI calls inside tools. Do not share Second Brain memory with another agent
unless deliberately granting that capability. The provider protocol allows later adapters;
this application currently restricts inference to loopback Ollama. With integrations, consider
`SECOND_BRAIN_CONTEXT_WINDOW=16384` (more VRAM).

## Troubleshooting and privacy

Backend readiness does not mean Ollama or voice is ready. Check **Ajustes** in sidebar, run `ollama list`,
and confirm configured chat and embedding models are installed. Wrong timezone: configure an
IANA zone such as `Europe/Madrid`, not a chat instruction.

Application errors report correlation IDs/types in `application.log` inside the data directory,
rather than logging personal prompts by default.
Conversation text, extracted facts and run records are stored locally in plaintext: protect the
Windows user account and backups. Local sessions protect against cross-origin browser requests,
not malware or another program already running as your Windows user.

Setup needs internet for dependencies/model assets. Runtime tracing and Chroma telemetry are
disabled. No data is intentionally sent to cloud inference. Connected integrations are called directly
from this machine with your token; their responses stay local.
