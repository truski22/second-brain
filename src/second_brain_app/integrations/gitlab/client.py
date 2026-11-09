import logging
from urllib.parse import quote

import httpx

from tenet_harness import ToolError

from ..base import system_tls

log = logging.getLogger(__name__)


class GitLabClient:
    """Minimal read-only GitLab REST v4 client; errors surface as user-safe ToolError."""

    def __init__(self, base_url: str, token: str, transport: httpx.BaseTransport | None = None):
        self.base_url = base_url
        self.http = httpx.Client(
            base_url=base_url + "/api/v4", headers={"PRIVATE-TOKEN": token}, timeout=15,
            follow_redirects=False, trust_env=True, transport=transport,
            **({} if transport else {"verify": system_tls()}),
        )
        self._user: dict | None = None

    def get(self, path: str, **params):
        try:
            response = self.http.get(path, params={k: v for k, v in params.items() if v not in (None, "")})
        except httpx.TimeoutException:
            raise ToolError("GitLab no respondió a tiempo.") from None
        except httpx.HTTPError as exc:
            log.warning("GitLab request failed (%s)", type(exc).__name__)
            raise ToolError("No se pudo conectar con GitLab. Revisa la red, la VPN o el proxy.") from None
        if response.status_code == 401:
            raise ToolError("El token de GitLab no es válido o ha caducado.")
        if response.status_code == 403:
            raise ToolError("El token no tiene permiso para este recurso de GitLab.")
        if response.status_code == 404:
            raise ToolError("No existe en GitLab o no tienes acceso. Comprueba el proyecto y el número.")
        if response.status_code >= 300:
            raise ToolError(f"GitLab devolvió un error ({response.status_code}).")
        return response.json()

    def user(self) -> dict:
        if self._user is None:
            self._user = self.get("/user")
        return self._user

    def project_path(self, project: str) -> str:
        """Accepts a numeric id, a path such as group/name, or a web URL of the project."""
        project = project.strip().strip("/")
        if project.startswith(self.base_url + "/"):
            project = project[len(self.base_url) + 1:].split("/-/")[0]
        if not project:
            raise ValueError("Indica el proyecto como grupo/nombre.")
        return "/projects/" + quote(project, safe="")

    def close(self):
        self.http.close()
