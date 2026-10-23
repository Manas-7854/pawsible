# Your desktop pet

Jamun puts a little pet on your desktop. Click it to chat, keep todos, and save memories. The current version includes a penguin; choosing between multiple pets is not available yet.

Built for Fedora GNOME with Wayland and XWayland.

## Install

From this directory, with Python available:

```sh
python -m pip install -r requirements.txt
python main.py
```

The included `sprites/` directory provides the penguin animations.

To start Jamun automatically when you log in, run:

```sh
python install_startup.py install
```

The script adds a GNOME autostart entry that launches Jamun hidden at login. Run `python install_startup.py remove` to undo it.

## Set up chat

Create a [Gemini API key](https://ai.google.dev/gemini-api/docs/api-key) in Google AI Studio. Run `install -m 600 .env.example .env`, replace `replace-with-your-key` in `.env` with your key, then restart Jamun. Gemini-powered chat, todos, and memory use `gemini-3.5-flash-lite` by default; you can change the model in Settings. The pet works without a key.

## Controls

Run `python main.py --install-shortcuts` to add the default GNOME shortcuts:

| Shortcut | Action |
| --- | --- |
| `Shift+Space` | Open or focus chat |
| `Ctrl+Alt+Space` | Hide the pet and chat |

Click the pet to open chat, drag it to move it, or right-click it for Settings and Quit. In chat, `Ctrl+N` starts a conversation, `Ctrl+1/2/3` switches between Chat, Todos, and Memory, and `Esc` returns to the pet.

## Credits

Penguin sprites: [PENGU by stext25](https://stext25.itch.io/pengu).
