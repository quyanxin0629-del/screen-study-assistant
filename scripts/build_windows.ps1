$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)
if (-not (Test-Path ".venv\Scripts\python.exe")) {
    py -3 -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw "Failed to create Python environment" }
}
& .venv\Scripts\python.exe -m pip uninstall -y rapidocr-onnxruntime onnxruntime onnxruntime-gpu onnxruntime-directml
& .venv\Scripts\python.exe -m pip install -e ".[ocr,build]"
if ($LASTEXITCODE -ne 0) { throw "Failed to install dependencies" }
& .venv\Scripts\python.exe -m PyInstaller --noconfirm --windowed --onedir `
    --name ScreenStudyAssistant --paths src --collect-all rapidocr --collect-all onnxruntime `
    --collect-data screen_study_assistant `
    --hidden-import keyring.backends.Windows run_desktop.py
if ($LASTEXITCODE -ne 0) { throw "Application build failed" }
