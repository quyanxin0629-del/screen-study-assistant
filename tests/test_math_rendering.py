import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QUrl
from PySide6.QtGui import QTextDocument
from PySide6.QtWidgets import QApplication

from screen_study_assistant.math_rendering import MathRenderer
from screen_study_assistant.math_text import Formula, split_formulas
from screen_study_assistant.ui import AnswerWindow


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.mark.parametrize("source", [
    r"\[ \boxed{5} \]", r"$$\boxed{5}$$", r"[ \boxed{5} ]", r"\boxed{5}",
    r"答案为 $\boxed{\frac{5}{2}}$。", r"答案为 \(\boxed{x^2}\)。",
])
def test_boxed_answers_and_nested_braces(source):
    parts = split_formulas(source)
    formulas = [part for part in parts if isinstance(part, Formula)]
    assert len(formulas) == 1
    assert formulas[0].source.strip().startswith(r"\boxed{")
    assert "".join(part.original if isinstance(part, Formula) else part for part in parts) == source


@pytest.mark.parametrize("source", [
    r"用 `\boxed{5}` 写答案，代码 `$x$` 不渲染。",
    "```latex\n\\[ \\boxed{5} \\]\n```\n",
    "~~~text\n$\\boxed{2}$\n~~~\n",
    r"价格 $5 和 $10，或者 \$20。", r"\\boxed{5}",
    r"\[\frac{a}{", r"$x^{", r"\boxed{\frac{5}{", r"\[\boxed{5}",
])
def test_code_currency_escapes_and_incomplete_streams_remain_text(source):
    assert split_formulas(source) == [source]


@pytest.mark.parametrize("source", [
    r"\boxed{5}", r"\boxed{2}", r"\boxed{\frac{5}{2}}",
    r"\sqrt{x^2+1}", r"\begin{pmatrix}1&2\\3&4\end{pmatrix}",
    r"\sum_{i=1}^{n} i = \frac{n(n+1)}{2}",
])
def test_actual_offline_renderer_produces_visible_pixels(app, source):
    renderer = MathRenderer()
    formula = Formula(source, True)
    image = renderer.render(formula, 16)
    assert image is not None and not image.isNull()
    assert any(image.pixelColor(x, y).alpha() for x in range(image.width())
               for y in range(image.height()))
    assert renderer.render(formula, 16) is image


def test_boxed_ui_preserves_copy_source_and_blocks_provider_images(app):
    answer = AnswerWindow()
    answer.start_answer("解释这段内容")
    source = "答案：\n\\[ \\boxed{5} \\]\n另一种问法：\n[ \\boxed{2} ]"
    answer.finish_answer(source)
    assert r"\boxed" not in answer.browser.toPlainText()
    assert answer.browser.toPlainText().count("\ufffc") == 2
    assert "答案" in answer.browser.toPlainText()
    assert "STUDYMATH" not in answer.browser.toPlainText()
    answer.copy_answer()
    assert app.clipboard().text() == source
    for url in ("https://example.invalid/image.png", "file:///etc/passwd"):
        document = answer.browser.bubbles[-1].body.document()
        assert document.resource(QTextDocument.ImageResource, QUrl(url)) is None
    answer.deleteLater()


def test_invalid_formula_falls_back_without_breaking_answer(app):
    answer = AnswerWindow()
    answer.start_answer("解释这段内容")
    answer.finish_answer(r"前文 $\unknowncommand{5}$ 后文")
    assert "前文" in answer.browser.toPlainText() and "后文" in answer.browser.toPlainText()
    assert r"\unknowncommand" in answer.browser.toPlainText()
    assert answer.send.isEnabled()
    answer.deleteLater()


def test_escaped_dollar_within_math_is_not_a_closing_delimiter():
    parts = split_formulas(r"示例 $x + \$5$。")
    assert [p.source for p in parts if isinstance(p, Formula)] == [r"x + \$5"]
