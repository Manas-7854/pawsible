import os
import socket
import stat
import sys
import tempfile
import time


def signal_running_instance(name, command):
    if not hasattr(os, "getuid") or not hasattr(socket, "AF_UNIX"):
        return False
    address = os.path.join(tempfile.gettempdir(), f"{name}-{os.getuid()}")
    try:
        target = os.stat(address, follow_symlinks=False)
        if target.st_uid != os.getuid() or not stat.S_ISSOCK(target.st_mode):
            return False
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(0.2)
            client.connect(address)
            client.sendall(command.encode())
        return True
    except OSError:
        return False


if __name__ == "__main__":
    command = sys.argv[2] if len(sys.argv) == 3 and sys.argv[1] == "--command" and sys.argv[2] in {"toggle", "focus", "hide", "pet", "chat", "quit"} else None
    for legacy_name in ("jamun", "pengu") if hasattr(os, "getuid") else ():
        legacy_socket = os.path.join(tempfile.gettempdir(), f"{legacy_name}-{os.getuid()}")
        if signal_running_instance(legacy_name, "quit"):
            deadline = time.monotonic() + 40
            while os.path.exists(legacy_socket) and time.monotonic() < deadline:
                time.sleep(0.1)
            if os.path.exists(legacy_socket):
                raise SystemExit(f"The old {legacy_name} instance did not exit; try again after quitting it.")
            if command == "quit" and legacy_name == "pengu":
                raise SystemExit(0)
    from jamun.app import main

    raise SystemExit(main())
