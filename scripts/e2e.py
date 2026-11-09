"""Run real browser UI against synthetic services, without personal data or model calls."""
import os
import secrets
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import uvicorn
from langchain_core.messages import AIMessage

from second_brain_app.api import create_app
from second_brain_app.config import Settings


class Model:
    def bind_tools(self, tools):
        return self

    def invoke(self, messages):
        return AIMessage(content="Respuesta local.")


class Provider:
    model = "fake"

    def chat(self, structured=False):
        return Model()


class Memory:
    def __init__(self, *args):
        pass

    def search(self, *args, **kwargs):
        return []

    def list(self, *args):
        return []

    def memorize(self, job):
        return []


def main():
    root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory() as directory, socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        token = secrets.token_urlsafe(32)
        app = create_app(token=token, port=port, settings=Settings(Path(directory)),
                         provider=Provider(), memory_factory=Memory)
        server = uvicorn.Server(uvicorn.Config(app, access_log=False, log_level="warning"))
        thread = threading.Thread(target=lambda: server.run(sockets=[listener]))
        thread.start()
        try:
            for _ in range(100):
                if server.started:
                    break
                time.sleep(.05)
            if not server.started:
                raise RuntimeError("Synthetic test server did not start.")
            env = {**os.environ, "SECOND_BRAIN_E2E_URL": f"http://127.0.0.1:{port}/#token={token}"}
            command = [str(root / "frontend" / "node_modules" / ".bin" / "playwright.cmd"), "test"]
            result = subprocess.run(command, cwd=root / "frontend", env=env, check=False)
        finally:
            server.should_exit = True
            thread.join(timeout=10)
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
