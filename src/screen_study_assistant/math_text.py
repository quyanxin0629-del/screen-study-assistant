"""Pure-text math delimiters shared by the answer view and Markdown notes."""

from __future__ import annotations

import re
from dataclasses import dataclass

MAX_FORMULA = 8192
FENCE = re.compile(r" {0,3}(`{3,}|~{3,})[^\n]*(?:\n|$)")


def code_spans(text: str):
    """Yield code ranges, including unclosed fences during streaming."""
    i = 0
    while i < len(text):
        fence = FENCE.match(text, i) if i == 0 or text[i - 1] == "\n" else None
        if fence:
            marker = fence[1]
            close = re.search(
                rf"(?m)^ {{0,3}}{re.escape(marker[0])}{{{len(marker)},}}[ \t]*(?:\n|$)",
                text[fence.end():],
            )
            end = fence.end() + close.end() if close else len(text)
            yield i, end
            i = end
        elif text[i] == "`":
            run = len(text[i:]) - len(text[i:].lstrip("`"))
            close = text.find("`" * run, i + run)
            if close >= 0:
                yield i, close + run
                i = close + run
            else:
                i += run
        elif text[i] == "\\":
            i += 2
        else:
            i += 1


def _closing(text: str, delimiter: str, start: int) -> int:
    end = min(len(text), start + MAX_FORMULA)
    while start < end:
        close = text.find(delimiter, start, end)
        if close < 0:
            return -1
        backslashes = 0
        k = close - 1
        while k >= 0 and text[k] == "\\":
            backslashes += 1
            k -= 1
        if backslashes % 2 == 0:
            return close
        start = close + len(delimiter)
    return -1


@dataclass(frozen=True)
class Formula:
    source: str
    display: bool
    original: str = ""


def _boxed_end(text: str, start: int) -> int | None:
    if not text.startswith(r"\boxed", start):
        return None
    opening = start + len(r"\boxed")
    while opening < len(text) and text[opening].isspace():
        opening += 1
    if opening == len(text) or text[opening] != "{":
        return None
    depth, i = 1, opening + 1
    while i < min(len(text), start + MAX_FORMULA):
        if text[i] == "\\":
            i += 2
            continue
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return None


def split_formulas(text: str) -> list[str | Formula]:
    """Recognize TeX delimiters/boxed answers without interpreting code or currency."""
    parts: list[str | Formula] = []
    start = i = 0
    protected = dict(code_spans(text))
    while i < len(text):
        # Leave fenced and inline code byte-for-byte intact.
        if i in protected:
            i = protected[i]
            continue

        end = None
        formula = None
        # Some text providers emit plain [ \\boxed{…} ] instead of \\[ … \\].
        if text[i] == "[":
            opening = i + 1
            while opening < len(text) and text[opening].isspace():
                opening += 1
            box_end = _boxed_end(text, opening)
            if box_end:
                closing = box_end
                while closing < len(text) and text[closing].isspace():
                    closing += 1
                if closing < len(text) and text[closing] == "]":
                    end = closing + 1
                    formula = Formula(text[opening:box_end], True)
        if formula is None:
            for left, right, display in ((r"\[", r"\]", True), (r"\(", r"\)", False),
                                         ("$$", "$$", True), ("$", "$", False)):
                if not text.startswith(left, i):
                    continue
                opening = i + len(left)
                close = _closing(text, right, opening)
                if close < 0:
                    if left != "$":
                        parts.append(text[start:])
                        return parts
                    break  # Keep incomplete streaming formulas as text.
                content = text[opening:close]
                if left == "$" and (
                    not content or content[0].isspace() or content[-1].isspace()
                    or "\n" in content or (close + 1 < len(text) and text[close + 1].isdigit())
                ):
                    break
                if content.strip():
                    end = close + len(right)
                    formula = Formula(content, display)
                break
        if formula is None:
            box_end = _boxed_end(text, i)
            if box_end:
                end, formula = box_end, Formula(text[i:box_end], False)
        if formula:
            parts.extend((text[start:i], Formula(formula.source, formula.display, text[i:end])))
            i = start = end
        elif text[i] == "\\":
            i += 2  # An escaped delimiter is literal Markdown.
        else:
            i += 1
    parts.append(text[start:])
    return parts


def normalize_math_markdown(text: str) -> str:
    pieces = []
    for part in split_formulas(text):
        if isinstance(part, str):
            pieces.append(part)
        elif part.display:
            pieces.append("\n\n$$\n" + part.source.strip() + "\n$$\n\n")
        else:
            pieces.append("$" + part.source.strip() + "$")
    return "".join(pieces)


