import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from screen_study_assistant.launcher import LauncherWindow


def test_capsule_unfolds_without_triggering_actions_and_keeps_existing_labels():
    app = QApplication.instance() or QApplication([])
    window = LauncherWindow()
    calls = []
    window.capture_requested.connect(lambda: calls.append("capture"))
    window.settings_requested.connect(lambda: calls.append("settings"))
    window.notes_requested.connect(lambda: calls.append("notes"))
    window.show()
    app.processEvents()
    try:
        assert not window.expanded and not window.capture_button.isVisible()
        assert window.width() == window.COMPACT_WIDTH
        QTest.mouseClick(window, Qt.LeftButton)
        QTest.qWait(window.MORPH_MS + 60)
        assert window.expanded and window.capture_button.isVisible()
        assert window.width() == window.EXPANDED_WIDTH
        assert window._area().contains(window.geometry())
        assert not calls
        for item in (window.capture_button, window.settings_button, window.notes_button):
            assert item.text() in ("框选", "设置", "笔记")
            assert window.rect().contains(QRect(item.mapTo(window, QPoint()), item.size()))
            QTest.mouseClick(item, Qt.LeftButton)
        assert calls == ["capture", "settings", "notes"]
        QTest.keyClick(window, Qt.Key_Escape)
        QTest.qWait(window.MORPH_MS + 60)
        assert not window.expanded and not window._actions.isVisible()
        QTest.keyClick(window, Qt.Key_Space)
        QTest.qWait(window.MORPH_MS + 60)
        assert window.expanded and window.settings_button.isVisible()
    finally:
        window.hide()
        window.deleteLater()


def test_hide_during_transition_resets_capsule_and_pauses_glow():
    app = QApplication.instance() or QApplication([])
    window = LauncherWindow()
    window.show()
    app.processEvents()
    try:
        window.set_expanded(True)
        QTest.qWait(60)
        window.hide()
        assert not window.expanded and window.width() == window.COMPACT_WIDTH
        assert not window._glow_timer.isActive() and not window._collapse_timer.isActive()
        window.show()
        app.processEvents()
        assert window._glow_timer.isActive() and not window._actions.isVisible()
        window.set_expanded(True, animate=False)
        window.set_expanded(False)
        QTest.qWait(60)
        window.hide()
        assert window.width() == window.COMPACT_WIDTH
    finally:
        window.hide()
        window.deleteLater()


def test_capsule_expansion_and_fold_remain_inside_a_negative_coordinate_monitor(monkeypatch):
    app = QApplication.instance() or QApplication([])
    window = LauncherWindow()
    area = QRect(-1600, -900, 1600, 900)
    screen = type("Screen", (), {"availableGeometry": lambda _: area})()
    monkeypatch.setattr("screen_study_assistant.launcher.QGuiApplication.screenAt", lambda _: screen)
    try:
        for x in (area.left(), area.right() - window.COMPACT_WIDTH + 1):
            window.setGeometry(x, -100, window.COMPACT_WIDTH, window.HEIGHT)
            window.set_expanded(True, animate=False)
            app.processEvents()
            assert area.contains(window.geometry())
            assert window.glass_corner_radius() == window.HEIGHT / 2
            window.set_expanded(False, animate=False)
            assert area.contains(window.geometry())
            assert window.glass_corner_radius() == window.COMPACT_WIDTH / 2
    finally:
        window.hide()
        window.deleteLater()


def test_drag_unfolds_while_following_the_hand_without_restarting_or_firing_actions():
    from PySide6.QtCore import QEvent, QPointF
    from PySide6.QtGui import QMouseEvent

    app = QApplication.instance() or QApplication([])
    window = LauncherWindow()
    calls = []
    window.capture_requested.connect(lambda: calls.append("capture"))
    window.show()
    app.processEvents()
    try:
        QTest.mousePress(window, Qt.LeftButton, pos=window.rect().center())
        origin = QPoint(window._drag_origin)

        def move_to(delta):
            target = origin + delta
            event = QMouseEvent(QEvent.MouseMove, QPointF(window.mapFromGlobal(target)),
                                QPointF(target), Qt.NoButton, Qt.LeftButton, Qt.NoModifier)
            app.sendEvent(window, event)

        move_to(QPoint(-90, -35))
        assert window.expanded and window._dragged
        QTest.qWait(130)
        progress = window.unfold
        assert 0 < progress < 1 and window.COMPACT_WIDTH < window.width() < window.EXPANDED_WIDTH
        assert not window.capture_button.isEnabled()
        move_to(QPoint(-130, -60))
        QTest.qWait(70)
        assert window.unfold > progress  # dragging must not repeatedly restart the morph
        assert not calls
        target = origin + QPoint(-130, -60)
        app.sendEvent(window, QMouseEvent(QEvent.MouseButtonRelease,
                      QPointF(window.mapFromGlobal(target)), QPointF(target),
                      Qt.LeftButton, Qt.NoButton, Qt.NoModifier))
        QTest.qWait(window.MORPH_MS + 60)
        assert window.expanded and window.width() == window.EXPANDED_WIDTH
        assert window.height() == window.HEIGHT and window.capture_button.isEnabled()
        assert window._area().contains(window.geometry()) and not calls
    finally:
        window.hide()
        window.deleteLater()


def test_hover_does_not_steal_the_click_transition_and_idle_uses_desktop_pointer(monkeypatch):
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QEnterEvent

    app = QApplication.instance() or QApplication([])
    window = LauncherWindow()
    window.show()
    app.processEvents()
    try:
        app.sendEvent(window, QEnterEvent(QPointF(10, 10), QPointF(10, 10), QPointF(10, 10)))
        QTest.qWait(80)
        assert not window.expanded and window.width() == window.COMPACT_WIDTH
        QTest.mouseClick(window, Qt.LeftButton)
        QTest.qWait(90)
        assert window.COMPACT_WIDTH < window.width() < window.EXPANDED_WIDTH
        QTest.qWait(window.MORPH_MS + 60)
        monkeypatch.setattr("screen_study_assistant.launcher.QCursor.pos",
                            lambda: window.geometry().center())
        window._collapse_if_idle()
        assert window.expanded
        monkeypatch.setattr("screen_study_assistant.launcher.QCursor.pos", lambda: QPoint(-9999, -9999))
        # A stale QWidget hover bit must not keep the glass expanded forever.
        monkeypatch.setattr(window, "underMouse", lambda: True)
        window._collapse_if_idle()
        QTest.qWait(window.MORPH_MS + 60)
        assert not window.expanded and window.width() == window.COMPACT_WIDTH
    finally:
        window.hide()
        window.deleteLater()


def test_hiding_a_pressed_particle_resets_its_compression_and_input_state():
    app = QApplication.instance() or QApplication([])
    window = LauncherWindow()
    window.show()
    app.processEvents()
    try:
        QTest.mousePress(window, Qt.LeftButton)
        QTest.qWait(180)
        assert window.height() < window.COMPACT_HEIGHT
        window.hide()
        assert window._drag_origin is None and window.pressure == 0
        assert window.width() == window.COMPACT_WIDTH and window.height() == window.COMPACT_HEIGHT
        assert not window._glow_timer.isActive()
    finally:
        window.hide()
        window.deleteLater()
