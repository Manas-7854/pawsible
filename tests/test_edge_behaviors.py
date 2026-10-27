from pathlib import Path

import pytest
from PySide6.QtCore import QRect
from PySide6.QtWidgets import QApplication

from jamun.storage import Store
from jamun.ui import PetWindow, SettingsDialog, side_has_neighbor


@pytest.fixture(scope="module")
def qt_app():
    yield QApplication.instance() or QApplication([])


def test_free_edges_skips_a_taskbar_edge(qt_app):
    pet = PetWindow({})
    geometry = QRect(0, 0, 1000, 800)
    with_bottom_bar = QRect(0, 0, 1000, 760)
    assert pet.free_edges(with_bottom_bar, geometry) == ["left", "right", "top"]


def test_free_edges_skips_a_left_dock(qt_app):
    pet = PetWindow({})
    geometry = QRect(0, 0, 1000, 800)
    with_left_dock = QRect(60, 0, 940, 800)
    assert pet.free_edges(with_left_dock, geometry) == ["right", "top"]


def test_inner_edge_between_two_monitors_is_not_peekable():
    left_monitor = QRect(0, 0, 1920, 1080)
    right_monitor = QRect(1920, 0, 1920, 1080)
    assert side_has_neighbor("right", left_monitor, [right_monitor]) is True
    assert side_has_neighbor("left", left_monitor, [right_monitor]) is False
    assert side_has_neighbor("left", right_monitor, [left_monitor]) is True
    assert side_has_neighbor("right", right_monitor, [left_monitor]) is False


def test_a_vertically_separated_monitor_is_not_a_side_neighbor():
    monitor = QRect(0, 0, 1920, 1080)
    below = QRect(0, 1080, 1920, 1080)
    assert side_has_neighbor("left", monitor, [below]) is False
    assert side_has_neighbor("right", monitor, [below]) is False


def test_peek_is_not_clamped_back_on_screen(qt_app):
    pet = PetWindow({})
    pet.peek_phase = "out"
    pet.move(-40, 120)
    pet.keep_on_screen()
    assert pet.pos().x() == -40


def test_halt_clears_peek(qt_app):
    pet = PetWindow({})
    pet.peek_phase = "hold"
    pet.halt_movement()
    assert pet.peek_phase is None


def test_settings_dialog_saves_edge_antics(qt_app, tmp_path):
    store = Store(tmp_path / "jamun.sqlite3")
    dialog = SettingsDialog(store, {"penguin": {"label": "Penguin"}})
    assert dialog.edge_antics.isChecked()
    dialog.edge_antics.setChecked(False)
    dialog.accept()
    assert store.setting("edge_antics") == "0"
