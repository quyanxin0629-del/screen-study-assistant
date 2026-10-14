#!/bin/zsh
set -e
cd "${0:A:h:h}"
# Ad-hoc signatures identify a particular binary hash, so replacing an authorized
# build invalidates macOS privacy grants even when its bundle ID is unchanged.
sign_args=()
if [[ -n "${SCREEN_STUDY_SIGNING_IDENTITY:-}" ]]; then
  sign_args=(--codesign-identity "$SCREEN_STUDY_SIGNING_IDENTITY")
elif [[ -d dist/ScreenStudyAssistant.app && "${SCREEN_STUDY_ALLOW_ADHOC_UPDATE:-0}" != 1 ]]; then
  print -u2 "当前应用没有稳定签名。直接覆盖会使已授予的录屏权限失效，已保留现有应用。"
  print -u2 "请先设置 SCREEN_STUDY_SIGNING_IDENTITY 为有效的代码签名证书。"
  print -u2 "仅在接受更新后重新授权的开发测试中，使用 SCREEN_STUDY_ALLOW_ADHOC_UPDATE=1。"
  exit 2
else
  print -u2 "正在生成临时签名的开发版；未来更新可能需要重新授予录屏权限。"
fi
.venv/bin/python -m pip install '.[build]'
.venv/bin/python -m PyInstaller --noconfirm --windowed --onedir \
  --name ScreenStudyAssistant --osx-bundle-identifier com.screenstudy.assistant \
  --hidden-import keyring.backends.macOS --hidden-import Vision --hidden-import Quartz --hidden-import AppKit \
  --exclude-module PySide6.QtWebEngineCore --exclude-module PySide6.QtWebEngineWidgets \
  --exclude-module PySide6.QtPdf --exclude-module PySide6.QtPdfWidgets \
  --exclude-module rapidocr --exclude-module onnxruntime --exclude-module cv2 \
  --collect-data screen_study_assistant "${sign_args[@]}" \
  --paths src run_desktop.py
