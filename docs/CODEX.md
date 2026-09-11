# Codex integration (Windows preview)

The Codex adapter is built and installed locally. The public v0.1.1 ZIP still
contains the earlier Claude-only build; do not use it to test Codex.

## Activate on this computer

1. Open a terminal and run `codex`.
2. Enter `/hooks` and review the seven Vigil entries from `~/.codex/hooks.json`.
3. Trust the Vigil entries. They point to `~/.vigil/app/hook/vigil-hook.exe`.
4. Start a fresh Codex session. The local Vigil widget is already running.

Codex deliberately skips changed hooks until you review them. Installation does
not grant trust, and Vigil must never bypass that review. Existing sessions may
need restarting to load the new definitions.

## Supported events

- Prompt submitted: quiet working dot.
- Permission request: widget approval, with Codex-specific allow/deny output.
- Stop: quiet completed dot.
- Interrupt: quiet idle dot.
- Subagent start/stop: separate rows when an agent ID is supplied.
- Session end: remove the session record.

A question in ordinary assistant text is not parsed as a permission request.
Ordinary chatgpt.com chats and remote/cloud sessions are outside this local hook
integration. Desktop/CLI coverage depends on that runtime emitting the hooks.

## Verification completed

- Source provider regression suite.
- Compiled executable: stdin input, session files, Stop JSON, session cleanup.
- Compiled executable: isolated allow and deny through the actual request and
  decision files, including clearing the actionable state.
- Compiled executable: unanswered request returns no decision after 45 seconds
  and removes its pending request, leaving normal Codex approval handling intact.
- Codex 0.153.4 diagnostics loaded local configuration successfully.

These are protocol integration tests. A real live Codex permission request still
needs checking after the one-time hook trust review. No test executes a real
force-push, deletion, or deployment.

## Build and test

From `app/`, build `Hook.spec` and `Vigil.spec` separately with PyInstaller. The
hook uses the console subsystem to preserve stdin/stdout; the widget remains a
windowed executable. The hook must never import Qt.

From the repository root:

```powershell
python -m unittest discover -s tests -v
$env:VIGIL_TEST_HOOK = "$PWD\dist\vigil-hook\vigil-hook.exe"
python -m unittest discover -s tests -p test_hook_process.py -v
```

`VIGIL_DATA_DIR` isolates test events from real sessions. Do not set it for normal
usage. Source setup accepts `install-codex` or `--install-codex`; it preserves
other hooks and backs up the configuration first.

## Start Vigil by asking Codex

Once the skill is installed, say **start vigil** in a fresh Codex task. Codex
runs a bundled launcher, checks whether the widget is already running, and
starts it quietly if necessary. You can also ask **is Vigil running?** or
**stop vigil**.

Current source installers register this skill automatically in
`~/.agents/skills/vigil`. To add it to an existing Vigil installation, run:

```powershell
python app/vigil_setup.py install-skill
```

The skill needs to be installed once on each computer. It cannot start an app
that has not been downloaded and installed. The public v0.1.1 ZIP predates this
feature. Launching the widget does not bypass Codex's one-time `/hooks` review.
