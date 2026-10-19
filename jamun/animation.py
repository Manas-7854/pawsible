import json
from pathlib import Path

from PySide6.QtCore import QRect
from PySide6.QtGui import QPixmap


def load_manifest(path: Path):
    data = json.loads(path.read_text())
    result = {}
    for name, action in data["actions"].items():
        source = (path.parent / action["source"]).resolve()
        image = QPixmap(str(source))
        if image.isNull():
            raise ValueError(f"Cannot load animation source: {source}")
        frames = []
        for raw in action["frames"]:
            rect = QRect(*raw)
            if rect.width() <= 0 or rect.height() <= 0 or not image.rect().contains(rect):
                raise ValueError(f"Invalid frame in {name}: {raw}")
            frames.append(image.copy(rect))
        if not frames or action["duration_ms"] < 30:
            raise ValueError(f"Invalid animation: {name}")
        result[name] = {"frames": frames, "duration_ms": action["duration_ms"], "loop": bool(action["loop"])}
    return result
