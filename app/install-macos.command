#!/bin/bash
# Vigil installer for macOS.  Double-click this file in Finder, or run it.
#
# It copies Vigil into ~/.vigil/app, registers the Claude Code hooks, and
# starts it.  Nothing here needs sudo and nothing is written outside your
# home directory.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEST="$HOME/.vigil/app"

say()  { printf '\n\033[1m%s\033[0m\n' "$*"; }
ok()   { printf '  \033[32m✓\033[0m %s\n' "$*"; }
warn() { printf '  \033[33m!\033[0m %s\n' "$*"; }
die()  { printf '\n  \033[31m✗ %s\033[0m\n\n' "$*"; exit 1; }

say "Installing Vigil"

# ---- checks before we touch anything -------------------------------------
if [[ "$(uname)" != "Darwin" ]]; then
  die "This installer is for macOS. On Windows, run 'Install Vigil.bat'."
fi

if [[ ! -d "$HERE/Vigil.app" && ! -f "$HERE/vigil_widget.py" ]]; then
  die "Can't find Vigil.app or the source next to this script."
fi

if ! command -v claude >/dev/null 2>&1 && [[ ! -d "$HOME/.claude" ]]; then
  warn "Claude Code doesn't look installed. Vigil reads its hook events and"
  warn "will do nothing without it — https://claude.com/claude-code"
fi

# ---- stop anything already running ---------------------------------------
pkill -f 'Vigil.app/Contents/MacOS/Vigil' 2>/dev/null || true
pkill -f 'vigil_widget.py' 2>/dev/null || true

# ---- copy ----------------------------------------------------------------
mkdir -p "$DEST"
if [[ -d "$HERE/Vigil.app" ]]; then
  rm -rf "$DEST/Vigil.app"
  cp -R "$HERE/Vigil.app" "$DEST/"
  [[ -f "$HERE/vigil-hook" ]] && cp "$HERE/vigil-hook" "$DEST/" || true
  chmod +x "$DEST/Vigil.app/Contents/MacOS/Vigil" 2>/dev/null || true
  chmod +x "$DEST/vigil-hook" 2>/dev/null || true
  APP="$DEST/Vigil.app/Contents/MacOS/Vigil"
  ok "Copied Vigil.app to $DEST"
else
  cp "$HERE"/*.py "$DEST/"
  APP="$(command -v python3) $DEST/vigil_widget.py"
  ok "Copied the Python source to $DEST"
fi

# Gatekeeper quarantines anything downloaded from a browser. The build isn't
# notarised yet, so clear the flag here rather than making the user do the
# right-click-Open dance.
xattr -dr com.apple.quarantine "$DEST" 2>/dev/null || true
ok "Cleared the download quarantine flag"

# ---- register the hooks --------------------------------------------------
say "Connecting it to Claude Code"
if [[ -d "$HERE/Vigil.app" ]]; then
  "$DEST/Vigil.app/Contents/MacOS/Vigil" --install || die "Hook registration failed"
else
  python3 "$DEST/vigil_setup.py" --install || die "Hook registration failed"
fi
ok "Hooks registered in ~/.claude/settings.json (a backup was made first)"

# ---- start ---------------------------------------------------------------
say "Starting Vigil"
if [[ -d "$DEST/Vigil.app" ]]; then
  open -a "$DEST/Vigil.app"
else
  nohup python3 "$DEST/vigil_widget.py" >/dev/null 2>&1 &
fi
ok "Running"

cat <<'EOF'

────────────────────────────────────────────────────────────────────
  Two things left, and Vigil is half-blind without the first one:

  1. GRANT ACCESSIBILITY PERMISSION
     System Settings → Privacy & Security → Accessibility → turn on Vigil.

     Without it Vigil still works, but it cannot tell when you are already
     looking at the terminal that needs you, and clicking a notification
     will not bring that window forward.

  2. RESTART CLAUDE CODE
     Hooks load when a session starts. Close any open Claude Code windows
     and open a fresh one, or nothing will be reported.

  Then look at the bottom-right of your screen, about an inch above the
  Dock. You should see a "Vigil is watching" pill, then a small dot.

  To uninstall:  ~/.vigil/app/Vigil.app/Contents/MacOS/Vigil --uninstall
────────────────────────────────────────────────────────────────────

EOF
