"""
Install / uninstall / settings for Vigil.

Everything a user would otherwise have to do by hand-editing JSON:
  - write the Claude Code hooks (backed up, merged, validated)
  - remove them again, cleanly
  - autostart at login
  - user preferences

Safe by construction: settings.json is always backed up before we touch it,
and we re-read and re-parse it afterwards. If validation fails we roll back.
"""
import json, os, shutil, sys, time

HOME = os.path.expanduser("~")
DATA = os.path.join(HOME, ".vigil")
PREFS = os.path.join(DATA, "settings.json")
CLAUDE_SETTINGS = os.path.join(HOME, ".claude", "settings.json")
CODEX_HOOKS = os.path.join(HOME, ".codex", "hooks.json")

# Which agent events we listen to, and the state each maps to.
HOOK_MAP = {
    "UserPromptSubmit":  "working",
    "PermissionRequest": "blocked",
    "Notification":      "question",
    "Stop":              "done",
    "SessionEnd":        "idle",
}
# NOTE: PreToolUse is deliberately absent. It fires on every tool call and adds
# ~180ms each time for information UserPromptSubmit already gave us.

# Codex exposes the same lifecycle names, plus first-class subagent events.
# Each subagent gets a separate Vigil row through its agent_id.
CODEX_HOOK_MAP = {
    "UserPromptSubmit": "working", "PermissionRequest": "blocked",
    "Stop": "done", "SessionEnd": "idle",
    "SubagentStart": "working", "SubagentStop": "done",
    "Interrupt": "idle",
}

MARK = "vigil"          # how we recognise our own hooks to remove them later

DEFAULTS = {
    "ping_secs": 5.0,
    "ping_cooldown": 45.0,
    "muted": False,
    "autostart": False,
}


# ---------------------------------------------------------------- prefs
def load_prefs():
    p = dict(DEFAULTS)
    try:
        with open(PREFS, encoding="utf-8") as f:
            p.update(json.load(f))
    except Exception:
        pass
    return p


def save_prefs(p):
    try:
        os.makedirs(DATA, exist_ok=True)
        with open(PREFS, "w", encoding="utf-8") as f:
            json.dump(p, f, indent=2)
        return True
    except Exception:
        return False


# ---------------------------------------------------------------- launcher
def self_command():
    """How to launch the WIDGET again - works frozen or from source."""
    if getattr(sys, "frozen", False):
        return [sys.executable]                       # Vigil.exe
    return [sys.executable, os.path.abspath(
        os.path.join(os.path.dirname(__file__), "vigil_widget.py"))]


def hook_command(state, provider="claude"):
    """How Claude Code should invoke the HOOK.

    Frozen builds use a separate, Qt-free hook binary. Pointing the hook at the
    Qt-linked widget cost ~3 seconds per agent event; the split one is ~200ms,
    and that gap is the whole reason two binaries exist.

    On macOS a .app bundle puts sys.executable inside Contents/MacOS, so the
    sibling hook binary is looked for there as well as next to the bundle.
    """
    exe = "vigil-hook.exe" if os.name == "nt" else "vigil-hook"
    if getattr(sys, "frozen", False):
        here = os.path.dirname(sys.executable)
        cands = [os.path.join(here, "hook", exe), os.path.join(here, exe)]
        if sys.platform == "darwin":
            # .../Vigil.app/Contents/MacOS/Vigil -> also try Resources and the
            # directory the bundle itself sits in.
            cands += [
                os.path.join(here, "..", "Resources", exe),
                os.path.join(here, "..", "..", "..", exe),
            ]
        for cand in cands:
            cand = os.path.normpath(cand)
            if os.path.exists(cand):
                return _quote([cand, state, provider])
        parts = [sys.executable, "--hook", state, provider]  # fallback
    else:
        parts = [sys.executable, os.path.abspath(os.path.join(
            os.path.dirname(__file__), "vigil_hook_main.py")), state, provider]
    return _quote(parts)


def _quote(parts):
    """Quote for the shell Claude Code will run the hook through.

    Windows uses double quotes; POSIX shells need single quotes, or a path with
    a space in it silently becomes two arguments.
    """
    out = []
    for p in parts:
        p = str(p)
        if " " not in p:
            out.append(p)
        elif os.name == "nt":
            out.append(f'"{p}"')
        else:
            out.append("'" + p.replace("'", "'\''") + "'")
    return " ".join(out)


# ---------------------------------------------------------------- hooks
def _backup(path):
    if not os.path.exists(path):
        return None
    b = f"{path}.vigil-backup-{time.strftime('%Y%m%d-%H%M%S')}"
    shutil.copy2(path, b)
    return b


def install_claude_hooks():
    """Add Vigil's hooks to Claude Code. Returns (ok, message)."""
    try:
        os.makedirs(os.path.dirname(CLAUDE_SETTINGS), exist_ok=True)
        cfg = {}
        if os.path.exists(CLAUDE_SETTINGS):
            with open(CLAUDE_SETTINGS, encoding="utf-8") as f:
                cfg = json.load(f)
        backup = _backup(CLAUDE_SETTINGS)

        hooks = cfg.setdefault("hooks", {})
        for event, state in HOOK_MAP.items():
            entry = {"hooks": [{"type": "command", "command": hook_command(state)}]}
            others = [e for e in hooks.get(event, [])
                      if MARK not in json.dumps(e).lower()]
            hooks[event] = others + [entry]

        tmp = CLAUDE_SETTINGS + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
            f.write("\n")
        with open(tmp, encoding="utf-8") as f:      # prove it parses before we swap
            json.load(f)
        os.replace(tmp, CLAUDE_SETTINGS)
        return True, f"Hooks installed. Backup: {os.path.basename(backup) if backup else 'n/a'}"
    except Exception as e:
        return False, f"Could not install hooks: {e}"


def uninstall_claude_hooks():
    """Remove only Vigil's hooks, leaving anything else alone."""
    try:
        if not os.path.exists(CLAUDE_SETTINGS):
            return True, "Nothing to remove."
        with open(CLAUDE_SETTINGS, encoding="utf-8") as f:
            cfg = json.load(f)
        _backup(CLAUDE_SETTINGS)
        hooks = cfg.get("hooks", {})
        removed = 0
        for event in list(hooks):
            keep = [e for e in hooks[event] if MARK not in json.dumps(e).lower()]
            removed += len(hooks[event]) - len(keep)
            if keep:
                hooks[event] = keep
            else:
                hooks.pop(event)
        if not hooks:
            cfg.pop("hooks", None)
        tmp = CLAUDE_SETTINGS + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2); f.write("\n")
        with open(tmp, encoding="utf-8") as f:
            json.load(f)
        os.replace(tmp, CLAUDE_SETTINGS)
        return True, f"Removed {removed} Vigil hook(s)."
    except Exception as e:
        return False, f"Could not remove hooks: {e}"


def claude_hooks_installed():
    try:
        with open(CLAUDE_SETTINGS, encoding="utf-8") as f:
            return MARK in json.dumps(json.load(f).get("hooks", {})).lower()
    except Exception:
        return False



def install_codex_hooks():
    """Add Vigil to the user-level Codex/ChatGPT lifecycle hooks."""
    try:
        os.makedirs(os.path.dirname(CODEX_HOOKS), exist_ok=True)
        cfg = {}
        if os.path.exists(CODEX_HOOKS):
            with open(CODEX_HOOKS, encoding="utf-8") as f:
                cfg = json.load(f)
        backup = _backup(CODEX_HOOKS)

        hooks = cfg.setdefault("hooks", {})
        for event, state in CODEX_HOOK_MAP.items():
            timeout = 50 if event == "PermissionRequest" else (
                3 if event in ("SessionEnd", "Interrupt") else 5)
            entry = {"hooks": [{
                "type": "command",
                "command": hook_command(state, "codex"),
                "timeout": timeout,
                "statusMessage": "Updating Vigil",
            }]}
            others = [e for e in hooks.get(event, [])
                      if MARK not in json.dumps(e).lower()]
            hooks[event] = others + [entry]

        cfg.setdefault(
            "description",
            "Vigil watches Codex sessions and surfaces actionable requests.",
        )
        tmp = CODEX_HOOKS + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
            f.write("\n")
        with open(tmp, encoding="utf-8") as f:
            json.load(f)
        os.replace(tmp, CODEX_HOOKS)
        suffix = os.path.basename(backup) if backup else "n/a"
        return True, (
            f"Codex hooks installed. Backup: {suffix}. "
            "Open /hooks in Codex once to review and trust them."
        )
    except Exception as e:
        return False, f"Could not install Codex hooks: {e}"


def uninstall_codex_hooks():
    """Remove only Vigil handlers from Codex, preserving every other hook."""
    try:
        if not os.path.exists(CODEX_HOOKS):
            return True, "No Codex hooks to remove."
        with open(CODEX_HOOKS, encoding="utf-8") as f:
            cfg = json.load(f)
        _backup(CODEX_HOOKS)
        hooks = cfg.get("hooks", {})
        removed = 0
        for event in list(hooks):
            keep = [e for e in hooks[event]
                    if MARK not in json.dumps(e).lower()]
            removed += len(hooks[event]) - len(keep)
            if keep:
                hooks[event] = keep
            else:
                hooks.pop(event)
        if not hooks:
            cfg.pop("hooks", None)
        tmp = CODEX_HOOKS + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
            f.write("\n")
        with open(tmp, encoding="utf-8") as f:
            json.load(f)
        os.replace(tmp, CODEX_HOOKS)
        return True, f"Removed {removed} Vigil Codex hook(s)."
    except Exception as e:
        return False, f"Could not remove Codex hooks: {e}"


def codex_hooks_installed():
    try:
        with open(CODEX_HOOKS, encoding="utf-8") as f:
            return MARK in json.dumps(json.load(f).get("hooks", {})).lower()
    except Exception:
        return False


def install_hooks():
    results = (install_claude_hooks(), install_codex_hooks())
    return all(ok for ok, _ in results), "\n".join(msg for _, msg in results)


def uninstall_hooks():
    results = (uninstall_claude_hooks(), uninstall_codex_hooks())
    return all(ok for ok, _ in results), "\n".join(msg for _, msg in results)


def hooks_installed():
    return claude_hooks_installed() or codex_hooks_installed()
# ---------------------------------------------------------------- autostart
# Registry Run key on Windows, a LaunchAgent plist on macOS.
from vigil_platform import (                                     # noqa: E402
    set_autostart as _set_autostart,
    is_autostart,
)


def set_autostart(on):
    return _set_autostart(on, self_command())

def full_uninstall(remove_data=True):
    msgs = []
    ok, m = uninstall_hooks(); msgs.append(m)
    set_autostart(False); msgs.append("Autostart removed.")
    if remove_data:
        try:
            shutil.rmtree(DATA, ignore_errors=True)
            msgs.append("Removed ~/.vigil")
        except Exception as e:
            msgs.append(f"Could not remove data: {e}")
    return ok, "\n".join(msgs)


if __name__ == "__main__":
    arg = sys.argv[1].lstrip("-") if len(sys.argv) > 1 else "status"
    if arg == "install":
        print(install_hooks()[1])
    elif arg == "install-codex":
        ok, message = install_codex_hooks()
        print(message)
        sys.exit(0 if ok else 1)
    elif arg == "uninstall-codex":
        ok, message = uninstall_codex_hooks()
        print(message)
        sys.exit(0 if ok else 1)
    elif arg == "uninstall":
        print(full_uninstall()[1])
    else:
        print("hooks installed :", hooks_installed())
        print("autostart       :", is_autostart())
        print("data dir        :", DATA)
        print("hook command    :", hook_command("blocked"))
