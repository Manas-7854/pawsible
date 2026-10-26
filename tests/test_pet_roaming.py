from pathlib import Path

import pytest
from PySide6.QtCore import QRect
from PySide6.QtWidgets import QApplication

from jamun.animation import load_manifest
from jamun.ui import PetWindow, cross_waypoints

ROOT = Path(__file__).resolve().parents[1]
SIZE = (80, 80)
MARGIN = 18


@pytest.fixture(scope="module")
def pet():
    QApplication.instance() or QApplication([])
    return PetWindow(load_manifest(ROOT / "animation.json"))


def test_cross_to_right_display_walks_to_right_edge_then_jumps_in():
    here = QRect(0, 0, 1920, 1080)
    there = QRect(1920, 0, 1280, 1024)
    walk, entry = cross_waypoints(here, there, (300, 500), SIZE)
    assert walk == (float(here.right() - SIZE[0] - MARGIN), 500.0)
    assert entry == (float(there.left() + MARGIN), 500.0)


def test_cross_to_left_display_mirrors_the_edges():
    here = QRect(1920, 0, 1280, 1024)
    there = QRect(0, 0, 1920, 1080)
    walk, entry = cross_waypoints(here, there, (2400, 400), SIZE)
    assert walk == (float(here.left() + MARGIN), 400.0)
    assert entry == (float(there.right() - SIZE[0] - MARGIN), 400.0)


def test_cross_to_display_below_uses_vertical_edges():
    here = QRect(0, 0, 1920, 1080)
    there = QRect(0, 1080, 1920, 1080)
    walk, entry = cross_waypoints(here, there, (500, 300), SIZE)
    assert walk == (500.0, float(here.bottom() - SIZE[1] - MARGIN))
    assert entry == (500.0, float(there.top() + MARGIN))


def test_entry_point_is_clamped_into_a_smaller_target_display():
    here = QRect(0, 0, 1920, 1080)
    there = QRect(1920, 0, 800, 600)
    walk, entry = cross_waypoints(here, there, (300, 1000), SIZE)
    assert entry[1] == float(there.bottom() - SIZE[1] - MARGIN)


def test_cross_hop_faces_the_target_display(pet):
    pet.move(800, 300)
    pet.facing_left = False
    pet.start_jump(1.0, target=(100, 300))
    assert pet.facing_left is True
    pet.hop_origin = None
    pet.hop_target = None
    pet.start_jump(2.0, target=(1500, 300))
    assert pet.facing_left is False


def test_in_place_hop_keeps_facing(pet):
    pet.move(600, 300)
    pet.facing_left = True
    pet.start_jump(3.0)
    assert pet.facing_left is True
