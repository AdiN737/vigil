# Vigil on macOS

**Status: source-level support. Not built, not tested, no release binary yet.**

Read that line again before you rely on any of this. The Python source has real
macOS implementations of everything that used to be Windows-only, and the import
hygiene is verified — but nobody has run it on a Mac. PyInstaller cannot
cross-compile, so the `.app` has to be built on a Mac by someone with a Mac.

If you build it and it works, or it doesn't,
[open an issue](https://github.com/AdiN737/vigil/issues) — that feedback is the
only thing standing between this and a real release.

---

## What actually differs from Windows

Four things are OS-specific. They all live in
[`app/vigil_platform.py`](../app/vigil_platform.py), so this is the whole surface:

| What | Windows | macOS |
|---|---|---|
| Read the focused window's title | `win32gui.GetWindowText` | AppleScript via `osascript`, asking System Events for `AXTitle` |
| Bring a window to the front | `EnumWindows` + `SetForegroundWindow` | AppleScript: walk visible windows, `AXRaise` the match |
| Only one Vigil at a time | Kernel named mutex | `fcntl.flock` on `~/.vigil/widget.lock` |
| Start at login | Registry `Run` key | LaunchAgent plist in `~/Library/LaunchAgents` |

Everything else — the widget UI, the tier ladder, the five anti-spam gates, the
hook protocol, the session files in `~/.vigil` — is already portable and unchanged.

## Accessibility permission is not optional

macOS will not let any app read another app's window titles without it.

**System Settings → Privacy & Security → Accessibility → enable Vigil.**

Without it, Vigil still runs and still tells you when an agent needs you, but
it loses two things:

- **Gate 3 ("are you already looking?")** stops working, so you'll get pinged
  about a terminal you're staring at.
- **Click-to-jump** stops working — clicking a pill won't raise that window.

`foreground_title()` falls back to the frontmost *application* name when the
window title is unavailable, which still catches the common "am I in Terminal
right now" case. Both functions fail soft and return `""` / `False`; nothing
crashes when permission is denied.

## Build it

On a Mac, with Python 3.11+:

```bash
git clone https://github.com/AdiN737/vigil.git
cd vigil
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt pyinstaller
```

Build the **hook first** — it must not link Qt:

```bash
cd app && pyinstaller Hook-macos.spec
```

Then the widget:

```bash
pyinstaller Vigil-macos.spec
```

Assemble a distributable folder:

```bash
mkdir -p ../dist-macos
cp -R dist/Vigil.app ../dist-macos/
cp dist/vigil-hook ../dist-macos/
cp install-macos.command ../dist-macos/
chmod +x ../dist-macos/install-macos.command ../dist-macos/vigil-hook
```

### Check the hook did not get Qt linked into it

This is the one thing worth verifying by hand. On Windows, a hook that loaded Qt
cost **3 seconds per agent turn**; splitting it took that to 171 ms. If the Mac
hook is tens of megabytes, the split has silently failed:

```bash
du -h dist/vigil-hook
```

Expect something in the low single-digit megabytes. If it's 40 MB+, Qt got
pulled in — check the `excludes` list in `Hook-macos.spec`.

Time it too:

```bash
echo '{"session_id":"t","cwd":"/tmp/demo","tool_name":"Bash","hook_event_name":"PreToolUse"}' \
  | time ./dist/vigil-hook working
```

Anything over ~300 ms means something is being imported that shouldn't be.

## Install it

Double-click `install-macos.command`, or run it. It copies Vigil to
`~/.vigil/app`, clears the Gatekeeper quarantine flag, registers the Claude Code
hooks (backing up `settings.json` first), and starts it.

Then **restart Claude Code** — hooks load at session start.

### Gatekeeper

The build isn't notarised, so macOS will refuse it on first run. The installer
clears the quarantine attribute for you. If you launch `Vigil.app` directly
instead and get *"cannot be opened because the developer cannot be verified"*:

```bash
xattr -dr com.apple.quarantine ~/.vigil/app/Vigil.app
```

Or right-click the app → **Open** → **Open**.

## Run from source instead

No build step, and honestly the better path while this is untested:

```bash
pip install -r requirements.txt
python3 app/vigil_setup.py --install    # register the hooks
python3 app/vigil_widget.py             # start the widget
```

Uninstall with `python3 app/vigil_setup.py --uninstall`.

## Known unknowns

Genuinely untested, listed so you know where to look when something is wrong:

- **Frameless always-on-top window.** Qt's `Qt.Tool | Qt.FramelessWindowHint`
  behaves differently on macOS, particularly across Spaces and full-screen apps.
  The dot may not float above a full-screened window.
- **`LSUIElement`.** Set in the bundle so Vigil stays out of the Dock and the
  app switcher. Unverified.
- **Menu-bar icon.** Qt's `QSystemTrayIcon` maps to a menu-bar extra on macOS;
  the icon may need a template-image treatment to look right in dark mode.
- **Retina rendering.** The widget draws with `QPainter` at runtime rather than
  shipping bitmaps, so it *should* scale cleanly, but nobody has looked at it on
  a 2x display.
- **LaunchAgent.** The plist is written with `KeepAlive` false, deliberately, so
  quitting Vigil from the menu bar doesn't have launchd resurrect it. Untested.
