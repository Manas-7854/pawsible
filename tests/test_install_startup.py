import sys

import install_startup


def test_autostart_exec_quotes_paths_with_spaces(tmp_path, monkeypatch):
    root = tmp_path / "Pawsible project"
    root.mkdir()
    destination = tmp_path / "autostart" / "jamun.desktop"
    executable = tmp_path / "Python environment" / "bin" / "python"
    monkeypatch.setattr(install_startup, "ROOT", root)
    monkeypatch.setattr(install_startup, "DESTINATION", destination)
    monkeypatch.setattr(install_startup, "LEGACY_DESTINATION", destination.with_name("pengu.desktop"))
    monkeypatch.setattr(install_startup.sys, "executable", str(executable))
    monkeypatch.setattr(sys, "argv", ["install_startup.py", "install"])

    install_startup.main()

    assert f'Exec="{executable}" "{root / "main.py"}" --command hide\n' in destination.read_text()
    assert "Name=Pawsible\n" in destination.read_text()
