import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DESTINATION = Path.home() / ".config" / "autostart" / "jamun.desktop"
LEGACY_DESTINATION = DESTINATION.with_name("pengu.desktop")


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
        DESTINATION.write_text(
            "[Desktop Entry]\nType=Application\nName=jamun\nComment=Desktop penguin companion\n"
            f"Exec={sys.executable} {ROOT / 'main.py'} --command hide\n"
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
