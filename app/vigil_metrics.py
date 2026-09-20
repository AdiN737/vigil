"""What Vigil is actually doing for you, measured rather than claimed.

Vigil's entire promise is that an agent spends less time sitting idle waiting
for a human. That is a number, so we measure it instead of asserting it:

    waited      an agent sat blocked for N seconds before it got an answer
    answered    an approval was answered through Vigil (and how fast)
    fellthrough nobody answered in time, so the terminal prompted as usual
    notified    how long after the agent asked the pill actually appeared
    quiet       a ping that was deliberately suppressed (already looking,
                muted, rate-limited) - the interruptions Vigil avoided

Everything is appended to ~/.vigil/metrics.jsonl on this computer and stays
there. Nothing here is uploaded, and nothing records what a command did - only
that something happened, how long it took, and which project it belonged to.

The file is capped and trimmed from the front, so it can never grow without
bound. Writing is one append with no scanning, because the hook writes to it
on the agent's critical path.
"""
import json
import os
import time

MAX_BYTES = 512 * 1024      # ~4000 events; older ones are dropped
KEEP_DAYS = 90


def _path():
    d = os.environ.get("VIGIL_DATA_DIR") or os.path.join(os.path.expanduser("~"), ".vigil")
    try:
        os.makedirs(d, exist_ok=True)
    except Exception:
        pass
    return os.path.join(d, "metrics.jsonl")


def record(event, **fields):
    """Append one event. Never raises, never blocks on anything but the write."""
    try:
        rec = {"e": event, "t": round(time.time(), 3)}
        # Nothing about the work itself belongs in here. Strings are clipped
        # at the source too, but enforcing it here means a future caller
        # cannot accidentally write a command line into the metrics file.
        for k, v in fields.items():
            rec[k] = v[:40] if isinstance(v, str) else v
        p = _path()
        with open(p, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")
        if os.path.getsize(p) > MAX_BYTES:
            _trim(p)
    except Exception:
        pass


def _trim(p):
    """Drop the oldest half. Cheap, and only ever runs once the cap is hit."""
    try:
        with open(p, encoding="utf-8") as f:
            lines = f.readlines()
        keep = lines[len(lines) // 2:]
        tmp = p + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.writelines(keep)
        os.replace(tmp, p)
    except Exception:
        pass


# ─────────────────────────────────────────────────────────── reading
def events(days=7):
    """Every recorded event from the last `days`, oldest first."""
    cutoff = time.time() - days * 86400
    out = []
    try:
        with open(_path(), encoding="utf-8") as f:
            for line in f:
                try:
                    r = json.loads(line)
                except Exception:
                    continue
                if isinstance(r, dict) and r.get("t", 0) >= cutoff:
                    out.append(r)
    except FileNotFoundError:
        pass
    except Exception:
        return []
    return out


def _pct(values, p):
    if not values:
        return None
    s = sorted(values)
    return s[min(len(s) - 1, int(round((p / 100.0) * (len(s) - 1))))]


def summary(days=7, evs=None):
    """The numbers behind the claims. All times in seconds unless named _ms."""
    evs = events(days) if evs is None else evs
    waited = [e.get("secs", 0) for e in evs if e["e"] == "waited"]
    answered = [e.get("secs", 0) for e in evs if e["e"] == "answered"]
    fell = [e for e in evs if e["e"] == "fellthrough"]
    notified = [e.get("ms", 0) for e in evs if e["e"] == "notified"]
    quiet = [e for e in evs if e["e"] == "quiet"]
    away = [e for e in evs if e["e"] == "answered" and e.get("away")]

    asked = len(answered) + len(fell)
    reasons = {}
    for q in quiet:
        reasons[q.get("why", "other")] = reasons.get(q.get("why", "other"), 0) + 1

    # Time the agent did NOT spend waiting: every approval answered through
    # Vigil would otherwise have sat until the person next looked at that
    # terminal. We do not know that counterfactual, so we report what we
    # measured - how long answers took - and never invent a saving.
    return {
        "days": days,
        "idle_secs": sum(waited),          # agent time spent blocked on a human
        "blocks": len(waited),
        "asked": asked,                    # approvals Vigil was able to offer
        "answered": len(answered),
        "answered_away": len(away),        # answered without going to the terminal
        "fellthrough": len(fell),
        "coverage": (len(answered) / asked) if asked else None,
        "answer_p50": _pct(answered, 50),
        "answer_p95": _pct(answered, 95),
        "notify_p50_ms": _pct(notified, 50),
        "notify_p95_ms": _pct(notified, 95),
        "quiet": len(quiet),
        "quiet_why": reasons,
        # Only events that belong to a real agent session; a suppressed ping
        # is counted under "quiet", not as a session of its own.
        "sessions": len({e["sid"] for e in evs
                         if e.get("sid") and e["e"] in
                         ("waited", "answered", "fellthrough")}),
    }


def human_secs(s):
    if s is None:
        return "—"
    s = int(s)
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m {s % 60:02d}s"
    return f"{s // 3600}h {(s % 3600) // 60:02d}m"


def report(days=7):
    """A plain-text version of the same numbers, for `Vigil.exe --stats`."""
    s = summary(days)
    pct = "—" if s["coverage"] is None else f"{round(s['coverage'] * 100)}%"
    lines = [
        f"Vigil — last {days} days (measured on this computer)",
        "",
        f"  Agent idle time          {human_secs(s['idle_secs'])} across {s['blocks']} blocks",
        f"  Approvals offered        {s['asked']}",
        f"  Answered through Vigil   {s['answered']}  ({pct} of them)",
        f"  …without going to the terminal   {s['answered_away']}",
        f"  Fell back to the terminal {s['fellthrough']}",
        f"  Answer time              p50 {human_secs(s['answer_p50'])}"
        f"   p95 {human_secs(s['answer_p95'])}",
        f"  Notification delay       p50 {s['notify_p50_ms'] or '—'} ms"
        f"   p95 {s['notify_p95_ms'] or '—'} ms",
        f"  Interruptions avoided    {s['quiet']}"
        + (f"  ({', '.join(f'{k}: {v}' for k, v in sorted(s['quiet_why'].items()))})"
           if s["quiet_why"] else ""),
        f"  Sessions seen            {s['sessions']}",
        "",
        "Nothing here leaves this computer.",
    ]
    return "\n".join(lines)
