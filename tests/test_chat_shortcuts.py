from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton

from jamun.storage import Store
from jamun.ui import ChatWindow


def test_chat_shortcuts_work_from_child_widgets(tmp_path):
    app = QApplication.instance() or QApplication([])
    chat = ChatWindow(Store(tmp_path / "shortcuts.sqlite3"))
    assert any("Ctrl+N" in button.text() for button in chat.findChildren(QPushButton))
    assert all(f"Ctrl+{index + 1}" in chat.tabs.tabText(index) for index in range(3))
    chat.show()
    chat.activateWindow()
    app.processEvents()
    chat.tabs.setCurrentIndex(1)
    chat.todo_title.setFocus()
    QTest.keyClick(chat.todo_title, Qt.Key.Key_N, Qt.KeyboardModifier.ControlModifier)
    app.processEvents()
    assert chat.history.count() == 1
    assert chat.tabs.currentIndex() == 0
    assert chat.input.hasFocus()
    QTest.keyClick(chat.input, Qt.Key.Key_2, Qt.KeyboardModifier.ControlModifier)
    app.processEvents()
    assert chat.tabs.currentIndex() == 1
    QTest.keyClick(chat.todo_title, Qt.Key.Key_L, Qt.KeyboardModifier.ControlModifier)
    app.processEvents()
    assert chat.tabs.currentIndex() == 0
    assert chat.input.hasFocus()
    chat.allow_close = True
    chat.close()
