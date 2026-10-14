#!/bin/zsh
set -e
cd "${0:A:h}"
if [[ -d dist/ScreenStudyAssistant.app ]]; then
  exec open "$PWD/dist/ScreenStudyAssistant.app"
fi
if [[ ! -x .venv/bin/python ]]; then
  python3 -m venv .venv
fi
if ! .venv/bin/python -c 'import screen_study_assistant, PySide6, httpx' >/dev/null 2>&1; then
  .venv/bin/python -m pip install -e .
fi
exec .venv/bin/python -m screen_study_assistant
