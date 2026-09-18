"""Live settings pushed from vigilit.app, as cached on this machine.

The widget fetches them (see vigil_update) and writes ~/.vigil/remote.json.
The hook only ever READS that file: it never touches the network, because it
runs on every agent event and must stay fast and offline.

Only whitelisted keys are honoured, each with a type and bounds, so nothing
the server sends can put the app in a state it was not designed for. Anything
missing or malformed falls back to the shipped default.
"""
import json
import os

_DEFAULTS = {
    # Master switch for answering permission prompts from the widget. If a
    # future agent version breaks the approval protocol, flipping this off
    # makes every copy fall back to the agent's own prompt within a day,
    # without anyone reinstalling.
    "approvals_enabled": True,
    # A short notice shown in the tray menu, or None.
    "message": None,
}


def _path():
    d = os.environ.get("VIGIL_DATA_DIR") or os.path.join(os.path.expanduser("~"), ".vigil")
    return os.path.join(d, "remote.json")


def sanitize(raw):
    """Keep only known keys with sane values."""
    out = dict(_DEFAULTS)
    if not isinstance(raw, dict):
        return out
    if isinstance(raw.get("approvals_enabled"), bool):
        out["approvals_enabled"] = raw["approvals_enabled"]
    msg = raw.get("message")
    if isinstance(msg, str) and msg.strip():
        out["message"] = msg.strip()[:200]
    elif isinstance(msg, dict) and isinstance(msg.get("text"), str) and msg["text"].strip():
        out["message"] = msg["text"].strip()[:200]
    return out


def load():
    try:
        with open(_path(), encoding="utf-8") as f:
            return sanitize(json.load(f))
    except Exception:
        return dict(_DEFAULTS)


def save(raw):
    """Atomic, so the hook never reads a half-written file."""
    clean = sanitize(raw)
    path = _path()
    tmp = path + ".tmp"
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(clean, f)
        os.replace(tmp, path)
    except Exception:
        pass
    return clean


def approvals_enabled():
    return load()["approvals_enabled"]
