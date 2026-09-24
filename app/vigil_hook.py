"""
Vigil's provider-neutral lifecycle hook. Claude Code and Codex run the same
small binary; this module normalizes both payloads into one session record.

Writes ONE FILE PER SESSION into sessions/, so several Claude Code windows can
be tracked at once without overwriting each other.

TWO HARD RULES:
  1. Never crash or hang - that would break Claude Code. Everything is wrapped
     and we always exit 0.
  2. Stay FAST. This runs in Claude's critical path. No glob, no re, no
     directory scans on the hot path. Measured: see _bench.py.
"""
import sys, os, json, time, hashlib, uuid, ntpath

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
    d = os.environ.get("VIGIL_DATA_DIR") or os.path.join(os.path.expanduser("~"), ".vigil")
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
    """The active agent sends a JSON payload on stdin. It may be empty."""
    try:
        if sys.stdin.isatty():
            return {}
        raw = sys.stdin.read()
        return json.loads(raw) if raw.strip() else {}
    except Exception:
        return {}


def scrub(text):
    """Drop anything that looks like a credential before it is written down.

    The pill shows the command an agent wants to run, and a command can carry
    a token: `curl -H "Authorization: Bearer sk-..."`. You need to recognise
    the command, not the key, so long opaque words are replaced.

    Deliberately no `re` - importing it costs ~15ms on the hook's hot path.
    """
    out = []
    for word in text.split():
        bare = word.strip("\"'`,;()[]{}")
        if len(bare) >= 20:
            core = bare.split("=")[-1].split(":")[-1]
            if len(core) >= 20 and not any(c in core for c in "/\\"):
                has_digit = any(c.isdigit() for c in core)
                has_alpha = any(c.isalpha() for c in core)
                # A commit sha is all hex and worth reading; a key is not.
                is_sha = all(c in "0123456789abcdef" for c in core.lower())
                if has_digit and has_alpha and not is_sha:
                    out.append(word.replace(core, "[redacted]"))
                    continue
        out.append(word)
    return " ".join(out)


def describe(payload):
    """What to show on the pill: the project, the tool, and a short detail.

    The detail comes from the tool's own input - a command, a path, the
    agent's description of what it is doing. It deliberately does NOT come
    from `prompt`: what you type to your agent is yours, and Vigil never
    writes it down. See docs/SECURITY.md.
    """
    cwd = payload.get("cwd") or os.getcwd()
    project = os.path.basename(str(cwd).rstrip("\\/")) or "session"
    tool = payload.get("tool_name") or ""
    ti = payload.get("tool_input") or {}
    detail = ""
    if isinstance(ti, dict):
        detail = str(ti.get("command") or ti.get("description")
                     or ti.get("file_path") or ti.get("path") or "")
    if not detail:
        detail = tool
    return project, tool, scrub(" ".join(detail.split()))[:120], cwd


def provider_for(payload, hint=None):
    """Identify the producer without depending on unstable transcript files."""
    if hint in ("claude", "codex"):
        return hint
    explicit = str(payload.get("vigil_provider") or "").lower()
    if explicit in ("claude", "codex"):
        return explicit
    # Documented Codex hook extensions that Claude hooks do not send.
    if any(payload.get(k) is not None for k in
           ("model", "turn_id", "permission_mode", "agent_id")):
        return "codex"
    return "claude"


def project_identity(cwd):
    """Stable project key, including its full path rather than just basename."""
    raw = str(cwd)
    windows = bool(ntpath.splitdrive(raw)[0]) or "\\" in raw
    normalized = ntpath.normcase(ntpath.normpath(raw)) if windows else os.path.abspath(raw)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def identity_for(payload, provider):
    """Give Codex subagents their own rows while preserving the native id."""
    native = str(payload.get("session_id") or payload.get("prompt_id") or "")
    agent = str(payload.get("agent_id") or "")
    if provider == "codex":
        suffix = f":{agent}" if agent else ""
        return f"codex:{native or 'session'}{suffix}", native
    return native or provider, native


def approval_output(provider, verdict):
    """Return the provider's documented PermissionRequest response shape."""
    if provider == "codex":
        decision = {"behavior": verdict}
        if verdict == "deny":
            decision["message"] = "Denied from Vigil"
        return {"hookSpecificOutput": {
            "hookEventName": "PermissionRequest", "decision": decision,
        }}
    return {"hookSpecificOutput": {
        "hookEventName": "PermissionRequest",
        # PermissionRequest uses decision.behavior; permissionDecision is
        # a PreToolUse field and cannot answer this event.
        "decision": {"behavior": verdict},
    }}

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
    if str(sid).startswith("codex:"):
        s = "codex_" + hashlib.sha256(str(sid).encode()).hexdigest()
    elif not (len(s) == 36 and all(s[i] == "-" for i in (8, 13, 18, 23))
              and all(c in "0123456789abcdef-" for c in s)):
        # Lossy replacement, truncation, and Windows case folding can merge
        # native IDs. Keep canonical lowercase UUID filenames compatible.
        s = "session_" + hashlib.sha256(str(sid).encode()).hexdigest()
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


def _user_is_at(project):
    """True if the user is already looking at the window that wants them.

    A 1-2 character project name would match almost any window title and
    silently disable approvals everywhere, so short names never match.
    The widget guards this the same way.
    """
    if not project or len(project) < 3:
        return False
    try:
        from vigil_platform import foreground_title
        if project.lower() not in foreground_title():
            return False
        # A title containing "web" cannot identify which of two agents in
        # that project is focused. Never suppress a different agent's request.
        matches = 0
        for name in os.listdir(SESSIONS):
            if not name.endswith(".json"):
                continue
            try:
                with open(os.path.join(SESSIONS, name), encoding="utf-8") as f:
                    record = json.load(f)
                if (str(record.get("project", "")).lower() == project.lower()
                        and time.time() - float(record.get("updated", 0)) < STALE_SECS):
                    matches += 1
            except (OSError, ValueError, TypeError, AttributeError):
                continue
        return matches == 1
    except Exception:
        return False

def main(state=None, provider_hint=None):
    if state is None:
        state = (sys.argv[1] if len(sys.argv) > 1 else "idle").lower()
    payload = read_hook_input()
    provider = provider_for(payload, provider_hint)
    project, tool, detail, cwd = describe(payload)
    tier, label = tier_for(state, tool + " " + detail)

    sid, native_sid = identity_for(payload, provider)
    if not native_sid:
        # Without a producer session id, do not merge unrelated folders named
        # "web". Multiple id-less agents in one folder cannot be distinguished.
        agent = str(payload.get("agent_id") or "")
        sid = f"{provider}:path:{project_identity(cwd)}:{agent}"
    path = session_file(sid)

    event = payload.get("hook_event_name") or ""
    if state == "idle" and event == "SessionEnd":
        try:
            os.remove(path)
        except Exception:
            pass
        prune()                       # tidy up only when a session actually ends
        return 0

    # keep the clock running from when this state actually began
    since = time.time()
    prev = None
    try:
        with open(path, encoding="utf-8") as f:
            prev = json.load(f)
        if prev.get("state") == state and prev.get("since"):
            since = prev["since"]
    except Exception:
        pass

    # A session that was waiting on a human and is now moving again: the gap is
    # agent idle time, the number Vigil exists to shrink. Recorded locally.
    try:
        if (prev and int(prev.get("tier", 1)) >= 4 > tier
                and float(prev.get("since", 0)) > 0):
            import vigil_metrics as VM
            VM.record("waited", secs=round(time.time() - float(prev["since"]), 2),
                      tier=int(prev.get("tier", 1)), sid=str(sid)[:40],
                      by="terminal")
    except Exception:
        pass

    rec = {
        "schema": 1, "provider": provider,
        "session_id": str(sid), "native_session_id": native_sid,
        "state": state, "label": label, "tier": tier,
        "project": project, "project_id": project_identity(cwd),
        "cwd": cwd, "tool": tool, "detail": detail,
        "since": since, "updated": time.time(),
        "event": event,
    }

    try:
        os.makedirs(SESSIONS, exist_ok=True)
        tmp = path + f".{os.getpid()}.tmp"
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

    # ---------------------------------------------------------------- approve
    # On a permission request we can wait for the user to answer from the
    # widget / watch / device instead of the terminal. If nobody answers we
    # return nothing and Claude Code prompts exactly as it does today.
    if event == "PermissionRequest" and state == "blocked":
        try:
            import vigil_decide as VD
            import vigil_remote as VR
            # Live kill switch, pushed from vigilit.app and cached locally by
            # the widget. Reading it is a small local file; the hook itself
            # never touches the network. Off means the agent's own prompt
            # appears exactly as if Vigil were not installed.
            if VR.approvals_enabled() and not _user_is_at(project):
                import vigil_metrics as VM
                rid = uuid.uuid4().hex
                asked_at = time.time()
                VD.open_request(rid, str(sid), project, tool, detail, tier,
                                provider)
                try:
                    verdict = VD.await_decision(rid)
                finally:
                    VD.close_request(rid)
                took = round(time.time() - asked_at, 2)
                if verdict in ("allow", "deny"):
                    # Answered from the widget: this is both the answer time and
                    # the whole idle gap, since the agent resumes right now.
                    VM.record("answered", secs=took, verdict=verdict, tier=tier,
                              sid=str(sid)[:40], away=not _user_is_at(project))
                    VM.record("waited", secs=took, tier=tier, sid=str(sid)[:40],
                              by="vigil")
                else:
                    # Nobody answered in time. The terminal prompts as always,
                    # and the agent keeps waiting - worth knowing how often.
                    VM.record("fellthrough", secs=took, tier=tier, sid=str(sid)[:40])
                if verdict in ("allow", "deny"):
                    # Resolve the actionable record immediately; no later tool hook
                    # is needed to clear the widget after a decision.
                    rec.update(state="working" if verdict == "allow" else "idle",
                               tier=2 if verdict == "allow" else 1,
                               label="working" if verdict == "allow" else "idle",
                               since=time.time(), updated=time.time())
                    with open(tmp, "w", encoding="utf-8") as f:
                        json.dump(rec, f)
                    os.replace(tmp, path)
                    print(json.dumps(approval_output(provider, verdict)))
                    return 0
        except Exception:
            pass                                 # never block Claude over this

    if SERIAL_PORT:
        try:
            import serial                       # pip install pyserial
            with serial.Serial(SERIAL_PORT, BAUD, timeout=0.3) as s:
                s.write(f"{tier}|{state}|{project}|{detail}\n".encode())
        except Exception:
            pass

    # Codex requires valid JSON from passive Stop hooks. An empty object means
    # "observed, no control decision" and avoids a false hook-failed warning.
    if provider == "codex" and event in ("Stop", "SubagentStop"):
        print("{}")
    return 0         # ALWAYS succeed


def run(state, provider=None):
    """Entry point when the packaged exe is invoked as a hook."""
    try:
        return main(state, provider) or 0
    except Exception:
        return 0            # a broken hook must never break Claude Code


if __name__ == "__main__":
    sys.exit(run(sys.argv[1] if len(sys.argv) > 1 else "idle",
                 sys.argv[2] if len(sys.argv) > 2 else None))
