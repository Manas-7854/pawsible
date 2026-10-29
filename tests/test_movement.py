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
    yield QApplication.instance() or QApplication([])


def test_shipped_config():
    movements = load_movements(ROOT / "movements.json")
    assert "balanced" in movements
    for entry in movements.values():
        assert entry["speed"][0] <= entry["speed"][1]
        assert sum(entry["weights"].values()) > 0


def test_character_defaults():
    movements = load_movements(ROOT / "movements.json")
    for ident, entry in json.loads((ROOT / "characters.json").read_text()).items():
        assert entry["movement"] in movements, ident


@pytest.mark.parametrize("profile, changes", [
    ("calm", {}),
    ("balanced", {"speed": [90, 40]}),
    ("balanced", {"weights": {"walk": 0, "jump": 0}}),
    ("balanced", {"weights": {"sprint": 5}}),
    ("balanced", {"pace": 9}),
])
def test_invalid_config(tmp_path, profile, changes):
    entry = dict(label="Balanced", speed=[40, 60], weights={"walk": 1}, pace=1.0)
    path = tmp_path / "m.json"
    path.write_text(json.dumps({profile: {**entry, **changes}}))
    with pytest.raises(ValueError):
        load_movements(path)


@pytest.mark.parametrize("weights, rests, expected", [
    ({"walk": 1, "jump": 0, "rest": 0, "play": 0}, {}, "walk"),
    ({"rest": 1}, {}, "walk"),
    ({"rest": 1}, {"sleep": [1, 2]}, "rest"),
])
def test_pick_behavior(qt_app, weights, rests, expected):
    pet = PetWindow({})
    pet.rest_actions = rests
    pet.behavior_weights = weights
    assert pet.pick_behavior() == expected


@pytest.mark.parametrize("movement", ["", "energetic"])
def test_settings(qt_app, tmp_path, movement):
    store = Store(tmp_path / "jamun.sqlite3")
    movements = load_movements(ROOT / "movements.json")
    dialog = SettingsDialog(store, {"penguin": {"label": "Penguin"}}, movements)
    index = dialog.movement.findData(movement)
    assert index >= 0
    if movement:
        dialog.movement.setCurrentIndex(index)
    else:
        assert index == 0 and dialog.movement.currentData() == ""
    dialog.name.setText("Pengu")
    dialog.show_name.setChecked(True)
    dialog.accept()
    assert store.setting("pet_name") == "Pengu"
    assert store.setting("movement") == movement
    assert store.setting("show_name") == "1"
    store.db.close()


def test_name_tag(qt_app):
    tag = NameTag()
    tag.set_text("Pengu")
    narrow = tag.width()
    tag.set_text("A much longer pet name")
    assert tag.width() > narrow
