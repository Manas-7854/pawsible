# jamun

A small local penguin companion for Fedora GNOME Wayland. It uses PySide6, SQLite, and Google's official `google-genai` SDK. The original sprite files remain untouched.

## Set up and launch

From this directory:

```sh
conda activate pgmpy_env
python -m pip install -r requirements.txt
python main.py
```

The first launch opens chat. To run hidden (as login startup does), use `python main.py --command hide`. A later `python main.py --command chat` signals the running instance. `python main.py --command quit` stops it.

Set your key by running `install -m 600 .env.example .env`, then replace the placeholder in `.env`; or export `GEMINI_API_KEY` before launch. The app makes an existing `.env` private on startup, and Git ignores it. Never put a real key into tracked files. Missing credentials do not prevent the app from starting; chat shows setup guidance. The default model is `gemini-3.5-flash-lite`, configurable in Settings. Google's [model page](https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash-lite) lists function calling support; [pricing](https://ai.google.dev/gemini-api/docs/pricing) lists a free tier where eligible. Model availability and limits depend on your account and region.

## Controls

Install GNOME system-wide shortcuts after launching successfully:

```sh
python main.py --install-shortcuts
```

Default bindings are `Shift+Space` (open/focus chat) and `Ctrl+Alt+Space` (hide the pet and chat). GNOME receives these bindings even when jamun lacks focus. Change their GNOME accelerator strings in Settings. Remove only jamun's bindings with `python main.py --remove-shortcuts`. Note that `Shift+Space` is global and can override that key combination in other apps.

Click the penguin to open chat; drag it to reposition. Escape or closing chat leaves the pet visible. Right-click the penguin for Open chat, Hide all, Pause movement, Settings, and Quit. A tray icon is also created, but stock GNOME Shell may not display StatusNotifier tray icons without an extension. When hidden, use a shortcut or `python main.py --command chat` to reopen it.

On GNOME Wayland with XWayland available, jamun uses Qt's X11 backend for the pet and chat windows. Native Wayland does not expose general top-level positioning to applications; XWayland movement was verified on this machine. jamun requests the X11 “all desktops” hint whenever its windows appear, so the pet can follow GNOME workspace changes. The pet also removes Qt's `WM_TAKE_FOCUS` protocol; otherwise GNOME may pick it instead of your last app when switching workspaces. GNOME still controls activation, focus restoration after Escape, and stacking. Dragging, animation, and wandering never request focus. The pet window's footprint is only one scaled sprite cell; hiding closes all input surfaces. Hovering over the pet plays a short reaction.

Chat supports streaming, Stop, Markdown, copying the last response, and conversation history. Shortcuts shown in the panel include `Ctrl+N` for a new conversation, `Ctrl+L` to focus the input, `Ctrl+1/2/3` for Chat/Todos/Memory, `Ctrl+.` to stop, and `Ctrl+Shift+C` to copy the last reply. Tasks and saved memories have separate tabs. You can explicitly save a memory in the Memory tab or begin a message with “remember that …”. Todo requests use only the implemented `add_task`, `list_tasks`, `update_task`, and `complete_task` functions. Gemini-proposed task changes require your approval. If a task is unclear, give its displayed ID. Replies have no live web search.

Data and settings are in the per-user Qt application data location, normally `~/.local/share/jamun/jamun.sqlite3` on Fedora. jamun restricts that directory and database to your account, including existing installations. On first launch, jamun copies existing history, todos, memories, and settings from `~/.local/share/Pengu/pengu.sqlite3` if present; the old database is left untouched as a backup. The app never writes the database into the project directory. Recent complete messages, saved memories, and task summaries are sent to Gemini; full history stays in SQLite. Network operations run in a worker thread and use bounded retries.

## Startup

After verifying that the app works, install login startup with:

```sh
python install_startup.py install
```

It creates `~/.config/autostart/jamun.desktop` and starts jamun hidden at login. Installation removes this project's old `pengu.desktop` entry to avoid duplicate launches. Remove it with `python install_startup.py remove`. Startup is opt-in; it was installed on this machine after live verification.

## Sprite and diagnostics

`sprites/Pingu.png` is a transparent 128×112 sheet of 16×16 cells. `sprites/WALK_SPRITE_SHEET.png` provides the separate walk animation. `animation.json` lists exact frame rectangles, durations, loops, and action names. See a nearest-neighbor frame preview with `python main.py --preview`. The asset package also includes GIFs labelled idle, jump, slip, dive, and attack; these informed the action mapping. Sprite author and license were not included with the provided files, so attribution and reuse rights are unknown. Both sprite directories are excluded from Git until licensed assets are available; a fresh clone cannot launch the pet without them.

Run focused tests with `QT_QPA_PLATFORM=offscreen python -m pytest -q`.
