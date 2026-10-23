import json
import math
import shutil
import time
from pathlib import Path

import pytest
from PySide6.QtCore import QPointF
from PySide6.QtGui import QColor, QEnterEvent, QImage
from PySide6.QtNetwork import QLocalServer
from PySide6.QtWidgets import QApplication

from jamun.animation import load_characters, load_manifest
from jamun.app import JamunApp, next_state
from jamun.storage import Store
from jamun.ui import PetWindow, SettingsDialog


ROOT = Path(__file__).resolve().parents[1]


def write_synthetic_penguin_sheets(root):
    (root / "sprites").mkdir()
    for name, (width, height) in {"Pingu.png": (128, 112), "WALK_SPRITE_SHEET.png": (48, 32)}.items():
        sheet = QImage(width, height, QImage.Format.Format_ARGB32)
        sheet.fill(QColor(0, 0, 0, 0))
        for y in range(0, height, 16):
            for x in range(0, width, 16):
                sheet.setPixelColor(x + 8, y + 8, QColor("#445566"))
        assert sheet.save(str(root / "sprites" / name))


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


def test_optional_character_assets_and_switching(tmp_path):
    qt = QApplication.instance() or QApplication([])
    write_synthetic_penguin_sheets(tmp_path)
    (tmp_path / "animations").mkdir()
    shutil.copyfile(ROOT / "animation.json", tmp_path / "animation.json")
    shutil.copyfile(ROOT / "animations" / "fox.json", tmp_path / "animations" / "fox.json")
    (tmp_path / "characters.json").write_text(json.dumps({
        "penguin": {"label": "Penguin", "manifest": "animation.json"},
        "fox": {"label": "Fox", "manifest": "animations/fox.json", "optional": True},
    }))
    characters = load_characters(tmp_path / "characters.json")
    assert list(characters) == ["penguin"]

    fox_dir = tmp_path / "fox sprites"
    fox_dir.mkdir()
    sheet = QImage(448, 224, QImage.Format.Format_ARGB32)
    sheet.fill(QColor(0, 0, 0, 0))
    for y in range(0, 224, 32):
        for x in range(0, 448, 32):
            sheet.setPixelColor(x + 16, y + 16, QColor("#dd7733"))
    assert sheet.save(str(fox_dir / "Fox Sprite Sheet.png"))
    characters = load_characters(tmp_path / "characters.json")
    assert list(characters) == ["penguin", "fox"]
    assert len(characters["fox"]["actions"]["walk"]["frames"]) == 14

    store = Store(tmp_path / "data" / "jamun.sqlite3")
    dialog = SettingsDialog(store, characters)
    dialog.character.setCurrentIndex(dialog.character.findData("fox"))
    dialog.accept()
    assert store.setting("character") == "fox"
    app = JamunApp(qt, QLocalServer(), store, characters, "")
    assert app.character_id == "fox"
    app.command("character:penguin")
    assert app.character_id == "penguin"
    assert store.setting("character") == "penguin"
    app.quit()


def test_all_character_manifests_load_with_local_sheets(tmp_path):
    app = QApplication.instance() or QApplication([])
    shutil.copyfile(ROOT / "animation.json", tmp_path / "animation.json")
    shutil.copyfile(ROOT / "characters.json", tmp_path / "characters.json")
    write_synthetic_penguin_sheets(tmp_path)
    (tmp_path / "animations").mkdir()
    for manifest_path in (ROOT / "animations").glob("*.json"):
        shutil.copyfile(manifest_path, tmp_path / "animations" / manifest_path.name)
        manifest = json.loads(manifest_path.read_text())
        sheets = {}
        for action in manifest["actions"].values():
            x, y, width, height, count = action["strip"]
            source = (tmp_path / "animations" / action["source"]).resolve()
            size = sheets.setdefault(source, [0, 0, []])
            size[0] = max(size[0], x + width * count)
            size[1] = max(size[1], y + height)
            size[2].extend((x + index * width + width // 2, y + height // 2) for index in range(count))
        for source, (width, height, pixels) in sheets.items():
            source.parent.mkdir(parents=True, exist_ok=True)
            sheet = QImage(width, height, QImage.Format.Format_ARGB32)
            sheet.fill(QColor(0, 0, 0, 0))
            for x, y in pixels:
                sheet.setPixelColor(x, y, QColor("#445566"))
            assert sheet.save(str(source))

    characters = load_characters(tmp_path / "characters.json")
    assert set(characters) == {"penguin", "midnight_cat", "shadow_cat", "white_cat", "fox"}
    for character in characters.values():
        assert {"idle", "walk", "jump", "reaction"} <= character["actions"].keys()
        assert all(action["frames"] for action in character["actions"].values())


def test_saved_missing_character_starts_with_penguin(tmp_path):
    qt = QApplication.instance() or QApplication([])
    store = Store(tmp_path / "jamun.sqlite3")
    store.set_setting("character", "fox")
    characters = {"penguin": {
        "label": "Penguin", "actions": load_manifest(ROOT / "animation.json"),
        "play_actions": [], "hover_actions": ["reaction"], "rest_actions": {}, "render_crop": None,
    }}
    app = JamunApp(qt, QLocalServer(), store, characters, "")
    app.set_state("pet")
    assert app.character_id == "penguin"
    assert app.pet.isVisible()
    app.quit()


def test_jump_returns_to_resting_position():
    qt = QApplication.instance() or QApplication([])
    character = load_characters(ROOT / "characters.json")["penguin"]
    pet = PetWindow(character["actions"], play_actions=character["play_actions"], hover_actions=character["hover_actions"])
    area = qt.primaryScreen().availableGeometry()
    origin = (area.center().x(), area.center().y())
    pet.move(*origin)
    now = time.monotonic()
    assert pet.start_jump(now)
    pet.advance_jump(now + pet.hop_duration / 2)
    assert pet.y() < origin[1]
    assert pet.resting_position() == origin
    pet.advance_jump(now + pet.hop_duration + 0.01)
    assert (pet.x(), pet.y()) == origin
    assert pet.hop_origin is None
    pet.animation_timer.stop()
