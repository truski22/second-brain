"""Integration plumbing: harness protocol plus the Spanish URL validation used by the Settings UI."""
from urllib.parse import urlparse

from tenet_harness.integrations.base import ConnectionField, Integration, system_tls  # noqa: F401


def https_base_url(value: str) -> str:
    url = urlparse(value.strip())
    if url.scheme != "https" or not url.hostname:
        raise ValueError("La URL debe empezar por https:// e incluir el servidor.")
    if url.username or url.password or url.query or url.fragment:
        raise ValueError("La URL no debe contener credenciales, parámetros ni fragmentos.")
    return f"https://{url.netloc}{url.path.rstrip('/')}"
