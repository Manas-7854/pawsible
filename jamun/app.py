import argparse
import os
import re
import sqlite3
import sys
import time
from pathlib import Path

try:
    import fcntl
except ImportError:  # not available on Windows
    fcntl = None

from dotenv import load_dotenv
from PySide6.QtCore import QObject, QStandardPaths, Qt, QThread, QTimer, Slot
from PySide6.QtGui import QActionGroup, QIcon
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox, QSystemTrayIcon

from .animation import load_characters
from .provider import GeminiProvider
from .shortcuts import install_shortcuts, remove_shortcuts
from .storage import Store, secure_data_dir, secure_data_file
from .ui import ChatWindow, GenerationWorker, PetWindow, PreviewDialog, SettingsDialog


ROOT = Path(__file__).resolve().parent.parent


def next_state(state, command):
    if command == "toggle":
        return "chat" if state == "hidden" else "hidden"
    if command == "focus":
        return "pet" if state == "chat" else "chat"
    if command == "hide":
        return "hidden"
    if command == "pet":
        return "pet"
    if command == "chat":
        return "chat"
    raise ValueError(command)


def send_existing(name, command):
    socket = QLocalSocket()
    socket.connectToServer(name)
    if not socket.waitForConnected(350):
        return False
    socket.write(command.encode())
    socket.flush()
    socket.waitForBytesWritten(350)
    socket.disconnectFromServer()
    return True


class JamunApp(QObject):
    def __init__(self, qt, server, store, characters, api_key):
        super().__init__()
        self.qt = qt
        self.server = server
        self.store = store
        self.api_key = api_key
        self.characters = characters
        self.character_id = store.setting("character", "penguin")
        if self.character_id not in characters:
            self.character_id = "penguin"
        character = characters[self.character_id]
        self.state = "hidden"
        self.worker = None
        self.thread = None
        self.reply = ""
        self.active_message_id = None
        self.active_conversation_id = None
        self.pet = PetWindow(character["actions"], int(store.setting("size", 5)), character["play_actions"], character["hover_actions"], character["render_crop"], character["rest_actions"])
        self.chat = ChatWindow(store)
        self.chat.set_character_label(self.character_id)
        self.position_save_timer = QTimer(self)
        self.position_save_timer.setSingleShot(True)
        self.position_save_timer.setInterval(500)
        self.position_save_timer.timeout.connect(self.save_position)
        self.pet.clicked.connect(lambda: self.set_state("chat"))
        self.pet.moved.connect(self.position_save_timer.start)
        self.chat.closed_to_pet.connect(lambda: self.set_state("pet"))
        self.chat.send_requested.connect(self.send)
        self.chat.stop_requested.connect(self.stop)
        self.chat.settings_requested.connect(self.settings)
        self.menu = QMenu()
        self.menu.addAction("Open chat", lambda: self.set_state("chat"))
        self.menu.addAction("Hide all", lambda: self.set_state("hidden"))
        self.pause_action = self.menu.addAction("Resume movement" if store.setting("paused", "0") == "1" else "Pause movement", self.toggle_pause)
        character_menu = self.menu.addMenu("Character")
        self.character_group = QActionGroup(self.menu)
        self.character_menu_actions = {}
        for ident, entry in characters.items():
            action = character_menu.addAction(entry["label"])
            action.setCheckable(True)
            action.setChecked(ident == self.character_id)
            action.triggered.connect(lambda _checked=False, selected=ident: self.change_character(selected))
            self.character_group.addAction(action)
            self.character_menu_actions[ident] = action
        self.menu.addAction("Settings", self.settings)
        self.menu.addAction("Quit jamun", self.quit)
        self.pet.context_menu = self.menu
        self.tray = QSystemTrayIcon(QIcon(character["actions"]["idle"]["frames"][0]))
        self.tray.setToolTip("jamun")
        self.tray.setContextMenu(self.menu)
        self.tray.activated.connect(lambda reason: self.set_state("chat") if reason == QSystemTrayIcon.ActivationReason.Trigger else None)
        self.tray.show()
        self.server.newConnection.connect(self.incoming)
        self.qt.primaryScreenChanged.connect(lambda _: self.pet.keep_on_screen())
        self.qt.screenAdded.connect(lambda _: self.pet.keep_on_screen())
        self.qt.screenRemoved.connect(lambda _: self.pet.keep_on_screen())
        for screen in self.qt.screens():
            screen.availableGeometryChanged.connect(lambda _: self.pet.keep_on_screen())
        screen = self.qt.primaryScreen().availableGeometry()
        x = int(store.setting("pet_x", screen.right() - self.pet.width() - 32))
        y = int(store.setting("pet_y", screen.bottom() - self.pet.height() - 28))
        self.pet.move(x, y)
        self.pet.keep_on_screen()

    def save_position(self):
        x, y = self.pet.resting_position()
        self.store.set_setting("pet_x", x)
        self.store.set_setting("pet_y", y)

    def set_state(self, state):
        if state == "hidden":
            self.chat.hide()
            self.pet.stop()
        elif state == "pet":
            self.chat.hide()
            if not self.pet.isVisible():
                self.pet.start()
            self.pet.paused = self.store.setting("paused", "0") == "1"
        elif state == "chat":
            if not self.pet.isVisible():
                self.pet.start()
            self.pet.paused = True
            self.pet.halt_movement()
            self.pet.set_action("idle")
            self.anchor_chat()
            self.chat.show()
            self.chat.raise_()
            self.chat.activateWindow()
            self.chat.input.setFocus()
        self.state = state

    def anchor_chat(self):
        screen = QApplication.screenAt(self.pet.geometry().center()) or self.qt.primaryScreen()
        area = screen.availableGeometry()
        x = self.pet.x() + self.pet.width() + 12
        if x + self.chat.width() > area.right():
            x = self.pet.x() - self.chat.width() - 12
        x = max(area.left(), min(x, area.right() - self.chat.width() + 1))
        y = max(area.top(), min(self.pet.y() - 70, area.bottom() - self.chat.height() + 1))
        self.chat.move(x, y)

    def command(self, name):
        if name == "quit":
            self.quit()
        elif name.startswith("character:"):
            ident = name.split(":", 1)[1]
            if ident in self.characters:
                self.change_character(ident)
                self.set_state("pet")
        else:
            self.set_state(next_state(self.state, name))

    def incoming(self):
        while self.server.hasPendingConnections():
            socket = self.server.nextPendingConnection()
            socket.waitForReadyRead(300)
            command = bytes(socket.readAll()).decode().strip()
            socket.deleteLater()
            if command in ("toggle", "focus", "hide", "pet", "chat", "quit") or command in {f"character:{ident}" for ident in self.characters}:
                self.command(command)

    def toggle_pause(self):
        paused = self.store.setting("paused", "0") != "1"
        self.store.set_setting("paused", "1" if paused else "0")
        self.pet.paused = paused or self.state == "chat"
        if paused:
            self.pet.halt_movement()
            self.pet.set_action("idle")
        self.pause_action.setText("Resume movement" if paused else "Pause movement")
        self.chat.status.setText("Movement paused" if paused else "Movement resumed")

    def change_character(self, ident):
        if ident not in self.characters:
            return
        self.character_id = ident
        self.store.set_setting("character", ident)
        character = self.characters[ident]
        self.pet.set_character(character["actions"], character["play_actions"], character["hover_actions"], character["render_crop"], character["rest_actions"])
        self.tray.setIcon(QIcon(character["actions"]["idle"]["frames"][0]))
        self.chat.set_character_label(ident)
        self.character_menu_actions[ident].setChecked(True)
        self.chat.status.setText(f"Character: {character['label']}")

    def settings(self):
        dialog = SettingsDialog(self.store, self.characters, self.chat)
        if dialog.exec():
            self.change_character(self.store.setting("character", "penguin"))
            self.pet.set_scale(int(self.store.setting("size", 5)))
            self.pet.keep_on_screen()
            if self.state == "chat":
                self.anchor_chat()
            if os.environ.get("XDG_CURRENT_DESKTOP", "").upper().find("GNOME") >= 0:
                try:
                    install_shortcuts(ROOT, self.store.setting("open_shortcut", "<Shift>space"), self.store.setting("hide_shortcut", "<Ctrl><Alt>space"))
                except Exception as exc:
                    QMessageBox.warning(self.chat, "Shortcuts", f"Settings saved, but GNOME shortcuts could not be installed: {exc}")

    def send(self, text):
        if self.worker is not None:
            self.chat.status.setText("Wait for the current reply or press Stop.")
            self.chat.input.setPlainText(text)
            return
        if not self.chat.current_id:
            self.chat.new_conversation()
        ident = self.chat.current_id
        memory_match = re.match(r"(?is)^(?:please |can you )?remember (?:that |this: |this )?(.+)$", text.strip())
        if memory_match:
            self.store.add_message(ident, "user", text)
            self.store.add_memory(memory_match.group(1).strip())
            self.store.add_message(ident, "assistant", "I'll remember that. You can edit it in Memory.")
            self.chat.reload_memories()
            self.chat.render_messages()
            return
        self.store.add_message(ident, "user", text)
        self.chat.reload_history(ident)
        self.chat.render_messages()
        self.reply = ""
        self.active_conversation_id = ident
        self.active_message_id = None
        provider = GeminiProvider(self.api_key, self.store.setting("model", "gemini-3.5-flash-lite"), Path(self.store.db.execute("PRAGMA database_list").fetchone()[2]))
        self.thread = QThread()
        self.worker = GenerationWorker(ident, provider, self.store.messages(ident), self.store.memories(), self.store.tasks())
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.text.connect(self.on_text, Qt.ConnectionType.QueuedConnection)
        self.worker.task_approval_requested.connect(self.approve_task_change, Qt.ConnectionType.QueuedConnection)
        self.worker.finished.connect(self.on_finished, Qt.ConnectionType.QueuedConnection)
        self.worker.finished.connect(self.thread.quit)
        self.thread.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.thread.deleteLater)
        self.thread.finished.connect(self.clear_thread, Qt.ConnectionType.QueuedConnection)
        self.thread.start()
        self.chat.send_button.setEnabled(False)
        self.chat.stop_button.setEnabled(True)
        self.chat.status.setText("jamun is thinking…")

    @Slot(int, str)
    def on_text(self, ident, piece):
        if ident != self.active_conversation_id:
            return
        self.reply += piece
        if self.chat.current_id == ident:
            self.chat.render_messages(self.reply)

    @Slot(object)
    def approve_task_change(self, request):
        try:
            if request["worker"] is not self.worker or self.worker.stop_event.is_set():
                return
            dialog = QMessageBox(self.chat)
            dialog.setWindowTitle("Confirm task change")
            dialog.setTextFormat(Qt.TextFormat.PlainText)
            dialog.setText(f"Allow jamun to change your tasks?\n\n{request['name']}: {request['args']}")
            dialog.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            dialog.setDefaultButton(QMessageBox.StandardButton.No)
            request["approved"] = dialog.exec() == QMessageBox.StandardButton.Yes
        finally:
            request["ready"].set()

    @Slot(int, str)
    def on_finished(self, ident, error):
        if ident != self.active_conversation_id:
            return
        interrupted = self.worker.stop_event.is_set()
        if self.reply or interrupted:
            status = "interrupted" if interrupted or error else "complete"
            self.store.add_message(ident, "assistant", self.reply or "(stopped)", status)
        elif error:
            self.store.add_message(ident, "assistant", error, "error")
        self.chat.status.setText("Stopped" if interrupted else error or "Ready")
        self.chat.send_button.setEnabled(True)
        self.chat.stop_button.setEnabled(False)
        self.chat.reload_tasks()
        if self.chat.current_id == ident:
            self.chat.render_messages()
        self.worker = None
        self.active_conversation_id = None

    @Slot()
    def clear_thread(self):
        if self.thread is self.sender():
            self.thread = None

    def stop(self):
        if self.worker:
            self.worker.stop_event.set()
            self.chat.status.setText("Stopping…")

    def quit(self):
        self.stop()
        if self.thread and self.thread.isRunning():
            self.thread.quit()
            self.thread.wait(35000)
        self.chat.allow_close = True
        self.chat.close()
        if self.position_save_timer.isActive():
            self.position_save_timer.stop()
            self.save_position()
        self.pet.stop()
        self.tray.hide()
        self.server.close()
        self.qt.quit()


def migrate_legacy_data(data_dir, legacy_db):
    database = data_dir / "jamun.sqlite3"
    if database.exists() or not legacy_db.exists():
        return database
    secure_data_dir(data_dir)
    temporary = data_dir / "jamun.sqlite3.migrating"
    secure_data_file(temporary)
    source = sqlite3.connect(f"file:{legacy_db}?mode=ro", uri=True)
    destination = sqlite3.connect(temporary)
    try:
        source.backup(destination)
    finally:
        # Windows won't rename a file that still has open handles
        destination.close()
        source.close()
    temporary.replace(database)
    return database


def load_private_env(path):
    if path.is_symlink():
        raise RuntimeError(f"Refusing a symlinked key file: {path}")
    if path.exists():
        owned = not hasattr(os, "getuid") or path.stat().st_uid == os.getuid()
        if not path.is_file() or not owned:
            raise RuntimeError(f"Key file must be a regular file owned by you: {path}")
        path.chmod(0o600)
        load_dotenv(path)


def main():
    parser = argparse.ArgumentParser(description="jamun desktop companion")
    parser.add_argument("--command", choices=["toggle", "focus", "hide", "pet", "chat", "quit"], default="chat")
    parser.add_argument("--preview", action="store_true")
    parser.add_argument("--character", help="Select an installed character")
    parser.add_argument("--install-shortcuts", action="store_true")
    parser.add_argument("--remove-shortcuts", action="store_true")
    args = parser.parse_args()
    QApplication.setApplicationName("jamun")
    data_dir = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation))
    legacy_db = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.GenericDataLocation)) / "Pengu" / "pengu.sqlite3"
    database = migrate_legacy_data(data_dir, legacy_db)
    secure_data_file(database)
    if args.install_shortcuts or args.remove_shortcuts:
        store = Store(database)
        if args.install_shortcuts:
            install_shortcuts(ROOT, store.setting("open_shortcut", "<Shift>space"), store.setting("hide_shortcut", "<Ctrl><Alt>space"))
        else:
            remove_shortcuts()
        return 0
    load_private_env(ROOT / ".env")
    if os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland" and "GNOME" in os.environ.get("XDG_CURRENT_DESKTOP", "").upper() and os.environ.get("DISPLAY"):
        os.environ.setdefault("QT_QPA_PLATFORM", "xcb")
    qt = QApplication(sys.argv)
    qt.setQuitOnLastWindowClosed(False)
    characters = load_characters(ROOT / "characters.json")
    if args.character and args.character not in characters:
        parser.error(f"Character {args.character!r} is unavailable. Installed choices: {', '.join(characters)}")
    if args.preview:
        dialog = PreviewDialog(characters[args.character or "penguin"]["actions"])
        dialog.show()
        return qt.exec()
    name = str(data_dir / "jamun.sock")
    command = f"character:{args.character}" if args.character else args.command
    if send_existing(name, command):
        return 0
    secure_data_file(data_dir / "jamun.lock")
    lock_file = (data_dir / "jamun.lock").open("a+")
    if fcntl is not None:
        try:
            fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            for _ in range(10):
                time.sleep(0.2)
                if send_existing(name, command):
                    return 0
            raise RuntimeError("jamun is already starting; try the command again")
    QLocalServer.removeServer(name)
    server = QLocalServer()
    server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
    if not server.listen(name):
        raise RuntimeError("Could not start the single-instance command socket")
    store = Store(database)
    app = JamunApp(qt, server, store, characters, os.getenv("GEMINI_API_KEY", ""))
    app.lock_file = lock_file
    app.command(command)
    return qt.exec()
