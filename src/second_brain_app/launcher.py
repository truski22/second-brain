import argparse
import json
import logging
from logging.handlers import RotatingFileHandler
import secrets
import socket
import threading
import webbrowser

import uvicorn


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--prepare-voice", action="store_true")
    parser.add_argument("--parent-pid", type=int)
    args = parser.parse_args()
    from second_brain_app.config import Settings
    settings = Settings.load()
    if args.prepare_voice:
        from second_brain_app.voice import Voice
        Voice(settings).prepare()
        print("Local voice assets ready.")
        return
    from second_brain_app.instance import InstanceLock
    instance = InstanceLock(settings.data_dir)
    handler = RotatingFileHandler(settings.data_dir / "application.log", maxBytes=2_000_000,
                                  backupCount=2, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    logging.getLogger().addHandler(handler)
    logging.getLogger().setLevel(logging.WARNING)
    probe = socket.socket()
    probe.bind(("127.0.0.1", args.port))
    port = probe.getsockname()[1]
    token = secrets.token_urlsafe(32)
    from second_brain_app.api import create_app

    app = create_app(token=token, port=port, settings=settings)
    url = f"http://127.0.0.1:{port}/#token={token}"
    # Private parent-process pipe, never a file log.
    print(json.dumps({"url": url}), flush=True)
    if not args.no_browser:
        threading.Timer(1, lambda: webbrowser.open(url)).start()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port,
                                          access_log=False, log_level="warning"))
    if args.parent_pid:
        def watch_parent():
            import ctypes
            kernel = ctypes.windll.kernel32
            kernel.OpenProcess.restype = ctypes.c_void_p
            handle = kernel.OpenProcess(0x00100000, False, args.parent_pid)
            if not handle:
                server.should_exit = True
                return
            kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
            kernel.WaitForSingleObject(handle, 0xFFFFFFFF)
            kernel.CloseHandle.argtypes = [ctypes.c_void_p]
            kernel.CloseHandle(handle)
            server.should_exit = True
        threading.Thread(target=watch_parent, daemon=True).start()
    try:
        server.run(sockets=[probe])
    finally:
        probe.close()
        instance.close()
        logging.getLogger().removeHandler(handler)
        handler.close()


if __name__ == "__main__":
    main()
