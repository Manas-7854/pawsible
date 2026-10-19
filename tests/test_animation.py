import json
import math
from pathlib import Path

import pytest
from PySide6.QtCore import QPointF
from PySide6.QtGui import QEnterEvent
from PySide6.QtWidgets import QApplication

from jamun.animation import load_manifest
from jamun.app import next_state
from jamun.ui import PetWindow


ROOT = Path(__file__).resolve().parents[1]


def test_manifest_frames_are_individual_cells():
    app = QApplication.instance() or QApplication([])
    actions = load_manifest(ROOT / "animation.json")
    assert {"idle", "walk", "jump", "slip", "dive", "reaction"} <= set(actions)
    assert all(frame.size().width() == 16 and frame.size().height() == 16 for action in actions.values() for frame in action["frames"])
    assert all(not frame.toImage().isNull() and any(frame.toImage().pixelColor(x, y).alpha() for y in range(16) for x in range(16)) for action in actions.values() for frame in action["frames"])


def test_visibility_transitions():
    assert next_state("hidden", "toggle") == "chat"
    assert next_state("chat", "toggle") == "hidden"
    assert next_state("pet", "toggle") == "hidden"
    assert next_state("hidden", "focus") == "chat"
    assert next_state("pet", "focus") == "chat"
    assert next_state("chat", "focus") == "pet"


def test_roaming_reaches_multiple_directions_within_screen():
    app = QApplication.instance() or QApplication([])
    pet = PetWindow(load_manifest(ROOT / "animation.json"))
    area = app.primaryScreen().availableGeometry()
    x = area.center().x() - pet.width() // 2
    y = area.center().y() - pet.height() // 2
    movements = []
    for _ in range(40):
        pet.move(x, y)
        assert pet.start_trip()
        tx, ty = pet.target
        assert math.hypot(tx - x, ty - y) >= 90
        assert area.left() <= tx <= area.right() - pet.width() + 1
        assert area.top() <= ty <= area.bottom() - pet.height() + 1
        movements.append((tx - x, ty - y))
    pet.animation_timer.stop()
    assert any(dx > 0 for dx, _ in movements)
    assert any(dx < 0 for dx, _ in movements)
    assert any(dy > 0 for _, dy in movements)
    assert any(dy < 0 for _, dy in movements)
    assert any(dx and dy for dx, dy in movements)


def test_long_trip_can_cross_to_opposite_edge(monkeypatch):
    app = QApplication.instance() or QApplication([])
    pet = PetWindow(load_manifest(ROOT / "animation.json"))
    area = app.primaryScreen().availableGeometry()
    monkeypatch.setattr("jamun.ui.random.random", lambda: 0.0)
    left = area.left() + 30
    right = area.right() - pet.width() - 30
    for origin, direction in ((left, 1), (right, -1)):
        pet.move(origin, area.center().y())
        assert pet.start_trip()
        assert (pet.target[0] - origin) * direction > area.width() * 0.5
    pet.animation_timer.stop()


def test_idle_frames_are_upright():
    manifest = json.loads((ROOT / "animation.json").read_text())
    assert manifest["actions"]["idle"]["frames"] == [[0, 0, 16, 16], [0, 16, 16, 16]]


def test_hover_interrupts_roaming_with_reaction():
    app = QApplication.instance() or QApplication([])
    pet = PetWindow(load_manifest(ROOT / "animation.json"))
    area = app.primaryScreen().availableGeometry()
    pet.move(area.center().x(), area.center().y())
    assert pet.start_trip()
    assert 60 <= pet.speed <= 90
    point = QPointF(1, 1)
    pet.enterEvent(QEnterEvent(point, point, point))
    assert pet.target is None
    assert pet.action == "reaction"
    pet.animation_timer.stop()
