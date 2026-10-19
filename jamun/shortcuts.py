import ast
import os
import shlex
import subprocess
import sys
from pathlib import Path


SCHEMA = "org.gnome.settings-daemon.plugins.media-keys"
ITEM_SCHEMA = "org.gnome.settings-daemon.plugins.media-keys.custom-keybinding"
BASE = "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/"


def _gsettings(*args):
    result = subprocess.run(["gsettings", *args], capture_output=True, text=True, check=False)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "GNOME settings could not be updated")
    return result.stdout.strip()


def install_shortcuts(root: Path, open_binding: str, hide_binding: str):
    session = os.environ.get("XDG_SESSION_TYPE", "").lower()
    desktop = os.environ.get("XDG_CURRENT_DESKTOP", "").upper()
    if session not in ("wayland", "x11") or "GNOME" not in desktop:
        raise RuntimeError(f"Global shortcut installation is supported on GNOME Wayland and GNOME X11; detected {session or 'unknown'} / {desktop or 'unknown'}")
    raw = _gsettings("get", SCHEMA, "custom-keybindings")
    paths = [path for path in ast.literal_eval(raw.removeprefix("@as ").strip())
             if path not in (BASE + "pengu-toggle/", BASE + "pengu-focus/", BASE + "pengu-open/", BASE + "pengu-hide/")]
    for name, binding, command in (("open", open_binding, "chat"), ("hide", hide_binding, "hide")):
        path = BASE + f"jamun-{name}/"
        schema = f"{ITEM_SCHEMA}:{path}"
        launch = f"{shlex.quote(sys.executable)} {shlex.quote(str(root / 'main.py'))} --command {command}"
        _gsettings("set", schema, "name", f"jamun {name}")
        _gsettings("set", schema, "command", launch)
        _gsettings("set", schema, "binding", binding)
        if path not in paths:
            paths.append(path)
    _gsettings("set", SCHEMA, "custom-keybindings", str(paths))


def remove_shortcuts():
    raw = _gsettings("get", SCHEMA, "custom-keybindings")
    paths = ast.literal_eval(raw.removeprefix("@as ").strip())
    paths = [path for path in paths if path not in (
        BASE + "pengu-toggle/", BASE + "pengu-focus/", BASE + "pengu-open/", BASE + "pengu-hide/",
        BASE + "jamun-open/", BASE + "jamun-hide/"
    )]
    _gsettings("set", SCHEMA, "custom-keybindings", str(paths))
