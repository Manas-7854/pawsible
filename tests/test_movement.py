import json
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from jamun.animation import load_movements
from jamun.storage import Store
from jamun.ui import NameTag, PetWindow, SettingsDialog


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def qt_app():
    app = QApplication.instance() or QApplication([])
    yield app


def write_movements(path, data):
    path.write_text(json.dumps(data))
    return path


def test_shipped_movements_load():
    movements = load_movements(ROOT / "movements.json")
    assert "balanced" in movements
    for entry in movements.values():
        assert entry["speed"][0] <= entry["speed"][1]
        assert sum(entry["weights"].values()) > 0


def test_each_character_has_a_known_default_movement():
    movements = load_movements(ROOT / "movements.json")
    characters = json.loads((ROOT / "characters.json").read_text())
    for ident, entry in characters.items():
        assert entry["movement"] in movements, ident


def test_missing_balanced_is_rejected(tmp_path):
    path = write_movements(tmp_path / "m.json", {
        "calm": {"label": "Calm", "speed": [40, 60], "weights": {"walk": 1}, "pace": 1.0},
    })
    with pytest.raises(ValueError):
        load_movements(path)


def test_invalid_speed_is_rejected(tmp_path):
    path = write_movements(tmp_path / "m.json", {
        "balanced": {"label": "Balanced", "speed": [90, 40], "weights": {"walk": 1}, "pace": 1.0},
    })
    with pytest.raises(ValueError):
        load_movements(path)


def test_empty_weights_are_rejected(tmp_path):
    path = write_movements(tmp_path / "m.json", {
        "balanced": {"label": "Balanced", "speed": [40, 60], "weights": {"walk": 0, "jump": 0}, "pace": 1.0},
    })
    with pytest.raises(ValueError):
        load_movements(path)


def test_unknown_weight_key_is_rejected(tmp_path):
    path = write_movements(tmp_path / "m.json", {
        "balanced": {"label": "Balanced", "speed": [40, 60], "weights": {"sprint": 5}, "pace": 1.0},
    })
    with pytest.raises(ValueError):
        load_movements(path)


def test_out_of_range_pace_is_rejected(tmp_path):
    path = write_movements(tmp_path / "m.json", {
        "balanced": {"label": "Balanced", "speed": [40, 60], "weights": {"walk": 1}, "pace": 9},
    })
    with pytest.raises(ValueError):
        load_movements(path)


def test_pick_behavior_honors_weights(qt_app):
    pet = PetWindow({})
    pet.rest_actions = {}
    pet.behavior_weights = {"walk": 1, "jump": 0, "rest": 0, "play": 0}
    assert {pet.pick_behavior() for _ in range(50)} == {"walk"}


def test_pick_behavior_drops_rest_without_rest_actions(qt_app):
    pet = PetWindow({})
    pet.rest_actions = {}
    pet.behavior_weights = {"rest": 1}
    assert pet.pick_behavior() == "walk"


def test_pick_behavior_allows_rest_with_rest_actions(qt_app):
    pet = PetWindow({})
    pet.rest_actions = {"sleep": [1, 2]}
    pet.behavior_weights = {"rest": 1}
    assert pet.pick_behavior() == "rest"


def test_settings_dialog_saves_name_and_movement(qt_app, tmp_path):
    store = Store(tmp_path / "jamun.sqlite3")
    movements = load_movements(ROOT / "movements.json")
    dialog = SettingsDialog(store, {"penguin": {"label": "Penguin"}}, movements)
    dialog.name.setText("Pengu")
    dialog.movement.setCurrentIndex(dialog.movement.findData("energetic"))
    dialog.show_name.setChecked(True)
    dialog.accept()
    assert store.setting("pet_name") == "Pengu"
    assert store.setting("movement") == "energetic"
    assert store.setting("show_name") == "1"


def test_settings_dialog_keeps_movement_on_the_character_default(qt_app, tmp_path):
    store = Store(tmp_path / "jamun.sqlite3")
    movements = load_movements(ROOT / "movements.json")
    dialog = SettingsDialog(store, {"penguin": {"label": "Penguin"}}, movements)
    assert dialog.movement.findData("") == 0
    dialog.accept()
    assert store.setting("movement") == ""


def test_name_tag_resizes_to_its_text(qt_app):
    tag = NameTag()
    tag.set_text("Pengu")
    narrow = tag.width()
    tag.set_text("A much longer pet name")
    assert tag.width() > narrow
