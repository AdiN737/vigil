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


def hook_command(state):
    """How Claude Code should invoke the HOOK.

    Frozen builds use a separate, Qt-free vigil-hook.exe. Pointing the hook at
    the Qt-linked widget cost ~3 seconds per agent event; this one is ~200ms.
    """
    if getattr(sys, "frozen", False):
        here = os.path.dirname(sys.executable)
        for cand in (os.path.join(here, "hook", "vigil-hook.exe"),
                     os.path.join(here, "vigil-hook.exe")):
            if os.path.exists(cand):
                return f'"{cand}" {state}'
        parts = [sys.executable, "--hook", state]     # fallback, slower
    else:
        parts = [sys.executable, os.path.abspath(
            os.path.join(os.path.dirname(__file__), "vigil_hook_main.py")), state]
    return " ".join(f'"{p}"' if " " in p else p for p in parts)


# ---------------------------------------------------------------- hooks
def _backup(path):
    if not os.path.exists(path):
        return None
    b = f"{path}.vigil-backup-{time.strftime('%Y%m%d-%H%M%S')}"
    shutil.copy2(path, b)
    return b


def install_hooks():
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


def uninstall_hooks():
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


def hooks_installed():
    try:
        with open(CLAUDE_SETTINGS, encoding="utf-8") as f:
            return MARK in json.dumps(json.load(f).get("hooks", {})).lower()
    except Exception:
        return False


# ---------------------------------------------------------------- autostart
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def set_autostart(on):
    if os.name != "nt":
        return False
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0,
                            winreg.KEY_SET_VALUE) as k:
            if on:
                cmd = " ".join(f'"{p}"' if " " in p else p for p in self_command())
                winreg.SetValueEx(k, "Vigil", 0, winreg.REG_SZ, cmd)
            else:
                try:
                    winreg.DeleteValue(k, "Vigil")
                except FileNotFoundError:
                    pass
        return True
    except Exception:
        return False


def is_autostart():
    if os.name != "nt":
        return False
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, "Vigil")
        return True
    except Exception:
        return False


# ---------------------------------------------------------------- uninstall
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
    arg = sys.argv[1] if len(sys.argv) > 1 else "status"
    if arg == "install":
        print(install_hooks()[1])
    elif arg == "uninstall":
        print(full_uninstall()[1])
    else:
        print("hooks installed :", hooks_installed())
        print("autostart       :", is_autostart())
        print("data dir        :", DATA)
        print("hook command    :", hook_command("blocked"))
