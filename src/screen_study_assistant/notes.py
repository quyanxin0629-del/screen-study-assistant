"""Human-readable Markdown is the only persistent learning data format."""

from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from datetime import datetime
from pathlib import Path
from threading import Lock

import yaml

from .math_text import Formula, code_spans, normalize_math_markdown, split_formulas

_APPEND_LOCK = Lock()
_LEGACY_ENTRY = re.compile(
    r"(?m)^<!-- entry:([a-f0-9]{32}) -->[ \t]*\r?\n"
    r"(?=\*\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\*\r?\n)"
)


def format_question(question: str) -> str:
    # Bold literal question text without creating Markdown titles or remote resources.
    def escape(line):
        return re.sub(r"([\\`*_{}\[\]<>#])", r"\\\1", line)

    return "\n".join(
        "**" + escape(line) + "**" for line in question.strip().splitlines() if line.strip()
    )


def format_note_question(question: str) -> str:
    pieces = []
    for part in split_formulas(question.strip()):
        if isinstance(part, Formula):
            pieces.append(normalize_math_markdown(part.original))
        elif part.strip():
            leading = re.match(r"\s*", part)[0].replace("\n", "  \n")
            trailing = re.search(r"\s*$", part)[0].replace("\n", "  \n")
            pieces.append(leading + format_question(part).replace("\n", "  \n") + trailing)
        else:
            pieces.append(part.replace("\n", "  \n"))
    return "".join(pieces)


def format_note_answer(answer: str) -> str:
    """Change presentation only; leave wording, math content and code intact."""
    text = normalize_math_markdown(answer.strip())

    def tidy(chunk):
        def heading(match):
            title = match[1].strip()
            return title if title.startswith("**") and title.endswith("**") else f"**{title}**"

        chunk = re.sub(r"(?m)^ {0,3}#{1,6}[ \t]+(.+?)(?:[ \t]+#+)?[ \t]*$", heading, chunk)
        chunk = re.sub(r"(?m)^([^\n]+)\n {0,3}(?:=+|-{3,})[ \t]*$", heading, chunk)
        chunk = re.sub(r"(?is)<h[1-6](?:\s[^>]*)?>(.*?)</h[1-6]>", heading, chunk)
        chunk = re.sub(r"\n[ \t]*\n(?:[ \t]*\n)+", "\n\n", chunk)
        return chunk

    pieces, start = [], 0
    for left, right in code_spans(text):
        pieces.extend((tidy(text[start:left]), text[left:right]))
        start = right
    pieces.append(tidy(text[start:]))
    return "".join(pieces)


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def slug(value: str) -> str:
    return re.sub(r'[\\/:*?"<>|\x00-\x1f]', "-", value).strip(" .")[:45] or "学习问答"


def normalized(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().casefold()


def read_markdown(path: Path) -> tuple[dict, str]:
    content = path.read_text(encoding="utf-8")
    if not content.startswith("---\n"):
        raise ValueError("Missing metadata")
    _, front, body = content.split("---\n", 2)
    metadata = yaml.safe_load(front)
    if not isinstance(metadata, dict):
        raise ValueError("Invalid metadata")
    return metadata, body


def write_markdown(path: Path, metadata: dict, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        "---\n" + yaml.safe_dump(metadata, allow_unicode=True, sort_keys=False) + "---\n" + body,
        encoding="utf-8",
    )
    temporary.replace(path)


class NoteStore:
    def __init__(self, directory: str | Path):
        self.directory = Path(directory).expanduser()

    @property
    def qa_path(self) -> Path:
        return self.directory / "学习笔记.md"

    @property
    def index_path(self) -> Path:
        return self.directory / ".学习笔记索引.json"

    def _load_index(self):
        if not self.index_path.exists():
            return {"version": 1, "entries": {}}
        index = json.loads(self.index_path.read_text(encoding="utf-8"))
        if index.get("version") != 1 or not isinstance(index.get("entries"), dict):
            raise ValueError("Invalid notebook index")
        return index

    def _save_index(self, index):
        temporary = self.index_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")
        temporary.replace(self.index_path)

    def _prepare_locked(self):
        self.directory.mkdir(parents=True, exist_ok=True)
        self.qa_path.touch(exist_ok=True)
        index = self._load_index()
        text = self.qa_path.read_text(encoding="utf-8")
        protected = list(code_spans(text))
        markers = [m for m in _LEGACY_ENTRY.finditer(text)
                   if not any(left <= m.start() < right for left, right in protected)]
        if markers:
            pieces = [text[:markers[0].start()]]
            for n, marker in enumerate(markers):
                end = markers[n + 1].start() if n + 1 < len(markers) else len(text)
                pieces.append(format_note_answer(text[marker.end():end]) + "\n")
                index["entries"].setdefault(marker[1], {"state": "done"})
            backup = self.directory / ".学习笔记排版前备份.md"
            if not backup.exists():
                backup.write_text(text, encoding="utf-8")
            # Persist deduplication before removing visible legacy identifiers.
            self._save_index(index)
            temporary = self.qa_path.with_suffix(".tmp")
            temporary.write_text("".join(pieces), encoding="utf-8")
            temporary.replace(self.qa_path)
        self._recover_sessions_locked(index)
        return index

    def _replace_notebook(self, text):
        temporary = self.qa_path.with_suffix(".tmp")
        with temporary.open("w", encoding="utf-8", newline="") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(self.qa_path)

    def _read_notebook(self):
        with self.qa_path.open(encoding="utf-8", newline="") as stream:
            return stream.read()

    def _recover_sessions_locked(self, index):
        for record in index["entries"].values():
            pending = record.get("pending") if record.get("kind") == "session" else None
            if not pending:
                continue
            text = self._read_notebook()
            digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
            if digest == pending["before_hash"]:
                old = record.get("content", "")
                if old:
                    if text.count(old) != 1:
                        raise OSError("笔记已被外部修改，保留现有内容")
                    text = text.replace(old, pending["content"], 1)
                else:
                    text += pending["content"]
                self._replace_notebook(text)
            elif digest != pending["after_hash"]:
                raise OSError("笔记已被外部修改，保留现有内容")
            record.update({key: pending[key] for key in ("content", "revision", "organized")})
            record["state"] = "done"
            del record["pending"]
            self._save_index(index)

    def save_session(self, question: str, answer: str, session_id: str, timestamp: str,
                     revision: int, organized: bool = False) -> Path:
        """Replace only this capture's entry; journal before atomic notebook replacement."""
        if not re.fullmatch(r"[a-f0-9]{32}", session_id) or revision < 1:
            raise ValueError("Invalid note session")
        entry = (f"\n*{timestamp}*\n\n{format_note_question(question)}\n\n"
                 f"{format_note_answer(answer)}\n\n---\n")
        with _APPEND_LOCK:
            index = self._prepare_locked()
            record = index["entries"].get(session_id)
            if record and record.get("kind") != "session":
                raise ValueError("Conflicting note session identifier")
            if record and (revision, organized) <= (record["revision"], record["organized"]):
                return self.qa_path  # a delayed summary cannot overwrite newer follow-ups
            text = self._read_notebook()
            old = record["content"] if record else ""
            if old:
                if text.count(old) != 1:
                    raise OSError("当前笔记已被外部修改，保留现有内容")
                replacement = text.replace(old, entry, 1)
            else:
                replacement = text + entry
            if not record:
                record = {"kind": "session", "state": "pending", "content": "",
                          "revision": 0, "organized": False}
                index["entries"][session_id] = record
            record["pending"] = {
                "content": entry, "revision": revision, "organized": organized,
                "before_hash": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                "after_hash": hashlib.sha256(replacement.encode("utf-8")).hexdigest(),
            }
            self._save_index(index)
            self._recover_sessions_locked(index)
        return self.qa_path

    def prepare_notebook(self) -> Path:
        """Clean legacy entries in the same background queue used for appending."""
        with _APPEND_LOCK:
            self._prepare_locked()
        return self.qa_path

    def append_qa(self, question: str, answer: str, entry_id: str, timestamp: str) -> Path:
        """Append one completed turn; never rewrite earlier or manually edited entries."""
        if not re.fullmatch(r"[a-f0-9]{32}", entry_id):
            raise ValueError("Invalid note entry identifier")
        entry = (
            f"\n*{timestamp}*\n\n{format_note_question(question)}\n\n"
            f"{format_note_answer(answer)}\n\n---\n"
        )
        payload = entry.encode("utf-8")
        digest = hashlib.sha256(payload).hexdigest()
        with _APPEND_LOCK:
            index = self._prepare_locked()
            record = index["entries"].get(entry_id)
            if record:
                if record.get("hash") not in (None, digest):
                    raise ValueError("Conflicting note entry identifier")
                if record["state"] == "done":
                    return self.qa_path
            with self.qa_path.open("r+b") as stream:
                if record:
                    stream.seek(record["offset"])
                    existing = stream.read(len(payload))
                    if existing == payload:
                        record["state"] = "done"
                        self._save_index(index)
                        return self.qa_path
                    if existing:
                        raise OSError("Unfinished note write; existing text has been preserved")
                else:
                    stream.seek(0, 2)
                    record = {"state": "pending", "offset": stream.tell(), "hash": digest}
                    index["entries"][entry_id] = record
                    self._save_index(index)
                stream.seek(0, 2)
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            record["state"] = "done"
            self._save_index(index)
        return self.qa_path

    def find_concept(self, text: str) -> tuple[Path, dict, str] | None:
        candidates = {normalized(text)}
        # The complete OCR span must match: avoid matching a word out of a long passage.
        if len(text.strip()) > 100:
            return None
        matches = []
        for path in (self.directory / "知识图鉴").glob("*.md"):
            try:
                meta, body = read_markdown(path)
                names = [meta.get("name", "")] + (meta.get("aliases") or [])
                if any(isinstance(n, str) and normalized(n) in candidates for n in names):
                    matches.append((path, meta, body))
            except (OSError, ValueError, yaml.YAMLError):
                continue
        return matches[0] if len(matches) == 1 else None

    def upsert_concept(
        self, card: dict, qa_path: Path, existing=None, qa_id: str | None = None
    ) -> tuple[Path, dict, str]:
        name = card["name"].strip()[:60]
        existing = existing or self.find_concept(name)
        if existing:
            path, meta, body = existing
        else:
            identifier = uuid.uuid4().hex
            path = self.directory / "知识图鉴" / f"{slug(name)}-{identifier[:6]}.md"
            aliases = card.get("aliases", [])
            meta = {
                "schema_version": 1,
                "id": identifier,
                "name": name,
                "aliases": [a[:100] for a in aliases if isinstance(a, str)]
                if isinstance(aliases, list)
                else [],
                "status": "初次遇见",
                "tags": card.get("tags", []),
                "created_at": now(),
                "updated_at": now(),
                "encounters": [],
            }
            body = f"\n# {name}\n\n## 一句话解释\n\n{str(card.get('summary', ''))}\n\n## 详细解释\n\n{str(card.get('explanation', ''))}\n\n## 我的理解\n\n"
        # Legacy files retain their metadata; new aggregate entries use a session ID.
        qa_meta, qa_body = read_markdown(qa_path) if qa_id is None else ({}, "")
        qa_id = qa_id or qa_meta["id"]
        encounters = meta.setdefault("encounters", [])
        if not any(e.get("qa_id") == qa_id for e in encounters):
            encounters.append({"time": now(), "qa_id": qa_id, "source": None, "note": qa_path.name})
        meta["updated_at"] = now()
        write_markdown(path, meta, body)
        if qa_meta:
            qa_meta["concept_id"] = meta["id"]
            write_markdown(qa_path, qa_meta, qa_body)
        return path, meta, body
