"""
Vigil hook script. Claude Code runs this on every agent event.

Writes ONE FILE PER SESSION into sessions/, so several Claude Code windows can
be tracked at once without overwriting each other.

TWO HARD RULES:
  1. Never crash or hang - that would break Claude Code. Everything is wrapped
     and we always exit 0.
  2. Stay FAST. This runs in Claude's critical path. No glob, no re, no
     directory scans on the hot path. Measured: see _bench.py.
"""
import sys, os, json, time

HERE = os.path.dirname(os.path.abspath(__file__))

def _data_dir():
    """Runtime state lives OUTSIDE the project folder.

    The repo may sit in OneDrive/Dropbox; writing session files there causes
    sync storms, transient file locks mid-write, and - worst - session files
    syncing BETWEEN machines so you see phantom sessions from another computer.
    """
    # NOT %LOCALAPPDATA%. The Microsoft Store build of Python virtualizes
    # writes there into a hidden per-package sandbox, so notify.py and the
    # widget would silently look in different folders the moment either one
    # runs under a different Python. The home directory is not virtualized.
    d = os.path.join(os.path.expanduser("~"), ".vigil")
    try:
        os.makedirs(d, exist_ok=True)
    except Exception:
        pass
    return d


DATA = _data_dir()
SESSIONS = os.path.join(DATA, "sessions")
LOG = os.path.join(DATA, "log.txt")

STALE_SECS = 4 * 3600          # forget a session that has said nothing in 4h

# Set to your board's COM port once you have hardware, e.g. "COM7". None = off.
SERIAL_PORT = None
BAUD = 115200

# tier 7: things that are hard or impossible to undo
DESTRUCTIVE = (
    "rm -rf", "rm -f", "del /f", "format ", "mkfs",
    "git push --force", "git push -f", "git reset --hard", "git clean -fd",
    "drop table", "drop database", "truncate ",
    "deploy", "publish", "terraform apply", "kubectl delete",
)

TIERS = {"idle": 1, "working": 2, "done": 3,
         "question": 4, "blocked": 5, "failed": 6}

SAFE = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-")


def read_hook_input():
    """Claude Code sends a JSON payload on stdin. It may be empty."""
    try:
        if sys.stdin.isatty():
            return {}
        raw = sys.stdin.read()
        return json.loads(raw) if raw.strip() else {}
    except Exception:
        return {}


def describe(payload):
    cwd = payload.get("cwd") or os.getcwd()
    project = os.path.basename(str(cwd).rstrip("\\/")) or "session"
    tool = payload.get("tool_name") or ""
    ti = payload.get("tool_input") or {}
    detail = ""
    if isinstance(ti, dict):
        detail = str(ti.get("command") or ti.get("file_path")
                     or ti.get("path") or ti.get("prompt") or "")
    if not detail:
        detail = tool
    return project, tool, " ".join(detail.split())[:120], cwd


def tier_for(state, blob):
    low = blob.lower()
    if state == "blocked":
        for d in DESTRUCTIVE:
            if d in low:
                return 7, "destructive"
    return TIERS.get(state, 1), state


def session_file(sid):
    """Sanitise without importing re - it costs ~15ms of startup."""
    s = "".join(c if c in SAFE else "_" for c in str(sid))[:80]
    return os.path.join(SESSIONS, (s or "unknown") + ".json")


def prune():
    """Only called on SessionEnd - a directory scan is too slow for the hot path."""
    now = time.time()
    try:
        for name in os.listdir(SESSIONS):
            if not name.endswith(".json"):
                continue
            f = os.path.join(SESSIONS, name)
            try:
                if now - os.path.getmtime(f) > STALE_SECS:
                    os.remove(f)
            except Exception:
                pass
    except Exception:
        pass


def main():
    state = (sys.argv[1] if len(sys.argv) > 1 else "idle").lower()
    payload = read_hook_input()
    project, tool, detail, cwd = describe(payload)
    tier, label = tier_for(state, tool + " " + detail)

    sid = payload.get("session_id") or payload.get("prompt_id") or project
    path = session_file(sid)

    event = payload.get("hook_event_name") or ""
    if state == "idle" and event == "SessionEnd":
        try:
            os.remove(path)
        except Exception:
            pass
        prune()                       # tidy up only when a session actually ends
        sys.exit(0)

    # keep the clock running from when this state actually began
    since = time.time()
    try:
        with open(path, encoding="utf-8") as f:
            prev = json.load(f)
        if prev.get("state") == state and prev.get("since"):
            since = prev["since"]
    except Exception:
        pass

    rec = {
        "session_id": str(sid), "state": state, "label": label, "tier": tier,
        "project": project, "cwd": cwd, "tool": tool, "detail": detail,
        "since": since, "updated": time.time(),
        "event": event,
    }

    try:
        os.makedirs(SESSIONS, exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(rec, f)
        os.replace(tmp, path)          # atomic, so the widget never sees a half-file
    except Exception:
        pass

    # Only log the events a human cares about. Logging every tool call would
    # grow without bound and cost disk on the hot path.
    if tier >= 3:
        try:
            with open(LOG, "a", encoding="utf-8") as f:
                f.write(f"{time.strftime('%H:%M:%S')}  tier{tier}  {state:9s} "
                        f"{project:20s} {str(sid)[:8]}  {detail}\n")
        except Exception:
            pass

    if SERIAL_PORT:
        try:
            import serial                       # pip install pyserial
            with serial.Serial(SERIAL_PORT, BAUD, timeout=0.3) as s:
                s.write(f"{tier}|{state}|{project}|{detail}\n".encode())
        except Exception:
            pass

    sys.exit(0)      # ALWAYS succeed


if __name__ == "__main__":
    try:
        main()
    except Exception:
        sys.exit(0)
