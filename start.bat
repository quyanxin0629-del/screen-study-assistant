@echo off
cd /d "%~dp0"
if exist "dist\ScreenStudyAssistant\ScreenStudyAssistant.exe" (
  start "" "dist\ScreenStudyAssistant\ScreenStudyAssistant.exe"
  exit /b
)
if not exist ".venv\Scripts\python.exe" (
  py -3 -m venv .venv
  if errorlevel 1 exit /b 1
)
.venv\Scripts\python.exe -c "import screen_study_assistant, PySide6, rapidocr, onnxruntime; assert 'DmlExecutionProvider' in onnxruntime.get_available_providers()" >nul 2>&1
if errorlevel 1 (
  .venv\Scripts\python.exe -m pip uninstall -y rapidocr-onnxruntime onnxruntime onnxruntime-gpu onnxruntime-directml
  .venv\Scripts\python.exe -m pip install -e ".[ocr]"
  if errorlevel 1 exit /b 1
)
start "" .venv\Scripts\pythonw.exe -m screen_study_assistant
