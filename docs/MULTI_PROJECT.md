# Multi-project tracking: first milestone

Status: built and installed locally on 2026-09-23; not publicly released.

The packaged build passed six multi-project tests, six provider-process tests
(including both 45-second timeout fallbacks), and a Windows UI smoke test. The UI
expanded from a 26 x 26 dot to four rows (292 x 312), then resized to three rows
(292 x 232) when one fixture session closed. The installed binaries match this
candidate. Existing Claude/Codex hook configuration was preserved.

These checks use controlled fixtures. Four actual AI client sessions still need
a live acceptance pass before public release.

## What changes for you

Click the Vigil dot to see active sessions across projects, including agents still
working. Each row identifies its project and session, with a provider label. Hover
for full paths and session IDs. If more than four sessions are active, click the
more-sessions row and choose the agent you want; its controls move into view.

Requests still take priority. Working, completed and idle states do not cause
pop-ups. Opening the panel manually does not replay already viewed requests.
Looking at one project's terminal no longer silences requests from other projects.
When a window title cannot identify one agent uniquely, Vigil keeps the notification
eligible instead of guessing which agent you are watching.

Approval buttons answer only their associated request. Missing, expired and already
answered requests are rejected. Two competing decisions cannot overwrite each other.
Closing one session leaves the other sessions intact.

## Verification

Automated tests use temporary data, not your real agents or approvals:

- Four concurrent hook processes: two projects, two sessions each, mixed Claude and
  Codex fixtures. Answer overlapping requests out of order and verify exact routing.
- Same-named folders in different locations remain separate projects.
- Session IDs that would collide as Windows filenames remain separate.
- Expired, malformed, missing and competing decisions fail safely.
- Isolated Qt tests cover visibility, resizing, overflow selection, focus ambiguity,
  quiet states, notification batching and approval refresh.

Run from the repository root:

    python -m unittest discover -s tests -v

For a packaged Windows build, point the same hook tests at the executable:

    $env:VIGIL_TEST_HOOK = "C:/path/to/Vigil/hook/vigil-hook.exe"
    python -m unittest discover -s tests -p test_multi_project.py -v
    python -m unittest discover -s tests -p test_hook_process.py -v
    Remove-Item Env:VIGIL_TEST_HOOK

With other Vigil instances closed, the isolated desktop smoke test checks startup,
four visible working sessions, and resizing when one session closes:

    python tools/smoke_packaged_widget.py C:/path/to/Vigil/Vigil.exe

## Live acceptance check before release

1. Build/install this source version through the normal release process.
2. Start two supported local agent sessions in each of two project folders.
3. Click the dot; verify all four sessions have distinct rows.
4. Trigger harmless approval requests in both projects. Answer one and verify only
   that agent resumes. Deny the other and verify the other agent remains intact.
5. Focus one project while the other requests input; verify it remains visible.
6. Leave agents working and completed; verify these states cause no pop-ups.
7. Close one agent; verify three remain. With five sessions, use the overflow chooser.

## Limits and follow-on work

These tests exercise the hook protocol and widget; they are not a live end-to-end
validation of four AI clients. The local installed executable now contains this milestone; public downloads have not been updated.
Each client must emit supported hooks. Browser chats and remote agents are not
automatically discovered.

Two agents that provide neither a session ID nor an agent ID in the same directory
cannot be distinguished; folder identity alone is insufficient. Foreground window
routing also remains best-effort when multiple terminals share a title.

Next: project-grouped navigation, project-specific mute controls, and a guided live
setup check. Cross-device tracking remains separate future work.

## Moving Vigil between monitors

Drag the dot or the body of the expanded panel to another monitor and release it.
Vigil saves that position. Expanding, collapsing and restarting keep it on the
selected display. Dragging through a gap between displays no longer resets it to
the primary monitor. Releasing in a gap snaps it to the nearest visible edge.

Monitor tests cover both directions, negative desktop coordinates, saved secondary
positions and expansion/collapse. If a saved monitor is disconnected, Vigil falls
back to the primary display. An empty panel now explains that nothing needs you
instead of rendering a transparent rectangle.

Validation: 79 regression tests passed after the monitor fix. The rebuilt Windows
widget also passed its packaged smoke test at (2860, 400) on the secondary display
and is installed locally. A new public download release has not been published.
