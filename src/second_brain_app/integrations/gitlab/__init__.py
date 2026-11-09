import re
from threading import Lock
from typing import Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field

from tenet_harness.contracts import RunContext, Tool, ToolError, ToolResult, Toolset
from tenet_harness.storage import Store

from ..base import ConnectionField, https_base_url
from ..secrets import SecretStore
from .client import GitLabClient

TOKEN_KEY = "gitlab.token"
URL_KEY = "gitlab.url"
USER_KEY = "gitlab.user"


class Args(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Todos(Args):
    limit: int = Field(default=20, ge=1, le=50)


class MyMergeRequests(Args):
    role: Literal["author", "reviewer", "assignee"] = "author"
    state: Literal["opened", "merged", "closed", "all"] = "opened"
    limit: int = Field(default=20, ge=1, le=50)


class MyIssues(Args):
    state: Literal["opened", "closed", "all"] = "opened"
    limit: int = Field(default=20, ge=1, le=50)


class ProjectSearch(Args):
    query: str = Field(min_length=1, max_length=200)
    limit: int = Field(default=10, ge=1, le=30)


class Item(Args):
    project: str = Field(min_length=1, max_length=300, description="Project path, e.g. group/name")
    iid: int = Field(ge=1, description="Number shown after ! (merge request) or # (issue)")


class Pipelines(Args):
    project: str = Field(min_length=1, max_length=300, description="Project path, e.g. group/name")
    ref: str = Field(default="", max_length=200, description="Branch or tag; empty for all")
    limit: int = Field(default=5, ge=1, le=20)


class PipelineJobs(Args):
    project: str = Field(min_length=1, max_length=300, description="Project path, e.g. group/name")
    pipeline_id: int = Field(ge=1)
    failed_only: bool = True


def _when(value: str | None) -> str | None:
    return value[:16].replace("T", " ") if value else None


def _people(rows) -> list[str]:
    return [row["username"] for row in rows or []]


def _project(item: dict) -> str:
    # references.full is "group/name!12" for merge requests and "group/name#5" for issues.
    return re.split(r"[!#](?=\d+$)", (item.get("references") or {}).get("full", ""))[0]


def _merge_request(item: dict) -> dict:
    return {"project": _project(item), "iid": item["iid"], "title": item["title"], "state": item["state"],
            "draft": item.get("draft", False), "author": (item.get("author") or {}).get("username"),
            "reviewers": _people(item.get("reviewers")), "status": item.get("detailed_merge_status"),
            "source_branch": item.get("source_branch"), "target_branch": item.get("target_branch"),
            "updated": _when(item.get("updated_at")), "url": item["web_url"]}


def _issue(item: dict) -> dict:
    return {"project": _project(item), "iid": item["iid"], "title": item["title"], "state": item["state"],
            "assignees": _people(item.get("assignees")), "labels": item.get("labels", []),
            "due_date": item.get("due_date"), "updated": _when(item.get("updated_at")), "url": item["web_url"]}


def _text(value: str | None, limit: int = 1500) -> str:
    value = (value or "").strip()
    return value if len(value) <= limit else value[:limit] + " …[truncated]"


class GitLabIntegration:
    id = "gitlab"
    name = "GitLab"
    fields = (
        ConnectionField("url", "URL de GitLab", placeholder="https://gitlab.com"),
        ConnectionField("token", "Token personal (scope read_api)", secret=True),
    )

    def __init__(self, store: Store, secrets: SecretStore, transport: httpx.BaseTransport | None = None):
        self.store, self.secrets, self.transport = store, secrets, transport
        self.lock = Lock()
        self._client: GitLabClient | None = None

    def _settings(self) -> dict:
        return self.store.get_settings()

    def available(self) -> bool:
        return bool(self._settings().get(URL_KEY)) and bool(self.secrets.get(TOKEN_KEY))

    def status(self) -> dict:
        settings = self._settings()
        return {"id": self.id, "name": self.name, "connected": self.available(),
                "url": settings.get(URL_KEY, ""), "account": settings.get(USER_KEY, ""),
                "access": "read", "fields": [vars(f) for f in self.fields]}

    def connect(self, values: dict[str, str]) -> dict:
        url = https_base_url(values.get("url", ""))
        token = values.get("token", "").strip()
        if not 10 <= len(token) <= 200:
            raise ValueError("Introduce un token personal de GitLab válido.")
        candidate = GitLabClient(url, token, self.transport)
        try:
            user = candidate.user()
        except ToolError as exc:
            candidate.close()
            raise ValueError(str(exc)) from None
        with self.lock:
            self.secrets.set(TOKEN_KEY, token)
            self.store.save_settings({URL_KEY: url, USER_KEY: user["username"]})
            if self._client:
                self._client.close()
            self._client = candidate
        return self.status()

    def disconnect(self) -> None:
        with self.lock:
            self.secrets.delete(TOKEN_KEY)
            with self.store.connect() as db:
                db.execute("DELETE FROM settings WHERE key IN (?,?)", (URL_KEY, USER_KEY))
            if self._client:
                self._client.close()
            self._client = None

    def client(self) -> GitLabClient:
        with self.lock:
            if self._client is None:
                url, token = self._settings().get(URL_KEY), self.secrets.get(TOKEN_KEY)
                if not url or not token:
                    raise ToolError("GitLab no está conectado. Conéctalo en Ajustes.")
                self._client = GitLabClient(url, token, self.transport)
            return self._client

    def close(self) -> None:
        with self.lock:
            if self._client:
                self._client.close()
            self._client = None

    def toolset(self) -> Toolset:
        def todos(ctx: RunContext, args: Todos):
            rows = self.client().get("/todos", state="pending", per_page=args.limit)
            return ToolResult(status="success", data=[{
                "action": row["action_name"], "type": row["target_type"],
                "project": (row.get("project") or {}).get("path_with_namespace"),
                "title": (row.get("target") or {}).get("title") or row.get("body", "")[:200],
                "iid": (row.get("target") or {}).get("iid"), "author": (row.get("author") or {}).get("username"),
                "created": _when(row.get("created_at")), "url": row.get("target_url")} for row in rows])

        def my_merge_requests(ctx: RunContext, args: MyMergeRequests):
            client = self.client()
            scope = {"author": {"scope": "created_by_me"}, "assignee": {"scope": "assigned_to_me"},
                     "reviewer": {"scope": "all", "reviewer_username": client.user()["username"]}}[args.role]
            rows = client.get("/merge_requests", state=args.state, per_page=args.limit,
                              order_by="updated_at", **scope)
            return ToolResult(status="success", data=[_merge_request(row) for row in rows])

        def my_issues(ctx: RunContext, args: MyIssues):
            rows = self.client().get("/issues", scope="assigned_to_me", state=args.state,
                                     per_page=args.limit, order_by="updated_at")
            return ToolResult(status="success", data=[_issue(row) for row in rows])

        def search_projects(ctx: RunContext, args: ProjectSearch):
            rows = self.client().get("/projects", search=args.query, membership="true", simple="true",
                                     order_by="last_activity_at", per_page=args.limit)
            return ToolResult(status="success", data=[{
                "project": row["path_with_namespace"], "name": row["name"],
                "default_branch": row.get("default_branch"), "last_activity": _when(row.get("last_activity_at")),
                "url": row["web_url"]} for row in rows])

        def merge_request(ctx: RunContext, args: Item):
            client = self.client()
            row = client.get(f"{client.project_path(args.project)}/merge_requests/{args.iid}")
            pipeline = row.get("head_pipeline") or {}
            return ToolResult(status="success", data={
                **_merge_request(row), "description": _text(row.get("description")),
                "labels": row.get("labels", []), "has_conflicts": row.get("has_conflicts"),
                "changes_count": row.get("changes_count"),
                "pipeline": {"id": pipeline.get("id"), "status": pipeline.get("status")} if pipeline else None})

        def issue(ctx: RunContext, args: Item):
            client = self.client()
            row = client.get(f"{client.project_path(args.project)}/issues/{args.iid}")
            return ToolResult(status="success", data={
                **_issue(row), "description": _text(row.get("description")),
                "author": (row.get("author") or {}).get("username"),
                "milestone": (row.get("milestone") or {}).get("title")})

        def pipelines(ctx: RunContext, args: Pipelines):
            client = self.client()
            rows = client.get(f"{client.project_path(args.project)}/pipelines", ref=args.ref,
                              per_page=args.limit, order_by="id", sort="desc")
            return ToolResult(status="success", data=[{
                "id": row["id"], "status": row["status"], "ref": row.get("ref"), "sha": (row.get("sha") or "")[:8],
                "source": row.get("source"), "created": _when(row.get("created_at")), "url": row.get("web_url")}
                for row in rows])

        def pipeline_jobs(ctx: RunContext, args: PipelineJobs):
            client = self.client()
            rows = client.get(f"{client.project_path(args.project)}/pipelines/{args.pipeline_id}/jobs",
                              per_page=50, **({"scope": "failed"} if args.failed_only else {}))
            return ToolResult(status="success", data=[{
                "name": row["name"], "stage": row.get("stage"), "status": row["status"],
                "failure_reason": row.get("failure_reason"), "allow_failure": row.get("allow_failure"),
                "url": row.get("web_url")} for row in rows])

        return Toolset(
            id=self.id, external=True, available=self.available,
            summary="GitLab: merge requests, code reviews, issues, CI pipelines, to-dos and code projects "
                    "(revisiones de código, pipelines, repositorios).",
            keywords=("gitlab", "merge request", "merge requests", "mr", "mrs", "pull request", "pipeline",
                      "pipelines", "ci", "repo", "repos", "repositorio", "repositorios", "rama", "branch",
                      "commit", "review", "reviews", "code review", "revisión de código", "issue", "issues"),
            examples=(
                "¿Qué merge requests tengo pendientes de revisar?", "¿Por qué ha fallado el pipeline?",
                "¿Tengo algún PR esperando mi aprobación?", "¿Qué issues tengo asignadas?",
                "¿Qué tengo pendiente en GitLab?", "¿Cómo va el build de la rama main?",
                "Show my open merge requests", "Why did CI fail on my branch?"),
            instructions=(
                "GitLab access is read-only: you cannot create, comment, approve, merge or retry anything; say "
                "so if asked and never offer those actions. A request to be reminded of something (even "
                "about a pipeline or MR) is a reminder: call add_reminder directly, do not query GitLab. Identify items by project path and iid from previous results; if the project is "
                "unknown, search projects first. Include the url when you mention a specific item."),
            tools=(
                Tool("gitlab_todos", "List the user's pending GitLab to-dos (mentions, review requests).",
                     Todos, todos),
                Tool("gitlab_my_merge_requests", "List merge requests where the user is author, reviewer "
                     "or assignee.", MyMergeRequests, my_merge_requests),
                Tool("gitlab_my_issues", "List GitLab issues assigned to the user.", MyIssues, my_issues),
                Tool("gitlab_search_projects", "Find GitLab projects the user belongs to by name.",
                     ProjectSearch, search_projects),
                Tool("gitlab_merge_request", "Read one merge request: description, merge status and the "
                     "status of its latest pipeline.",
                     Item, merge_request),
                Tool("gitlab_issue", "Read one GitLab issue with its description.", Item, issue),
                Tool("gitlab_pipelines", "List recent CI pipelines of a project or branch. For one merge "
                     "request use gitlab_merge_request instead.",
                     Pipelines, pipelines),
                Tool("gitlab_pipeline_jobs", "List the jobs of a pipeline (failed ones by default) to "
                     "explain a failure.", PipelineJobs, pipeline_jobs),
            ),
        )
