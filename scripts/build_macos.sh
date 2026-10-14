#!/bin/zsh
set -e
cd "${0:A:h:h}"
.venv/bin/python -m pip install '.[build]'
.venv/bin/python -m PyInstaller --noconfirm --windowed --onedir \
  --name ScreenStudyAssistant --osx-bundle-identifier com.screenstudy.assistant \
  --hidden-import keyring.backends.macOS --hidden-import Vision --hidden-import Quartz --hidden-import AppKit \
  --exclude-module PySide6.QtWebEngineCore --exclude-module PySide6.QtWebEngineWidgets \
  --exclude-module PySide6.QtPdf --exclude-module PySide6.QtPdfWidgets \
  --exclude-module rapidocr --exclude-module onnxruntime --exclude-module cv2 \
  --collect-data screen_study_assistant \
  --paths src run_desktop.py
