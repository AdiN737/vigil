# What Vigil costs, measured

Something that runs all day has to justify its footprint with numbers, not
adjectives. Re-run these yourself:

```
python tools/bench.py --exe ~/.vigil/app/hook/vigil-hook.exe
```

## Measured on a Windows 11 laptop, 19 Sep 2026 (v0.2.0)

| | |
|---|---|
| Hook, per event | **~240 ms**, p95 ~320 ms |
| …of which is Vigil's own work | **under 10 ms** |
| Widget, resident memory | **55 MB** |
| Widget, CPU while idle | **0.01% of one core** |

## Why the hook costs 240 ms, and why it is not what it looks like

Almost all of it is Windows starting a self-contained Python binary. An
*empty* PyInstaller executable measured **286 ms** on the same machine, so the
floor is the runtime, not Vigil: everything our hook does — parse the payload,
write one small JSON file, exit — fits in the remaining few milliseconds.

The part that matters more is **how often it runs**. Vigil deliberately does
not register `PreToolUse`, the hook that fires on every single tool call.
It runs on turn boundaries only:

| Event | When |
|---|---|
| `Notification` | the agent asks you something |
| `PermissionRequest` | the agent needs approval |
| `Stop` / `SubagentStop` | the turn finished |
| `SessionEnd` | the session closed |
| `UserPromptSubmit` (Codex) | you sent a prompt |

So a turn with forty tool calls pays this cost once or twice, at the moment
the agent is already finished or already waiting — not forty times mid-flight.

To cut the floor itself we would have to ship a native launcher instead of a
frozen Python binary. That is worth doing if anyone's numbers say the startup
cost is being felt; it is not worth the build complexity before then.

## What Vigil measures about itself

The widget and hook record timings locally to `~/.vigil/metrics.jsonl`:
how long agents sat blocked, how fast approvals were answered, how long after
an event the pill appeared, and how many interruptions were suppressed.
Right-click the dot → **What Vigil did…**, or run `Vigil.exe --stats`.

The file holds durations, tiers and truncated session ids — never a command,
path or prompt. It is capped at 512 KB, trimmed oldest-first, and never leaves
the machine. There is no telemetry endpoint in this product.
