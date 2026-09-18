VIGIL
Ambient status for your AI coding agents.

WHAT IT DOES
  A small dot lives in the corner of your screen. When a Claude Code session
  needs you - a permission prompt, a question, a failure - it unfurls into a
  pill telling you which project and how long it has been waiting. Click it to
  jump straight to that window. Then it folds back to a dot.

  It stays quiet while agents are working. That is the point.

INSTALL
  Double-click "Install Vigil.bat".

  It copies Vigil to %USERPROFILE%\.vigil\app, registers the Claude Code
  hooks (backing up your settings.json first), and starts it.

  No Python needed. Nothing to configure.

USING IT
  Right-click the dot, or the tray icon by your clock:
    - Mute pop-ups
    - Start with Windows
    - How long pop-ups stay (3 / 5 / 8 / 12 seconds)
    - Reset position
    - Connect / disconnect from Claude Code

  Drag the dot anywhere. It remembers, and the pill unfurls away from the
  nearest screen edge.

REMOVE
  Double-click "Uninstall Vigil.bat". It unregisters the hooks, clears
  autostart, and deletes ~/.vigil. Your settings.json is backed up first.

NOTES
  - Install to local disk, not OneDrive. Running from a synced folder made
    the agent hook 3.5x slower in testing.
  - Windows may warn that this is from an unknown publisher. The build is
    not code-signed yet.
