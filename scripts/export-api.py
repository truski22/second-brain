import json
from pathlib import Path

from second_brain_app.api import create_app
from second_brain_app.config import Settings

target = Path(__file__).resolve().parents[1] / "build" / "openapi.json"
target.parent.mkdir(exist_ok=True)
target.write_text(json.dumps(create_app(token="schema-only-token-not-for-runtime", port=8765,
                                      settings=Settings(target.parent / "schema-data")).openapi(), indent=2),
                  encoding="utf-8")
