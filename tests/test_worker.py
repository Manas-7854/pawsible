import time

from PySide6.QtCore import QEventLoop, QThread, QTimer
from PySide6.QtNetwork import QLocalServer
from PySide6.QtWidgets import QApplication

from jamun.animation import load_manifest
from jamun.app import JamunApp
from jamun.storage import Store
from jamun.ui import GenerationWorker


class FailingProvider:
    def stream(self, messages, memories, tasks, on_text, stopped):
        time.sleep(0.15)
        raise RuntimeError("offline")


def test_generation_worker_keeps_event_loop_responsive():
    app = QApplication.instance() or QApplication([])
    loop = QEventLoop()
    thread = QThread()
    worker = GenerationWorker(7, FailingProvider(), [], [], [])
    worker.moveToThread(thread)
    ticks = []
    result = []
    timer = QTimer()
    timer.setInterval(10)
    timer.timeout.connect(lambda: ticks.append(1))
    worker.finished.connect(lambda ident, error: result.append((ident, error)))
    worker.finished.connect(thread.quit)
    thread.finished.connect(loop.quit)
    thread.started.connect(worker.run)
    timer.start()
    thread.start()
    loop.exec()
    timer.stop()
    assert thread.wait(2000)
    assert len(ticks) >= 3
    assert result == [(7, "offline")]


def test_switching_conversations_keeps_reply_with_original(tmp_path, monkeypatch):
    from jamun import app as app_module

    class DelayedProvider:
        def __init__(self, *args):
            pass

        def stream(self, messages, memories, tasks, on_text, stopped):
            time.sleep(0.08)
            on_text("Reply for first conversation")

    monkeypatch.setattr(app_module, "GeminiProvider", DelayedProvider)
    qt = QApplication.instance() or QApplication([])
    store = Store(tmp_path / "app.sqlite3")
    server = QLocalServer()
    app = JamunApp(qt, server, store, load_manifest(app_module.ROOT / "animation.json"), "test-key")
    app.chat.new_conversation()
    first = app.chat.current_id
    app.send("First question")
    app.chat.new_conversation()
    second = app.chat.current_id
    loop = QEventLoop()
    timer = QTimer()
    timer.setInterval(10)
    timer.timeout.connect(lambda: loop.quit() if app.worker is None else None)
    timer.start()
    QTimer.singleShot(2000, loop.quit)
    loop.exec()
    timer.stop()
    assert app.worker is None
    assert [row["content"] for row in store.messages(first)] == ["First question", "Reply for first conversation"]
    assert store.messages(second) == []
    app.quit()
