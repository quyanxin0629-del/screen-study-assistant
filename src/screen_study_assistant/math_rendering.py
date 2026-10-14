"""Offline TeX → SVG → Qt images; original Markdown remains the source of truth."""

from __future__ import annotations

import gzip
import json
from collections import OrderedDict
from pathlib import Path

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtQml import QJSEngine, QJSValue
from PySide6.QtSvg import QSvgRenderer

from .math_text import MAX_FORMULA, Formula


class MathRenderer:
    """Runs a bundled MathJax module in Qt's isolated JS engine (no Node required)."""

    def __init__(self):
        self.engine = None
        self.function = None
        self.cache = OrderedDict()

    def render(self, formula: Formula, font_size: float) -> QImage | None:
        key = (formula, round(font_size, 2))
        if key in self.cache:
            self.cache.move_to_end(key)
            return self.cache[key]
        image = self._render(formula, font_size)
        self.cache[key] = image
        if len(self.cache) > 128:
            self.cache.popitem(last=False)
        return image

    def _render(self, formula: Formula, font_size: float) -> QImage | None:
        if len(formula.source) > MAX_FORMULA:
            return None
        if self.engine is None:
            engine = QJSEngine()
            path = Path(__file__).parent / "assets" / "math" / "renderer.js.gz"
            source = gzip.decompress(path.read_bytes()).decode("utf-8")
            result = engine.evaluate(source, str(path))
            if result.isError():
                raise RuntimeError(result.toString())
            self.function = engine.globalObject().property("StudyMath").property("render")
            self.engine = engine
        result = self.function.call([QJSValue(formula.source), QJSValue(formula.display)])
        if result.isError():
            return None
        data = json.loads(result.toString())
        # MathJax's ex units correspond to half of the chosen text font's em.
        width = float(data["width"].removesuffix("ex")) * font_size * 0.5
        height = float(data["height"].removesuffix("ex")) * font_size * 0.5
        if not (0 < width <= 4096 and 0 < height <= 2048):
            return None
        svg = data["svg"].replace("currentColor", "#242A35")
        renderer = QSvgRenderer(QByteArray(svg.encode()))
        if not renderer.isValid():
            return None
        scale = 2.0
        image = QImage(max(1, round(width * scale)), max(1, round(height * scale)),
                       QImage.Format_ARGB32_Premultiplied)
        image.fill(Qt.transparent)
        painter = QPainter(image)
        renderer.render(painter, QRectF(0, 0, image.width(), image.height()))
        painter.end()
        image.setDevicePixelRatio(scale)
        return image
