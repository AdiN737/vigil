# Vigil

**A dot in the corner of your screen that tells you the moment Claude Code needs you — and lets you answer without leaving what you're doing.**

Free · Windows 10 & 11 · no account, no telemetry, no network calls.

---

## The problem

You give an agent a long task and go do something else. It works for seven
minutes, hits a permission prompt, and then sits there — silently, indefinitely.
You come back twenty minutes later and nineteen of them were wasted.

So you start checking. Alt-tab, glance, alt-tab back. Except checking *is* the
interruption: you break focus to find out you didn't need to. You end up
checking too often, or not often enough. Both waste the speed you're paying for.

## What Vigil does

A small dot lives in the corner of your screen. Most of the time that is all it
is. When a session genuinely needs a human, it unfurls into a pill showing which
project, what it is asking, and how long it has been waiting — with **Approve**
and **Deny** on it. Press one and the answer goes straight back to the agent.
Then it folds back to a dot.

Run five agents at once and each gets its own row, sorted by urgency, with the
dangerous one on top. Collapsed, the dot carries a count.

## Install

Grab the latest `Vigil-vX.Y.Z-windows.zip` from
[Releases](../../releases/latest), then:

1. **Extract it properly** — right-click → *Extract All*. Don't run it from
   inside the zip preview; Windows unpacks that to a temp folder and the install
   won't stick.
2. **Double-click `Install Vigil.bat`.** It copies Vigil to
   `%USERPROFILE%\.vigil\app`, registers the Claude Code hooks (backing up your
   `settings.json` first), and starts it.
3. Windows will say **"Windows protected your PC."** The build isn't
   code-signed yet — that warning means *unrecognised*, not *unsafe*. Click
   **More info → Run anyway**.
4. **Restart Claude Code.** Hooks load when a session starts, so existing
   windows won't report until you open a fresh one.

Look at the **bottom-right of your screen**, roughly an inch above the taskbar.

To remove it: double-click `Uninstall Vigil.bat`, or delete `%USERPROFILE%\.vigil`
and drop the Vigil entries from `.claude\settings.json`.

**You need Claude Code installed.** Vigil reads its hook events and does nothing
without them.

## The states

Seven tiers, copied here from `TIERS` in [`app/vigil_widget.py`](app/vigil_widget.py).
Three of them never interrupt you, and those three are most of the day.

| tier | state | colour | interrupts you |
|-----:|-------|--------|----------------|
| 1 | `idle` | `#6E7887` | no — colour only |
| 2 | `working` | `#4C8DFF` | no — colour only |
| 3 | `done` | `#3DD68C` | no — colour only |
| 4 | `question` | `#FFB020` | opens the pill |
| 5 | `blocked` | `#FF8C42` | opens the pill |
| 6 | `failed` | `#FF5C5C` | opens the pill |
| 7 | `destructive` | `#FF3B3B` | opens the pill, always |

`destructive` isn't a separate kind of event — it's a `blocked` one whose command
matched something you can't undo (`rm -rf`, `git push --force`, `drop table`,
`terraform apply`). It's the only tier that ignores every rate limit below.

## Why it doesn't spam you

Every would-be interruption runs five gates before it reaches your screen:

1. **Is it actionable?** Working, finished and idle never open the pill.
2. **Have we already told you?** One ping per session, not one per event.
3. **Are you already looking?** If the window that needs you is focused, silence.
4. **Is it too soon?** Each recent ping doubles the quiet period after it —
   45s, 90s, 180s, up to fifteen minutes.
5. **Can it wait for a friend?** Simultaneous prompts batch into one notice.

In testing, 500 agent events across five concurrent sessions produced zero
pop-ups. The constants that control all of this live at the top of
[`app/vigil_widget.py`](app/vigil_widget.py) — if it's too chatty or too quiet
for you, tune them there rather than adding new triggers.

## How it works

```
Claude Code  ──event──▶  vigil-hook.exe  ──writes──▶  ~/.vigil  ──polls──▶  the widget
                              ▲                                                  │
                              └────────── allow / deny ───────────────────────────┘
```

Two binaries, a folder of small JSON files, and no server. Every design choice
below exists because a measurement forced it.

- **Two binaries, not one.** The hook runs on every turn, so it can't afford to
  load a 91 MB UI framework to decide it has nothing to say. Splitting it out
  took the hook from 3 seconds to **171 ms**.
- **Five hooks, not six.** `PreToolUse` fires on literally every tool call.
  Dropping it cost nothing in coverage and gave back most of a 7-second-per-turn
  regression. Total overhead is now about **0.33 s per turn**.
- **Files, not a daemon.** One small JSON per session, written with an atomic
  replace so a busy agent can never half-overwrite what the widget is reading.
- **State lives in `~/.vigil`.** Not a synced folder (phantom sessions from other
  machines) and not `%LOCALAPPDATA%` (the Microsoft Store build of Python
  silently sandboxes writes there).
- **Fails open, always.** The hook is wrapped end to end. If Vigil breaks,
  throws, or is missing entirely, Claude Code prompts exactly as it would
  without it.

### What it reads

- The folder name of the project
- Which tool the agent is about to use
- The command or file path it's running — first 120 characters

It does **not** read your prompts, the agent's replies, or the contents of any
file. It makes no network calls of any kind.

## Repository layout

| Path | What |
|------|------|
| `app/` | The widget, the hook, setup and the approval bridge |
| `app/vigil_widget.py` | The UI, the tier table, and the anti-spam gates |
| `app/vigil_hook.py` | The fast hook Claude Code calls on every event |
| `app/vigil_setup.py` | Registers and removes the hooks in `settings.json` |
| `app/vigil_decide.py` | The allow/deny handshake between widget and hook |
| `poc/` | The 20-minute proof of concept — no GUI, no hardware |
| `design/renders/` | Concept renders of the hardware device |
| `design/cad/` | STL/3MF models and the generator scripts |
| `docs/HARDWARE.md` | Build guide for the physical device |

## Running from source

Needs Python 3.11+ and PySide6.

```bash
pip install PySide6
python app/vigil_widget.py          # the widget
python app/vigil_setup.py --install # register the hooks
```

Building the distributable uses the `.spec` files in `app/` with PyInstaller.
The widget and the hook build separately — that separation is the whole
performance story, so don't merge them.

## Status

**v0.1.1.** Windows only, Claude Code only, not code-signed. It has been
stress-tested across simulated eight-hour days, but you'll be among the first
real users — bug reports are genuinely useful.

Planned, and not built yet: a macOS build, watching other agents (ChatGPT,
Gemini, Cursor) through a browser extension bridged to the desktop app, and a
physical desk device with an LED ring and a dial you press to approve.

## License

MIT — see [LICENSE](LICENSE).
