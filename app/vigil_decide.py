"""
The decision channel — the core of approve-from-anywhere.

ONE mechanism serves all three surfaces:

    widget click  ─┐
    watch / phone ─┼──> writes ~/.vigil/decisions/<id>.json ──> hook returns
    the device    ─┘                                            permissionDecision

The hook blocks on PermissionRequest waiting for that file. If nothing arrives
it returns nothing and Claude Code shows its normal terminal prompt — so the
worst case is exactly today's behaviour. That fallback is the whole safety story.

IMPORTANT: we only wait when the user is NOT looking at the Claude window. If
they are already at that terminal they will just answer it there, and blocking
would only delay the prompt they are staring at.
"""
import json, os, time

HOME = os.path.expanduser("~")
DATA = os.path.join(HOME, ".vigil")
DECISIONS = os.path.join(DATA, "decisions")
REQUESTS = os.path.join(DATA, "requests")

WAIT_SECS = 45.0          # how long the hook will wait for you to answer
POLL_MS = 120


def _ensure():
    for d in (DECISIONS, REQUESTS):
        try:
            os.makedirs(d, exist_ok=True)
        except Exception:
            pass


def request_path(rid):
    return os.path.join(REQUESTS, f"{rid}.json")


def decision_path(rid):
    return os.path.join(DECISIONS, f"{rid}.json")


# ---------------------------------------------------------------- hook side
def open_request(rid, session_id, project, tool, detail, tier,
                 provider="claude"):
    """Called by the hook. Publishes a pending approval for the UIs to show."""
    _ensure()
    rec = {
        "id": rid, "session_id": session_id, "project": project,
        "provider": provider, "tool": tool, "detail": detail, "tier": tier,
        "opened": time.time(), "expires": time.time() + WAIT_SECS,
    }
    try:
        tmp = request_path(rid) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(rec, f)
        os.replace(tmp, request_path(rid))
    except Exception:
        pass
    return rec


def await_decision(rid, seconds=WAIT_SECS):
    """Block until someone decides, or we run out of time.

    Returns 'allow', 'deny', or None. None means: let Claude Code prompt
    normally, exactly as it does today.
    """
    end = time.time() + seconds
    dp = decision_path(rid)
    while time.time() < end:
        try:
            if os.path.exists(dp):
                with open(dp, encoding="utf-8") as f:
                    d = json.load(f)
                v = str(d.get("decision", "")).lower()
                if v in ("allow", "deny"):
                    return v
        except Exception:
            pass
        time.sleep(POLL_MS / 1000.0)
    return None


def close_request(rid):
    for p in (request_path(rid), decision_path(rid)):
        try:
            os.remove(p)
        except Exception:
            pass


# ---------------------------------------------------------------- UI side
def pending():
    """Every approval still waiting for an answer. Used by the widget."""
    _ensure()
    out, now = [], time.time()
    try:
        names = os.listdir(REQUESTS)
    except Exception:
        return out
    for n in names:
        if not n.endswith(".json"):
            continue
        try:
            with open(os.path.join(REQUESTS, n), encoding="utf-8") as f:
                r = json.load(f)
            if r.get("expires", 0) < now:
                try:
                    os.remove(os.path.join(REQUESTS, n))
                except Exception:
                    pass
                continue
            if os.path.exists(decision_path(r.get("id", ""))):
                continue                      # already answered
            out.append(r)
        except Exception:
            continue
    out.sort(key=lambda r: r.get("opened", 0))
    return out


def decide(rid, decision, source="widget"):
    """Answer a pending approval. Called by the widget, watch bridge, or device."""
    _ensure()
    if decision not in ("allow", "deny"):
        return False
    try:
        tmp = decision_path(rid) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"id": rid, "decision": decision,
                       "source": source, "at": time.time()}, f)
        os.replace(tmp, decision_path(rid))
        return True
    except Exception:
        return False
