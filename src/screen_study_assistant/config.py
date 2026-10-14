"""Local settings; secrets are stored separately in the OS credential vault."""

from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import keyring


def app_directory() -> Path:
    if os.name == "nt":
        return Path(os.getenv("APPDATA", str(Path.home()))) / "ScreenStudyAssistant"
    if __import__("sys").platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "ScreenStudyAssistant"
    return (
        Path(os.getenv("XDG_CONFIG_HOME", str(Path.home() / ".config"))) / "screen-study-assistant"
    )


def normalize_url(value: str) -> str:
    value = value.strip().rstrip("/")
    parts = urlsplit(value)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError("请填写有效的 http:// 或 https:// API 地址。")
    if parts.username or parts.password or parts.query or parts.fragment:
        raise ValueError("API 地址不能包含密码、查询参数或 # 标记。")
    path = parts.path.rstrip("/")
    if path.endswith("/chat/completions"):
        path = path.removesuffix("/chat/completions")
    return urlunsplit((parts.scheme, parts.netloc.lower(), path, "", ""))


def normalize_shortcut(value: str) -> str:
    parts = [part.strip() for part in value.split("+")]
    if len(parts) < 2 or "," in value:
        raise ValueError("快捷键需要一个组合键，例如 Command + Shift + K。")
    modifiers, key = parts[:-1], parts[-1]
    allowed = ["Meta", "Ctrl", "Alt", "Shift"]
    if any(modifier not in allowed for modifier in modifiers) or len(set(modifiers)) != len(
        modifiers
    ):
        raise ValueError("快捷键只能包含 Command、Ctrl、Option / Alt、Shift 修饰键。")
    if not any(modifier in modifiers for modifier in ("Meta", "Ctrl", "Alt")):
        raise ValueError("请包含 Command、Ctrl 或 Option / Alt，避免影响正常打字。")
    if not re.fullmatch(r"[A-Za-z0-9]|F(?:[1-9]|1[0-2])|Space", key):
        raise ValueError("主键支持字母、数字、空格或 F1–F12。")
    key = key.upper() if len(key) == 1 else key
    return "+".join([modifier for modifier in allowed if modifier in modifiers] + [key])


@dataclass
class Settings:
    api_url: str = ""
    model: str = ""
    notes_dir: str = str(Path.home() / "Documents" / "屏幕学习笔记")
    shortcut: str = "Meta+Shift+K" if sys.platform == "darwin" else "Ctrl+Shift+K"

    ocr_device: str = "auto"

    def validate(self) -> "Settings":
        url = normalize_url(self.api_url) if self.api_url.strip() else ""
        if bool(url) != bool(self.model.strip()):
            raise ValueError("API URL 与模型名称需要一起填写；也可以先留空，只保存快捷键。")
        if self.ocr_device not in ("auto", "cpu"):
            raise ValueError("OCR 模式需要选择自动或 CPU。")
        return Settings(
            url,
            self.model.strip(),
            self.notes_dir,
            normalize_shortcut(self.shortcut),
            self.ocr_device,
        )


class ConfigStore:
    service = "screen-study-assistant"

    def __init__(self, directory: Path | None = None):
        self.directory = directory or app_directory()
        self._key_url = None
        self._key_value = ""

    def load(self) -> Settings:
        path = self.directory / "settings.json"
        if not path.exists():
            return Settings()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return Settings(
                **{k: v for k, v in data.items() if k in asdict(Settings()) and isinstance(v, str)}
            )
        except (ValueError, TypeError) as exc:
            raise ValueError("本地设置文件损坏，请重新保存设置。") from exc

    def get_key(self, url: str) -> str:
        if not url:
            return ""
        endpoint = normalize_url(url)
        if endpoint != self._key_url:
            value = keyring.get_password(self.service, endpoint) or ""
            self._key_url, self._key_value = endpoint, value
        return self._key_value

    def forget_key(self) -> None:
        self._key_url, self._key_value = None, ""

    def save(self, settings: Settings, key: str | None = None, clear_key: bool = False) -> None:
        settings = settings.validate()
        if key and not settings.api_url:
            raise ValueError("保存 API Key 前，请先填写 API URL 和模型名称。")
        if clear_key and settings.api_url:
            try:
                keyring.delete_password(self.service, settings.api_url)
            except keyring.errors.PasswordDeleteError:
                pass
            self._key_url, self._key_value = settings.api_url, ""
        elif key is not None:
            keyring.set_password(self.service, settings.api_url, key)
            self._key_url, self._key_value = settings.api_url, key
        elif self._key_url != settings.api_url:
            self.forget_key()
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.directory / "settings.json"
        temporary = path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(asdict(settings), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        temporary.chmod(0o600)
        temporary.replace(path)
