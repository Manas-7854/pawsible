import json
from collections import deque
from pathlib import Path

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap


def outlined_frame(frame, color, width):
    source = frame.toImage().convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
    size = source.size()
    opaque = {(x, y) for y in range(size.height()) for x in range(size.width()) if source.pixelColor(x, y).alpha()}
    image = QImage(size, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    edge = {(x, y) for y in range(size.height()) for x in range(size.width()) if (x == 0 or y == 0 or x == size.width() - 1 or y == size.height() - 1) and (x, y) not in opaque}
    exterior = set(edge)
    queue = deque(edge)
    while queue:
        x, y = queue.popleft()
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            neighbor = (x + dx, y + dy)
            if 0 <= neighbor[0] < size.width() and 0 <= neighbor[1] < size.height() and neighbor not in opaque and neighbor not in exterior:
                exterior.add(neighbor)
                queue.append(neighbor)
    for x, y in exterior:
        if any((x + dx, y + dy) in opaque for dy in range(-width, width + 1) for dx in range(-width, width + 1)):
            image.setPixelColor(x, y, color)
    painter = QPainter(image)
    painter.drawImage(0, 0, source)
    painter.end()
    return QPixmap.fromImage(image)


def load_manifest(path: Path):
    data = json.loads(path.read_text())
    result = {}
    for name, action in data["actions"].items():
        source = (path.parent / action["source"]).resolve()
        image = QPixmap(str(source))
        if image.isNull():
            raise ValueError(f"Cannot load animation source: {source}")
        frames = []
        rectangles = action.get("frames")
        if rectangles is None:
            x, y, width, height, count = action["strip"]
            rectangles = [[x + index * width, y, width, height] for index in range(count)]
        for raw in rectangles:
            rect = QRect(*raw)
            if rect.width() <= 0 or rect.height() <= 0 or not image.rect().contains(rect):
                raise ValueError(f"Invalid frame in {name}: {raw}")
            frames.append(image.copy(rect))
        if not frames or action["duration_ms"] < 30:
            raise ValueError(f"Invalid animation: {name}")
        hold_last = action.get("hold_last", 0)
        if not isinstance(hold_last, int) or not 0 <= hold_last <= 20:
            raise ValueError(f"Invalid hold time in {name}")
        frames.extend([frames[-1]] * hold_last)
        if any(frame.size() != frames[0].size() or not frame.toImage().hasAlphaChannel() for frame in frames):
            raise ValueError(f"Inconsistent frames in {name}")
        result[name] = {"frames": frames, "duration_ms": action["duration_ms"], "loop": bool(action["loop"])}
    return result


def load_characters(path: Path):
    registry = json.loads(path.read_text())
    characters = {}
    for ident, entry in registry.items():
        manifest_path = (path.parent / entry["manifest"]).resolve()
        manifest = json.loads(manifest_path.read_text())
        sources = {(manifest_path.parent / action["source"]).resolve() for action in manifest["actions"].values()}
        missing = [source for source in sources if not source.is_file()]
        if missing and entry.get("optional", False):
            continue
        actions = load_manifest(manifest_path)
        required = {"idle", "walk", "reaction", "jump"}
        if not required <= actions.keys():
            raise ValueError(f"{ident} needs idle, walk, reaction, and jump actions")
        size = actions["idle"]["frames"][0].size()
        if any(frame.size() != size for action in actions.values() for frame in action["frames"]):
            raise ValueError(f"{ident} has mixed frame sizes")
        if "outline" in entry:
            config = entry["outline"]
            color = QColor(config["color"])
            width = config["width"]
            alpha = config.get("alpha", 255)
            if not color.isValid() or not isinstance(width, int) or not 1 <= width <= 3 or not isinstance(alpha, int) or not 1 <= alpha <= 255:
                raise ValueError(f"{ident} has an invalid outline")
            color.setAlpha(alpha)
            cache = {}
            for action in actions.values():
                outlined = []
                for frame in action["frames"]:
                    key = frame.cacheKey()
                    if key not in cache:
                        cache[key] = outlined_frame(frame, color, width)
                    outlined.append(cache[key])
                action["frames"] = outlined
        render_crop = QRect(*entry["render_crop"]) if "render_crop" in entry else None
        if render_crop and (render_crop.width() <= 0 or render_crop.height() <= 0 or not QRect(0, 0, size.width(), size.height()).contains(render_crop)):
            raise ValueError(f"{ident} has an invalid display crop")
        play_actions = manifest.get("play_actions", [])
        hover_actions = manifest.get("hover_actions", ["reaction"])
        rest_actions = manifest.get("rest_actions", {})
        if any(action not in actions for action in play_actions + hover_actions + list(rest_actions)):
            raise ValueError(f"{ident} has an unknown behavior action")
        if not hover_actions:
            raise ValueError(f"{ident} needs at least one hover action")
        for name, seconds in rest_actions.items():
            if not isinstance(seconds, list) or len(seconds) != 2 or any(not isinstance(value, (int, float)) for value in seconds) or not 1 <= seconds[0] <= seconds[1] <= 120:
                raise ValueError(f"{ident} has an invalid rest duration for {name}")
        movement = entry.get("movement")
        if movement is not None and not isinstance(movement, str):
            raise ValueError(f"{ident} has an invalid default movement")
        characters[ident] = {"label": entry["label"], "actions": actions, "play_actions": play_actions, "hover_actions": hover_actions, "rest_actions": rest_actions, "render_crop": render_crop, "movement": movement}
    return characters


def load_movements(path: Path):
    registry = json.loads(path.read_text())
    movements = {}
    for ident, entry in registry.items():
        label = entry["label"]
        if not isinstance(label, str) or not label:
            raise ValueError(f"{ident} has an invalid label")
        speed = entry["speed"]
        if not isinstance(speed, list) or len(speed) != 2 or any(not isinstance(value, (int, float)) for value in speed) or not 1 <= speed[0] <= speed[1] <= 400:
            raise ValueError(f"{ident} has an invalid speed range")
        weights = entry["weights"]
        if not isinstance(weights, dict) or set(weights) - {"walk", "jump", "rest", "play"}:
            raise ValueError(f"{ident} has invalid behavior weights")
        if any(not isinstance(value, (int, float)) or value < 0 for value in weights.values()) or sum(weights.values()) <= 0:
            raise ValueError(f"{ident} has invalid behavior weights")
        pace = entry["pace"]
        if not isinstance(pace, (int, float)) or not 0.2 <= pace <= 4:
            raise ValueError(f"{ident} has an invalid pace")
        movements[ident] = {"label": label, "speed": (float(speed[0]), float(speed[1])), "weights": {name: float(value) for name, value in weights.items()}, "pace": float(pace)}
    if "balanced" not in movements:
        raise ValueError("A balanced movement is required as the default")
    return movements
