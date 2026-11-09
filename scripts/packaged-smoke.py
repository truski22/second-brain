"""Exercise frozen backend/API/Chroma using disposable data; never print session tokens."""
import json
import os
import re
import subprocess
import tempfile
import time
from pathlib import Path

import httpx


def main():
    root = Path(__file__).resolve().parents[1]
    exe = root / "dist" / "second-brain-backend" / "second-brain-backend.exe"
    with tempfile.TemporaryDirectory() as directory:
        log = Path(directory) / "stderr.log"
        with log.open("w", encoding="utf-8") as errors:
            process = subprocess.Popen([str(exe), "--no-browser"], stdout=subprocess.PIPE, stderr=errors,
                                       text=True, env={**os.environ, "SECOND_BRAIN_DATA_DIR": directory})
            try:
                line = process.stdout.readline()
                if not line:
                    raise RuntimeError("Packaged backend failed: " + log.read_text(encoding="utf-8"))
                url = json.loads(line)["url"]
                base, token = url.split("/#token=")
                with httpx.Client(base_url=base, timeout=30, trust_env=False) as client:
                    for _ in range(100):
                        try:
                            response = client.get("/health")
                            response.raise_for_status()
                            break
                        except httpx.HTTPError:
                            if process.poll() is not None:
                                raise RuntimeError(log.read_text(encoding="utf-8"))
                            time.sleep(.2)
                    else:
                        raise RuntimeError("Packaged readiness timed out.")
                    response = client.post("/auth", json={"token": token})
                    response.raise_for_status()
                    client.headers["Authorization"] = "Bearer " + response.json()["session"]
                    response = client.get("/")
                    response.raise_for_status()
                    for asset in re.findall(r'(?:src|href)="(/assets/[^"]+)"', response.text):
                        client.get(asset).raise_for_status()
                    for endpoint in ("/api/conversations", "/api/memories", "/api/reminders", "/api/status"):
                        response = client.get(endpoint)
                        if not response.is_success:
                            raise RuntimeError(f"{endpoint}: {response.text}; " + log.read_text(encoding="utf-8"))
                    print("Frozen backend: health, authentication, frontend assets, Chroma and APIs passed.")
            finally:
                process.terminate()
                process.wait(timeout=15)


if __name__ == "__main__":
    main()
