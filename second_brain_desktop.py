"""Desktop launcher: runs the Tauri build, or browser mode with --web."""
import argparse
import subprocess
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="Second Brain desktop launcher")
    parser.add_argument("--web", action="store_true", help="Open the shared app in a local browser")
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    try:
        from dotenv import load_dotenv
    except ImportError:
        raise SystemExit("Install project dependencies first: python -m pip install uv; uv sync --locked --extra voice")
    load_dotenv(root / ".env")
    if args.web:
        raise SystemExit(subprocess.call([sys.executable, "-m", "second_brain_app.launcher"], cwd=root))
    candidates = [
        root / "frontend" / "src-tauri" / "target" / profile / "second-brain-desktop.exe"
        for profile in ("release", "debug")
    ]
    executable = next((path for path in candidates if path.is_file()), None)
    if executable is None:
        raise SystemExit(
            "Desktop build not found. Run npm --prefix frontend run build; "
            ".\\scripts\\build-sidecar.ps1; npm --prefix frontend run desktop:build. "
            "Browser mode: python second_brain_desktop.py --web"
        )
    raise SystemExit(subprocess.call([str(executable)], cwd=executable.parent))


if __name__ == "__main__":
    main()
