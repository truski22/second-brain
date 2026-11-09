$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
& npm --prefix frontend run build
if ($LASTEXITCODE -ne 0) { throw "Frontend build failed" }
& .\.venv\Scripts\python.exe -m PyInstaller --noconfirm --log-level INFO --onedir `
    --name second-brain-backend --paths src --add-data "frontend\dist;frontend\dist" `
    --collect-data whisper --collect-data dateparser --collect-data langchain_core `
    --collect-submodules langgraph.checkpoint.sqlite --copy-metadata langgraph `
    --collect-submodules keyring.backends --copy-metadata keyring `
    --copy-metadata langchain-core --copy-metadata langchain-ollama `
    --collect-submodules chromadb.api --collect-submodules chromadb.segment `
    --collect-submodules chromadb.execution --collect-submodules chromadb.telemetry `
    --exclude-module gradio --exclude-module matplotlib --exclude-module pandas `
    --exclude-module transformers --exclude-module sentence_transformers `
    --exclude-module tensorboard --exclude-module IPython --exclude-module tkinter `
    --exclude-module pytest `
    scripts\backend.py
if ($LASTEXITCODE -ne 0) { throw "Python sidecar build failed" }
$target = (rustc -vV | Select-String '^host:').ToString().Split(' ')[1]
New-Item -ItemType Directory -Force frontend\src-tauri\binaries | Out-Null
Copy-Item dist\second-brain-backend\second-brain-backend.exe "frontend\src-tauri\binaries\second-brain-backend-$target.exe"
& .\.venv\Scripts\python.exe scripts\packaged-smoke.py
if ($LASTEXITCODE -ne 0) { throw "Packaged application smoke test failed" }
