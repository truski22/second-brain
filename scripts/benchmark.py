"""Measure app startup/idle memory and a synthetic local run without legacy data."""
import ctypes
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from uuid import uuid4

import httpx


class MemoryCounters(ctypes.Structure):
    _fields_ = [("cb", ctypes.c_ulong), ("PageFaultCount", ctypes.c_ulong),
                ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]


def working_set(process):
    counters = MemoryCounters()
    counters.cb = ctypes.sizeof(counters)
    psapi = ctypes.windll.psapi
    psapi.GetProcessMemoryInfo.argtypes = [ctypes.c_void_p, ctypes.POINTER(MemoryCounters), ctypes.c_ulong]
    children = subprocess.check_output([
        "powershell", "-NoProfile", "-Command",
        f"(Get-CimInstance Win32_Process -Filter 'ParentProcessId = {process.pid}').ProcessId",
    ], text=True).split()
    kernel = ctypes.windll.kernel32
    kernel.OpenProcess.restype = ctypes.c_void_p
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    total = 0
    for pid in [process.pid, *(int(child) for child in children)]:
        handle = kernel.OpenProcess(0x0410, False, pid)
        if not handle:
            raise ctypes.WinError()
        try:
            if not psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb):
                raise ctypes.WinError()
            total += counters.WorkingSetSize
        finally:
            kernel.CloseHandle(handle)
    return round(total / (1024 * 1024), 2)


def main():
    root = Path(__file__).resolve().parents[1]
    records = []
    for launch in range(2):
        with tempfile.TemporaryDirectory() as data:
            started = time.perf_counter()
            process = subprocess.Popen(
                [sys.executable, "-m", "second_brain_app.launcher", "--no-browser"],
                cwd=root, env={**os.environ, "SECOND_BRAIN_DATA_DIR": data},
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            )
            try:
                info = json.loads(process.stdout.readline())
                base, token = info["url"].split("/#token=")
                with httpx.Client(base_url=base, timeout=130, trust_env=False) as client:
                    for _ in range(100):
                        try:
                            client.get("/health").raise_for_status()
                            break
                        except httpx.HTTPError:
                            time.sleep(.05)
                    startup = time.perf_counter() - started
                    response = client.post("/auth", json={"token": token})
                    response.raise_for_status()
                    client.headers["Authorization"] = "Bearer " + response.json()["session"]
                    record = {"launch": launch + 1, "startup_seconds": round(startup, 3),
                              "idle_working_set_mib": working_set(process), "runs": []}
                    for number in range(2):
                        run_id = str(uuid4())
                        begin = time.perf_counter()
                        response = client.post("/api/runs", json={
                            "run_id": run_id, "thread_id": f"benchmark-{number}", "text": "Hola, responde brevemente.",
                        })
                        response.raise_for_status()
                        first, reply, memory = None, None, None
                        with client.stream("GET", f"/api/runs/{run_id}/events") as stream:
                            stream.raise_for_status()
                            for line in stream.iter_lines():
                                event = json.loads(line)
                                elapsed = time.perf_counter() - begin
                                if event["type"] in {"token", "reply"} and first is None:
                                    first = elapsed
                                if event["type"] == "reply":
                                    reply = elapsed
                                if event["type"] == "memory_saved":
                                    memory = elapsed
                                if event["type"] in {"error", "memory_failed"}:
                                    raise RuntimeError(event.get("message", event["type"]))
                        record["runs"].append({
                            "first_text_seconds": round(first, 3), "reply_seconds": round(reply, 3),
                            "post_reply_memory_seconds": round(memory - reply, 3) if memory else None,
                        })
                        if memory is None:
                            raise RuntimeError("Stream closed without its terminal memory event.")
                    records.append(record)
            finally:
                process.terminate()
                process.wait(timeout=15)
    print(json.dumps({"model": "qwen2.5:7b", "mode": "source backend; voice not loaded",
                      "note": "App restarts, not OS-cache-cold measurements; no legacy performance comparison.",
                      "measurements": records}, indent=2))


if __name__ == "__main__":
    main()
