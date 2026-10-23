import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DESTINATION = Path.home() / ".config" / "autostart" / "jamun.desktop"
LEGACY_DESTINATION = DESTINATION.with_name("pengu.desktop")


def desktop_exec_arg(value):
    # Desktop-entry Exec quoting has two escaping layers, unlike shell quoting.
    escaped = []
    for char in str(value):
        if char == "%":
            escaped.append("%%")
        elif char == "\\":
            escaped.append("\\" * 4)
        elif char in ('"', "`", "$"):
            escaped.append("\\" * 2 + char)
        else:
            escaped.append(char)
    return '"' + "".join(escaped) + '"'


def remove_legacy_entry():
    if LEGACY_DESTINATION.exists() and str(ROOT / "main.py") in LEGACY_DESTINATION.read_text():
        LEGACY_DESTINATION.unlink()
        print(f"Removed old startup entry {LEGACY_DESTINATION}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["install", "remove"])
    args = parser.parse_args()
    if args.action == "install":
        DESTINATION.parent.mkdir(parents=True, exist_ok=True)
        launch = f"{desktop_exec_arg(sys.executable)} {desktop_exec_arg(ROOT / 'main.py')} --command hide"
        DESTINATION.write_text(
            "[Desktop Entry]\nType=Application\nName=Pawsible\nComment=Desktop pet companion\n"
            f"Exec={launch}\n"
            "Terminal=false\nX-GNOME-Autostart-enabled=true\n"
        )
        print(f"Installed {DESTINATION}")
        remove_legacy_entry()
    else:
        if DESTINATION.exists():
            DESTINATION.unlink()
            print(f"Removed {DESTINATION}")
        remove_legacy_entry()


if __name__ == "__main__":
    main()
