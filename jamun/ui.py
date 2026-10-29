import math
import random
import threading
import time

from markdown_it import MarkdownIt
from PySide6.QtCore import Qt, QTimer, Signal, QObject
from PySide6.QtGui import QKeyEvent, QKeySequence, QPainter, QShortcut
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QFormLayout, QHBoxLayout, QInputDialog,
    QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox,
    QPushButton, QScrollArea, QSpinBox, QTabWidget,
    QTextBrowser, QTextEdit, QVBoxLayout, QWidget,
)

from .provider import GeminiProvider
from .workspaces import exclude_from_focus, show_on_all_workspaces


MARKDOWN = MarkdownIt("commonmark", {"html": False, "linkify": True})


class InputBox(QTextEdit):
    send_requested = Signal()

    def keyPressEvent(self, event: QKeyEvent):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            self.send_requested.emit()
            return
        super().keyPressEvent(event)


class GenerationWorker(QObject):
    text = Signal(int, str)
    finished = Signal(int, str)
    task_approval_requested = Signal(object)

    def __init__(self, conversation_id, provider, messages, memories, tasks):
        super().__init__()
        self.conversation_id = conversation_id
        self.provider = provider
        self.messages = messages
        self.memories = memories
        self.tasks = tasks
        self.stop_event = threading.Event()
        self.provider.approve_task_change = self.request_task_approval

    def request_task_approval(self, name, args):
        request = {"worker": self, "name": name, "args": args, "ready": threading.Event(), "approved": False}
        self.task_approval_requested.emit(request)
        while not request["ready"].wait(0.1):
            if self.stop_event.is_set():
                return False
        return request["approved"]

    def run(self):
        error = ""
        try:
            self.provider.stream(self.messages, self.memories, self.tasks, lambda text: self.text.emit(self.conversation_id, text), self.stop_event)
        except Exception as exc:
            error = str(exc)
        self.finished.emit(self.conversation_id, error)


class NameTag(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.label = QLabel()
        self.label.setStyleSheet("color: #f2f5fb; background: rgba(20, 26, 38, 0.78); border-radius: 7px; padding: 1px 7px; font: 12px 'Sans Serif';")
        layout.addWidget(self.label)

    def set_text(self, text):
        self.label.setText(text)
        self.adjustSize()


class PetWindow(QWidget):
    clicked = Signal()
    moved = Signal()

    def __init__(self, actions, scale=5, play_actions=None, hover_actions=None, render_crop=None, rest_actions=None):
        super().__init__()
        self.actions = actions
        self.play_actions = play_actions or [name for name in actions if name not in ("idle", "walk")]
        self.hover_actions = hover_actions or ["reaction"]
        self.rest_actions = rest_actions or {}
        self.render_crop = render_crop
        self.scale = scale
        self.action = "idle"
        self.frame_index = 0
        self.drag_origin = None
        self.dragging = False
        self.paused = False
        self.target = None
        self.position = (0.0, 0.0)
        self.last_motion = 0.0
        self.speed = 0.0
        self.facing_left = False
        self.hop_origin = None
        self.hop_started = 0.0
        self.hop_duration = 0.0
        self.hover_cooldown_until = 0.0
        self.rest_action = None
        self.rest_until = 0.0
        self.speed_range = (60, 90)
        self.behavior_weights = {"walk": 45, "jump": 18, "rest": 20, "play": 17}
        self.pace = 1.0
        self.next_behavior = time.monotonic() + 1.5
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFixedSize(16 * scale, 16 * scale)
        self.animation_timer = QTimer(self, timeout=self.advance_frame)
        self.animation_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.behavior_timer = QTimer(self, timeout=self.behave)
        self.behavior_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.behavior_timer.setInterval(33)

    def set_temperament(self, speed_range, weights, pace):
        self.speed_range = speed_range
        self.behavior_weights = weights
        self.pace = pace

    def pick_behavior(self):
        weights = dict(self.behavior_weights)
        if not self.rest_actions:
            weights.pop("rest", None)
        options = [name for name in ("walk", "jump", "rest", "play") if weights.get(name, 0) > 0]
        if not options:
            return "walk"
        return random.choices(options, [weights[name] for name in options])[0]

    def set_scale(self, scale):
        self.scale = scale
        self.setFixedSize(16 * scale, 16 * scale)
        self.update()

    def set_character(self, actions, play_actions, hover_actions=None, render_crop=None, rest_actions=None):
        self.halt_movement()
        self.actions = actions
        self.play_actions = play_actions
        self.hover_actions = hover_actions or ["reaction"]
        self.rest_actions = rest_actions or {}
        self.render_crop = render_crop
        self.hover_cooldown_until = 0.0
        self.set_action("idle")
        if not self.isVisible():
            self.animation_timer.stop()
        self.update()

    def set_action(self, name):
        self.action = name
        self.frame_index = 0
        if self.isVisible():
            self.animation_timer.start(self.actions[name]["duration_ms"])
        self.update()

    def start(self):
        self.position = (float(self.x()), float(self.y()))
        self.next_behavior = time.monotonic() + random.uniform(1, 2.5)
        self.show()
        self.set_action("idle")
        self.behavior_timer.start()

    def stop(self):
        self.halt_movement()
        self.animation_timer.stop()
        self.behavior_timer.stop()
        self.hide()

    def halt_movement(self):
        if self.hop_origin is not None:
            self.move(*self.hop_origin)
            self.hop_origin = None
        self.target = None
        self.rest_action = None
        self.rest_until = 0.0
        self.behavior_timer.setInterval(33)
        self.position = (float(self.x()), float(self.y()))
        self.next_behavior = time.monotonic() + random.uniform(1, 2.5)

    def start_rest(self, name, now=None):
        if self.paused or self.dragging or name not in self.rest_actions:
            return False
        self.halt_movement()
        now = time.monotonic() if now is None else now
        self.rest_action = name
        self.rest_until = now + random.uniform(*self.rest_actions[name])
        self.next_behavior = self.rest_until
        self.set_action(name)
        self.behavior_timer.setInterval(200)
        return True

    def resting_position(self):
        return self.hop_origin or (self.x(), self.y())

    def start_jump(self, now=None):
        if self.paused or self.dragging:
            return False
        self.halt_movement()
        now = time.monotonic() if now is None else now
        self.hop_origin = (self.x(), self.y())
        self.hop_started = now
        animation = self.actions["jump"]
        self.hop_duration = max(0.55, len(animation["frames"]) * animation["duration_ms"] / 1000)
        self.hover_cooldown_until = now + self.hop_duration + 1.0
        self.next_behavior = now + self.hop_duration + random.uniform(1.0, 2.4)
        self.set_action("jump")
        return True

    def advance_jump(self, now):
        progress = min(1.0, (now - self.hop_started) / self.hop_duration)
        if progress >= 1.0:
            self.move(*self.hop_origin)
            self.hop_origin = None
            self.position = (float(self.x()), float(self.y()))
            self.set_action("idle")
            self.moved.emit()
            return
        screen = QApplication.screenAt(self.geometry().center()) or QApplication.primaryScreen()
        rise = min(self.height() * 0.8, self.hop_origin[1] - screen.availableGeometry().top())
        lift = round(max(0, rise) * 4 * progress * (1 - progress))
        self.move(self.hop_origin[0], self.hop_origin[1] - lift)
        self.moved.emit()

    def advance_frame(self):
        action = self.actions[self.action]
        self.frame_index += 1
        if self.frame_index >= len(action["frames"]):
            if action["loop"]:
                self.frame_index = 0
            elif self.action == "jump" and self.hop_origin is not None:
                self.frame_index = len(action["frames"]) - 1
            elif self.action == self.rest_action:
                self.frame_index = len(action["frames"]) - 1
                self.animation_timer.stop()
            else:
                self.set_action("idle")
                return
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
        frame = self.actions[self.action]["frames"][self.frame_index]
        if self.action == "walk" and self.facing_left:
            painter.translate(self.width(), 0)
            painter.scale(-1, 1)
        painter.drawPixmap(self.rect(), frame, self.render_crop or frame.rect())

    def keep_on_screen(self):
        if self.hop_origin is not None:
            self.halt_movement()
        screen = QApplication.screenAt(self.geometry().center()) or QApplication.primaryScreen()
        area = screen.availableGeometry()
        x = max(area.left(), min(self.x(), area.right() - self.width() + 1))
        y = max(area.top(), min(self.y(), area.bottom() - self.height() + 1))
        if (x, y) != (self.x(), self.y()):
            self.move(x, y)
            self.position = (float(x), float(y))
            self.target = None

    def start_trip(self):
        screen = QApplication.screenAt(self.geometry().center()) or QApplication.primaryScreen()
        area = screen.availableGeometry()
        margin = 18
        left = area.left() + margin
        top = area.top() + margin
        right = max(left, area.right() - self.width() - margin)
        bottom = max(top, area.bottom() - self.height() - margin)
        x, y = self.x(), self.y()
        if random.random() < 0.45 and right - left >= 300:
            edge_band = min(120, (right - left) * 0.12)
            target_x = right - random.uniform(0, edge_band) if x < (left + right) / 2 else left + random.uniform(0, edge_band)
            self.target = (target_x, random.uniform(top, bottom))
        else:
            directions = [(1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1)]
            choices = []
            for dx, dy in directions:
                distance = random.uniform(180, 460)
                length = math.hypot(dx, dy)
                target_x = max(left, min(right, x + distance * dx / length))
                target_y = max(top, min(bottom, y + distance * dy / length))
                if math.hypot(target_x - x, target_y - y) >= 90:
                    choices.append((target_x, target_y))
            if not choices:
                return False
            self.target = random.choice(choices)
        self.position = (float(x), float(y))
        self.last_motion = time.monotonic()
        self.speed = random.uniform(*self.speed_range)
        self.facing_left = self.target[0] < x
        self.set_action("walk")
        return True

    def behave(self):
        if self.dragging:
            return
        if self.paused:
            if self.hop_origin is not None:
                self.halt_movement()
                self.set_action("idle")
            return
        now = time.monotonic()
        if self.hop_origin is not None:
            self.advance_jump(now)
            return
        if self.target is not None:
            x, y = self.position
            dx, dy = self.target[0] - x, self.target[1] - y
            distance = math.hypot(dx, dy)
            step = self.speed * min(now - self.last_motion, 0.08)
            self.last_motion = now
            if distance <= step:
                self.move(round(self.target[0]), round(self.target[1]))
                self.position = self.target
                self.target = None
                self.set_action("idle")
                self.next_behavior = now + random.uniform(0.8, 2.8) * self.pace
            else:
                self.position = (x + dx * step / distance, y + dy * step / distance)
                self.move(round(self.position[0]), round(self.position[1]))
            self.moved.emit()
            return
        if self.rest_action is not None:
            if now >= self.rest_until:
                self.rest_action = None
                self.rest_until = 0.0
                self.behavior_timer.setInterval(33)
                self.set_action("idle")
                self.next_behavior = now + random.uniform(0.8, 2.0) * self.pace
            return
        if now < self.next_behavior:
            return
        choice = self.pick_behavior()
        if choice == "walk":
            if not self.start_trip():
                self.next_behavior = now + 2
        elif choice == "jump":
            self.start_jump(now)
        elif choice == "rest":
            self.start_rest(random.choice(list(self.rest_actions)), now)
        else:
            choice = random.choice(self.play_actions) if self.play_actions else "idle"
            self.set_action(choice)
            duration = len(self.actions[choice]["frames"]) * self.actions[choice]["duration_ms"] / 1000
            self.next_behavior = now + duration + random.uniform(0.8, 2.2) * self.pace

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_origin = event.globalPosition().toPoint() - self.pos()
            self.dragging = False
        elif event.button() == Qt.MouseButton.RightButton:
            self.context_menu.exec(event.globalPosition().toPoint())

    def enterEvent(self, event):
        now = time.monotonic()
        if not self.dragging and self.rest_action in (None, "idle") and now >= self.hover_cooldown_until and self.action in ("idle", "walk"):
            choice = random.choice(self.hover_actions)
            if choice == "jump" and not self.paused:
                self.start_jump(now)
            else:
                self.halt_movement()
                self.set_action("reaction" if choice == "jump" else choice)
                action = self.actions[self.action]
                duration = len(action["frames"]) * action["duration_ms"] / 1000
                self.hover_cooldown_until = now + duration + 1.0
                self.next_behavior = now + duration + random.uniform(1.0, 2.2)
        super().enterEvent(event)

    def showEvent(self, event):
        super().showEvent(event)
        QTimer.singleShot(100, self.apply_window_hints)

    def apply_window_hints(self):
        if self.isVisible():
            exclude_from_focus(self)
            show_on_all_workspaces(self)

    def mouseMoveEvent(self, event):
        if self.drag_origin is not None and event.buttons() & Qt.MouseButton.LeftButton:
            new_pos = event.globalPosition().toPoint() - self.drag_origin
            if (new_pos - self.pos()).manhattanLength() > 4:
                if not self.dragging:
                    self.set_action("idle")
                self.dragging = True
            if self.dragging:
                self.halt_movement()
                self.move(new_pos)
                self.keep_on_screen()
                self.moved.emit()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            if not self.dragging:
                self.clicked.emit()
            self.drag_origin = None
            self.dragging = False


class SettingsDialog(QDialog):
    def __init__(self, store, characters, movements, parent=None):
        super().__init__(parent)
        self.setWindowTitle("jamun settings")
        self.store = store
        layout = QFormLayout(self)
        self.name = QLineEdit(store.setting("pet_name", "jamun"))
        self.name.setPlaceholderText("jamun")
        self.character = QComboBox()
        for ident, character in characters.items():
            self.character.addItem(character["label"], ident)
        self.character.setCurrentIndex(max(0, self.character.findData(store.setting("character", "penguin"))))
        self.movement = QComboBox()
        self.movement.addItem("Follow the character", "")
        for ident, movement in movements.items():
            self.movement.addItem(movement["label"], ident)
        self.movement.setCurrentIndex(max(0, self.movement.findData(store.setting("movement", ""))))
        self.model = QLineEdit(store.setting("model", "gemini-3.5-flash-lite"))
        self.open_shortcut = QLineEdit(store.setting("open_shortcut", "<Shift>space"))
        self.hide_shortcut = QLineEdit(store.setting("hide_shortcut", "<Ctrl><Alt>space"))
        self.size = QSpinBox()
        self.size.setRange(2, 10)
        self.size.setValue(int(store.setting("size", 5)))
        self.show_name = QCheckBox("Show name tag above the pet")
        self.show_name.setChecked(store.setting("show_name", "0") == "1")
        layout.addRow("Gemini model", self.model)
        layout.addRow("Name", self.name)
        layout.addRow("Character", self.character)
        layout.addRow("Movement", self.movement)
        layout.addRow(self.show_name)
        layout.addRow("Open chat shortcut (GNOME)", self.open_shortcut)
        layout.addRow("Hide jamun shortcut (GNOME)", self.hide_shortcut)
        layout.addRow("Character size", self.size)
        hint = QLabel("Shortcut changes are applied through GNOME custom keybindings.")
        hint.setWordWrap(True)
        layout.addRow(hint)
        save = QPushButton("Save")
        save.clicked.connect(self.accept)
        layout.addRow(save)

    def accept(self):
        for key, value in (("model", self.model.text().strip()), ("open_shortcut", self.open_shortcut.text().strip()), ("hide_shortcut", self.hide_shortcut.text().strip()), ("size", self.size.value())):
            if not str(value):
                QMessageBox.warning(self, "Missing setting", f"{key} cannot be empty")
                return
            self.store.set_setting(key, value)
        self.store.set_setting("pet_name", self.name.text().strip())
        self.store.set_setting("character", self.character.currentData())
        self.store.set_setting("movement", self.movement.currentData())
        self.store.set_setting("show_name", "1" if self.show_name.isChecked() else "0")
        super().accept()


class ChatWindow(QWidget):
    closed_to_pet = Signal()
    send_requested = Signal(str)
    stop_requested = Signal()
    settings_requested = Signal()

    def __init__(self, store):
        super().__init__()
        self.store = store
        self.current_id = None
        self.allow_close = False
        self.setWindowTitle("jamun")
        self.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint)
        self.resize(620, 520)
        self.pet_name = (store.setting("pet_name", "jamun") or "jamun").strip() or "jamun"
        self.char_icon = "🐧"
        root = QVBoxLayout(self)
        header = QHBoxLayout()
        self.header_label = QLabel(f"{self.char_icon}  {self.pet_name}")
        header.addWidget(self.header_label)
        header.addStretch()
        settings = QPushButton("⚙")
        settings.clicked.connect(self.settings_requested)
        header.addWidget(settings)
        root.addLayout(header)
        self.tabs = QTabWidget()
        root.addWidget(self.tabs)

        chat = QWidget()
        chat_layout = QHBoxLayout(chat)
        sidebar = QVBoxLayout()
        self.history = QListWidget()
        self.history.currentItemChanged.connect(self.select_conversation)
        sidebar.addWidget(self.history)
        for label, method in (("New · Ctrl+N", self.new_conversation), ("Rename", self.rename_conversation), ("Delete", self.delete_conversation)):
            button = QPushButton(label)
            button.clicked.connect(method)
            sidebar.addWidget(button)
        chat_layout.addLayout(sidebar, 1)
        conversation = QVBoxLayout()
        self.transcript = QTextBrowser()
        self.transcript.setOpenExternalLinks(True)
        conversation.addWidget(self.transcript, 1)
        self.status = QLabel("Ready")
        conversation.addWidget(self.status)
        self.input = InputBox()
        self.input.setPlaceholderText("Ask me anything…  Enter sends · Shift+Enter adds a line · Ctrl+L focuses")
        self.input.setFixedHeight(76)
        self.input.send_requested.connect(self.request_send)
        conversation.addWidget(self.input)
        controls = QHBoxLayout()
        self.send_button = QPushButton("Send")
        self.send_button.clicked.connect(self.request_send)
        controls.addWidget(self.send_button)
        self.stop_button = QPushButton("Stop · Ctrl+.")
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self.stop_requested)
        controls.addWidget(self.stop_button)
        self.copy_button = QPushButton("Copy · Ctrl+Shift+C")
        self.copy_button.clicked.connect(self.copy_last_reply)
        controls.addWidget(self.copy_button)
        conversation.addLayout(controls)
        chat_layout.addLayout(conversation, 3)
        self.tabs.addTab(chat, "Chat · Ctrl+1")

        todo = QWidget()
        todo_layout = QVBoxLayout(todo)
        self.todo_list = QListWidget()
        todo_layout.addWidget(self.todo_list)
        self.todo_title = QLineEdit()
        self.todo_title.setPlaceholderText("Task title")
        self.todo_notes = QLineEdit()
        self.todo_notes.setPlaceholderText("Notes (optional)")
        self.todo_due = QLineEdit()
        self.todo_due.setPlaceholderText("Due date YYYY-MM-DD (optional)")
        todo_layout.addWidget(self.todo_title)
        todo_layout.addWidget(self.todo_notes)
        todo_layout.addWidget(self.todo_due)
        task_controls = QHBoxLayout()
        for label, method in (("Add", self.add_task), ("Edit selected", self.edit_task), ("Complete", self.complete_task), ("Delete", self.delete_task)):
            button = QPushButton(label)
            button.clicked.connect(method)
            task_controls.addWidget(button)
        todo_layout.addLayout(task_controls)
        self.todo_list.currentItemChanged.connect(self.fill_task)
        self.tabs.addTab(todo, "Todos · Ctrl+2")

        memory = QWidget()
        memory_layout = QVBoxLayout(memory)
        self.memory_list = QListWidget()
        memory_layout.addWidget(self.memory_list)
        memory_controls = QHBoxLayout()
        for label, method in (("Add", self.add_memory), ("Edit", self.edit_memory), ("Delete", self.delete_memory)):
            button = QPushButton(label)
            button.clicked.connect(method)
            memory_controls.addWidget(button)
        memory_layout.addLayout(memory_controls)
        self.tabs.addTab(memory, "Memory · Ctrl+3")
        self.shortcuts = []
        for sequence, callback in (
            ("Ctrl+N", self.new_conversation),
            ("Ctrl+L", self.focus_input),
            ("Ctrl+1", lambda: self.tabs.setCurrentIndex(0)),
            ("Ctrl+2", lambda: self.tabs.setCurrentIndex(1)),
            ("Ctrl+3", lambda: self.tabs.setCurrentIndex(2)),
            ("Ctrl+Shift+C", self.copy_last_reply),
            ("Ctrl+.", self.stop_requested.emit),
        ):
            shortcut = QShortcut(QKeySequence(sequence), self)
            shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            shortcut.activated.connect(callback)
            self.shortcuts.append(shortcut)
        self.reload_all()
        self.setStyleSheet("""
            QWidget { background: #171d2a; color: #e8ecf6; font: 12px 'Sans Serif'; }
            QTabWidget::pane, QListWidget, QTextBrowser, QTextEdit, QLineEdit {
                background: #202a3b; border: 1px solid #35415a; border-radius: 9px; padding: 7px;
            }
            QPushButton { background: #374d69; border: 0; border-radius: 8px; padding: 7px 12px; }
            QPushButton:hover { background: #496787; }
            QPushButton:disabled { color: #8190a4; background: #2a3546; }
            QTabBar::tab { background: #202a3b; padding: 8px 15px; border-radius: 7px; }
            QTabBar::tab:selected { background: #3b5574; }
        """)

    def set_character_label(self, ident):
        self.char_icon = {"penguin": "🐧", "midnight_cat": "🐈‍⬛", "shadow_cat": "🐈‍⬛", "white_cat": "🐈", "fox": "🦊"}.get(ident, "🐧")
        self.header_label.setText(f"{self.char_icon}  {self.pet_name}")

    def set_pet_name(self, name):
        self.pet_name = (name or "").strip() or "jamun"
        self.header_label.setText(f"{self.char_icon}  {self.pet_name}")
        self.render_messages()

    def closeEvent(self, event):
        if self.allow_close:
            event.accept()
            return
        event.ignore()
        self.closed_to_pet.emit()

    def showEvent(self, event):
        super().showEvent(event)
        QTimer.singleShot(100, lambda: show_on_all_workspaces(self))

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.closed_to_pet.emit()
            return
        super().keyPressEvent(event)

    def reload_all(self):
        self.reload_history()
        self.reload_tasks()
        self.reload_memories()

    def reload_history(self, select_id=None):
        select_id = select_id or self.current_id
        self.history.blockSignals(True)
        self.history.clear()
        selected = None
        for row in self.store.conversations():
            item = QListWidgetItem(row["title"])
            item.setData(Qt.ItemDataRole.UserRole, row["id"])
            self.history.addItem(item)
            if row["id"] == select_id:
                selected = item
        self.history.blockSignals(False)
        if selected:
            self.history.setCurrentItem(selected)
        elif self.history.count():
            self.history.setCurrentRow(0)
        else:
            self.current_id = None
            self.transcript.clear()

    def select_conversation(self, item, previous):
        if item is None:
            return
        self.current_id = item.data(Qt.ItemDataRole.UserRole)
        self.render_messages()

    def new_conversation(self):
        ident = self.store.new_conversation()
        self.current_id = ident
        self.reload_history(ident)
        self.tabs.setCurrentIndex(0)
        self.input.setFocus()

    def focus_input(self):
        self.tabs.setCurrentIndex(0)
        self.input.setFocus()

    def rename_conversation(self):
        if not self.current_id:
            return
        title, ok = QInputDialog.getText(self, "Rename conversation", "Title")
        if ok and title.strip():
            self.store.rename_conversation(self.current_id, title)
            self.reload_history()

    def delete_conversation(self):
        if not self.current_id:
            return
        if self.send_button.isEnabled() is False:
            QMessageBox.information(self, "Reply in progress", "Stop the current reply before deleting a conversation.")
            return
        if QMessageBox.question(self, "Delete conversation", "Delete this conversation and its messages?") == QMessageBox.StandardButton.Yes:
            self.store.delete_conversation(self.current_id)
            self.current_id = None
            self.reload_history()

    def render_messages(self, draft=""):
        if not self.current_id:
            self.transcript.clear()
            return
        parts = []
        for row in self.store.messages(self.current_id):
            label = "You" if row["role"] == "user" else self.pet_name
            body = MARKDOWN.render(row["content"])
            note = f" <span style='color:#aab7ca'>({row['status']})</span>" if row["status"] != "complete" else ""
            parts.append(f"<div style='margin-bottom:12px'><b>{label}</b>{note}<br>{body}</div>")
        if draft:
            parts.append(f"<div><b>{self.pet_name}</b><br>{MARKDOWN.render(draft)}</div>")
        self.transcript.setHtml("".join(parts))
        self.transcript.verticalScrollBar().setValue(self.transcript.verticalScrollBar().maximum())

    def request_send(self):
        text = self.input.toPlainText().strip()
        if text:
            self.input.clear()
            self.send_requested.emit(text)

    def copy_last_reply(self):
        if not self.current_id:
            return
        for row in reversed(self.store.messages(self.current_id)):
            if row["role"] == "assistant":
                QApplication.clipboard().setText(row["content"])
                self.status.setText("Reply copied")
                return

    def reload_tasks(self):
        self.todo_list.clear()
        for row in self.store.tasks():
            mark = "✓" if row["status"] == "done" else "○"
            due = f" · {row['due_date']}" if row["due_date"] else ""
            item = QListWidgetItem(f"{mark}  #{row['id']}  {row['title']}{due}")
            item.setData(Qt.ItemDataRole.UserRole, dict(row))
            self.todo_list.addItem(item)

    def fill_task(self, item, previous):
        if item:
            row = item.data(Qt.ItemDataRole.UserRole)
            self.todo_title.setText(row["title"])
            self.todo_notes.setText(row["notes"])
            self.todo_due.setText(row["due_date"] or "")

    def add_task(self):
        try:
            self.store.add_task(self.todo_title.text(), self.todo_notes.text(), self.todo_due.text().strip() or None)
            self.todo_title.clear()
            self.todo_notes.clear()
            self.todo_due.clear()
            self.reload_tasks()
        except ValueError as exc:
            QMessageBox.warning(self, "Task error", str(exc))

    def selected_task_id(self):
        item = self.todo_list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole)["id"] if item else None

    def edit_task(self):
        ident = self.selected_task_id()
        if ident:
            try:
                self.store.update_task(ident, title=self.todo_title.text(), notes=self.todo_notes.text(), due_date=self.todo_due.text().strip())
                self.reload_tasks()
            except ValueError as exc:
                QMessageBox.warning(self, "Task error", str(exc))

    def complete_task(self):
        ident = self.selected_task_id()
        if ident:
            self.store.complete_task(ident)
            self.reload_tasks()

    def delete_task(self):
        ident = self.selected_task_id()
        if ident:
            self.store.delete_task(ident)
            self.reload_tasks()

    def reload_memories(self):
        self.memory_list.clear()
        for row in self.store.memories():
            item = QListWidgetItem(row["content"])
            item.setData(Qt.ItemDataRole.UserRole, row["id"])
            self.memory_list.addItem(item)

    def add_memory(self):
        text, ok = QInputDialog.getMultiLineText(self, "Save memory", "What should jamun remember?")
        if ok and text.strip():
            self.store.add_memory(text)
            self.reload_memories()

    def edit_memory(self):
        item = self.memory_list.currentItem()
        if item:
            text, ok = QInputDialog.getMultiLineText(self, "Edit memory", "Memory", item.text())
            if ok and text.strip():
                self.store.update_memory(item.data(Qt.ItemDataRole.UserRole), text)
                self.reload_memories()

    def delete_memory(self):
        item = self.memory_list.currentItem()
        if item:
            self.store.delete_memory(item.data(Qt.ItemDataRole.UserRole))
            self.reload_memories()


class PreviewDialog(QDialog):
    def __init__(self, actions):
        super().__init__()
        self.setWindowTitle("jamun animation preview")
        self.resize(950, 650)
        layout = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        rows = QVBoxLayout(content)
        for name, action in actions.items():
            row = QHBoxLayout()
            title = QLabel(name)
            title.setFixedWidth(100)
            row.addWidget(title)
            for frame in action["frames"]:
                label = QLabel()
                label.setPixmap(frame.scaled(48, 48, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.FastTransformation))
                row.addWidget(label)
            row.addStretch()
            rows.addLayout(row)
        rows.addStretch()
        scroll.setWidget(content)
        layout.addWidget(scroll)
