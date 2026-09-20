"""
Vigil desktop widget - multi-session.

A dot in the corner of your screen. When one or more AI agents need you, it
unfurls into a stack of pills - one per session - and folds back to a dot
after a few seconds. Click a pill to jump to that session's window.

    pip install PySide6-Essentials pywin32
    python vigil_widget.py            # normal
    python vigil_widget.py --demo     # fake sessions, in their own folder

Reads sessions/*.json written by Code/poc/notify.py.
"""
import json, os, sys, time, glob, ctypes

# Windowed executables have no stderr. Keep startup failures diagnosable.
if getattr(sys, "frozen", False):
    try:
        _logdir = os.path.join(os.path.expanduser("~"), ".vigil")
        os.makedirs(_logdir, exist_ok=True)
        _error_log = open(os.path.join(_logdir, "startup.log"), "a", buffering=1, encoding="utf-8")
        sys.stderr = _error_log
        sys.stdout = _error_log
    except OSError:
        pass

from PySide6.QtCore import (Qt, QTimer, QPoint, QRect, QPropertyAnimation,
                            QEasingCurve, QSharedMemory, QObject, Signal)
from PySide6.QtGui import (QColor, QPainter, QPainterPath, QPen, QFont, QAction,
                           QGuiApplication, QIcon, QPixmap)
from PySide6.QtWidgets import QApplication, QWidget, QMenu, QSystemTrayIcon

# ---------------------------------------------------------------- config
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
PREFS = os.path.join(DATA, "widget.json")

POLL_MS = 300
DOT_W = DOT_H = 26
PILL_W, PILL_H = 292, 72
PILL_APPROVE_H = 104          # taller when it carries Approve / Deny
BTN_W, BTN_H = 96, 26         # the buttons themselves
GAP = 8                       # between stacked pills
MAX_PILLS = 4                 # beyond this, show "+N more"
MARGIN_X, MARGIN_Y = 24, 96
PING_SECS = 5.0               # base time the stack stays open
PING_PER_EXTRA = 1.5          # +this per extra pill, so 3 pills get read
PING_COOLDOWN = 45.0          # minimum gap between pings, whatever happens
BURST_WINDOW = 900            # 15 min
BURST_FREE = 1                # pings per window before we start backing off
ALWAYS_PING = {7}             # destructive actions ignore the rate limit
COOLDOWN_MAX = 900.0          # 15 min - the hard ceiling on backing off
BATCH_MS = 1200               # blocks arriving together become ONE ping
GREET_SECS = 4.0
STALE_SECS = 4 * 3600

TIERS = {
    1: dict(name="idle",        color="#6E7887", pulse=0.0),
    2: dict(name="working",     color="#4C8DFF", pulse=0.5),
    3: dict(name="done",        color="#3DD68C", pulse=0.0),
    4: dict(name="question",    color="#FFB020", pulse=1.4),
    5: dict(name="blocked",     color="#FF8C42", pulse=2.0),
    6: dict(name="failed",      color="#FF5C5C", pulse=0.0),
    7: dict(name="destructive", color="#FF3B3B", pulse=5.0),
}

# The stack only ever opens when YOU have to do something.
NEEDS_YOU = {4, 5, 6, 7}


_CACHE = {}          # path -> (mtime, parsed record)


def read_sessions():
    """Every live session, most urgent first.

    Only re-parses a file whose mtime changed. Polling 3x/second and JSON-
    parsing every session each time cost 64ms at 25 sessions; this makes the
    steady state nearly free.
    """
    out, now = [], time.time()
    try:
        names = os.listdir(SESSIONS)
    except Exception:
        return out

    seen = set()
    for name in names:
        if not name.endswith(".json"):
            continue
        f = os.path.join(SESSIONS, name)
        seen.add(f)
        try:
            m = os.path.getmtime(f)
        except Exception:
            continue
        hit = _CACHE.get(f)
        if hit and hit[0] == m:
            r = hit[1]
        else:
            try:
                with open(f, encoding="utf-8") as fh:
                    r = json.load(fh)
                if not isinstance(r, dict):
                    continue
                r["tier"] = int(r.get("tier", 1))
                if not 1 <= r["tier"] <= 7:
                    r["tier"] = 1
                r["project"] = str(r.get("project", ""))[:60]
                r["detail"] = str(r.get("detail", ""))[:200]
                r["provider"] = str(r.get("provider", "claude"))[:16].lower()
                _CACHE[f] = (m, r)
            except Exception:
                _CACHE.pop(f, None)
                continue
        if now - r.get("updated", 0) > STALE_SECS:
            continue
        out.append(r)

    for gone in set(_CACHE) - seen:          # forget deleted sessions
        _CACHE.pop(gone, None)

    # most urgent first; among equals, whoever has been waiting longest
    out.sort(key=lambda r: (-r["tier"], r.get("since", now)))
    return out


def waiting(sessions):
    return [s for s in sessions if s["tier"] in NEEDS_YOU]


def prioritize(sessions, pending):
    """Order agents that want you, most time-critical first.

    With one agent this changes nothing. With several - the case that gets
    common fast once someone runs two or three projects - a pending approval
    beats everything else, because it has a deadline: answer it and that agent
    resumes now, miss it and the terminal prompts instead. Among approvals the
    one closest to expiring goes first; after that, the riskiest action, then
    whoever has been stuck longest.
    """
    now = time.time()

    def key(s):
        req = pending.get(s.get("session_id"))
        if req:
            return (0, req.get("expires", now), 0, 0)
        return (1, 0, -s.get("tier", 1), s.get("since", now))

    return sorted(sessions, key=key)


def ago(t):
    s = max(0, int(time.time() - t))
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m"
    return f"{s // 3600}h{(s % 3600) // 60:02d}"


# ----------------------------------------------- platform-specific bits
# Window focus, foreground title, the single-instance lock and autostart
# all differ per OS. They live in vigil_platform so this file does not have
# to know - and so macOS gets a real implementation instead of an early
# `return False`.
from vigil_platform import (                                     # noqa: E402
    focus_window_for, foreground_title,
    single_instance as _single_instance,
)


def already_looking(sessions):
    """True if the foreground window belongs to a session that wants attention.

    If you are staring at the terminal that just asked you something, a pill
    telling you about it is pure noise. This is the single most effective
    anti-spam rule we have.
    """
    fg = foreground_title()
    if not fg:
        return False
    for s in sessions:
        proj = (s.get("project") or "").lower()
        if proj and len(proj) > 2 and proj in fg:
            return True
    return False


# ---------------------------------------------------------------- widget
class Stack(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool |
            Qt.NoDropShadowWindowHint | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)

        self.sessions = read_sessions()
        self.pending = {}           # session_id -> pending approval request
        self.rows = []              # [(y, height, session, request)] for hit-testing
        self.shown = []             # sessions currently drawn as pills
        self.expanded = False
        self.manual = False         # opened by a click, so the poller leaves it
        self.phase = 0.0
        self.collapse_at = 0.0
        self.pinged_ids = set()     # sessions we have already pinged for
        self._quieted = set()       # (reason, session) already counted as quiet
        self.last_ping = 0.0        # for the global cooldown
        self.pending_since = 0.0    # start of the current batching window
        self.ping_log = []          # recent ping times, for burst back-off
        self.muted = False
        self.ping_secs = PING_SECS
        try:
            import vigil_setup as VS
            _p = VS.load_prefs()
            self.muted = bool(_p.get('muted', False))
            self.ping_secs = float(_p.get('ping_secs', PING_SECS))
        except Exception:
            pass
        self.greet_until = time.time() + GREET_SECS
        self.drag = None
        self._moved = False
        self._hit_y = 0
        self.on_right = True

        self.anim = QPropertyAnimation(self, b"geometry", self)
        self.anim.setDuration(240)
        self.anim.setEasingCurve(QEasingCurve.OutCubic)

        self.corner = self._load_corner()
        self._place(animate=False)

        t = QTimer(self); t.timeout.connect(self._poll); t.start(POLL_MS)
        f = QTimer(self); f.timeout.connect(self._frame); f.start(33)
        self._timers = (t, f)

    # ---------- geometry
    def _screen(self):
        return QGuiApplication.screenAt(self.pos()) or QGuiApplication.primaryScreen()

    def _load_corner(self):
        try:
            with open(PREFS, encoding="utf-8") as f:
                p = json.load(f)
            point = QPoint(int(p["x"]), int(p["y"]))
            bounds = QRect(point.x(), point.y(), DOT_W, DOT_H)
            if not any(screen.availableGeometry().contains(bounds)
                       for screen in QGuiApplication.screens()):
                raise ValueError("Saved position is outside the desktop")
            return point
        except Exception:
            g = QGuiApplication.primaryScreen().availableGeometry()
            return QPoint(g.right() - MARGIN_X - DOT_W, g.bottom() - MARGIN_Y)

    def _save_corner(self):
        try:
            with open(PREFS, "w", encoding="utf-8") as f:
                json.dump({"x": self.corner.x(), "y": self.corner.y()}, f)
        except Exception:
            pass

    def _rows(self):
        n = min(len(self.shown), MAX_PILLS)
        extra = 1 if len(self.shown) > MAX_PILLS else 0
        return n, extra

    def _row_h(self, s):
        """A pill with Approve / Deny needs more room."""
        return PILL_APPROVE_H if self.pending.get(s.get("session_id")) else PILL_H

    def _layout(self):
        """Build [(y, height, session, request)] and return the total height."""
        rows, y = [], 0
        n, extra = self._rows()
        for s in self.shown[:n]:
            h = self._row_h(s)
            rows.append((y, h, s, self.pending.get(s.get("session_id"))))
            y += h + GAP
        total = max(0, y - GAP) + (22 if extra else 0)
        return rows, total

    def _size(self):
        if not self.expanded:
            return DOT_W, DOT_H
        if not self.shown:                       # greeting
            return PILL_W, PILL_H
        _, total = self._layout()
        return PILL_W, total

    def _place(self, animate=True):
        """The dot never moves. The stack unfurls from it, away from the edge."""
        scr = self._screen().availableGeometry()
        self.on_right = (self.corner.x() + DOT_W // 2) > scr.center().x()
        w, h = self._size()
        x = self.corner.x() + DOT_W - w if self.on_right else self.corner.x()
        y = self.corner.y()
        if y + h > scr.bottom():                 # no room below - grow upward
            y = self.corner.y() + DOT_H - h
        r = QRect(x, y, w, h)
        if r.left() < scr.left():     r.moveLeft(scr.left())
        if r.right() > scr.right():   r.moveRight(scr.right())
        if r.top() < scr.top():       r.moveTop(scr.top())
        if r.bottom() > scr.bottom(): r.moveBottom(scr.bottom())
        if animate:
            self.anim.stop()
            self.anim.setStartValue(self.geometry())
            self.anim.setEndValue(r)
            self.anim.start()
        else:
            self.setGeometry(r)

    # ---------- state
    def _quiet(self, why, ids):
        """Count an interruption Vigil chose not to make.

        The poller runs 3x a second, so each session counts once per reason -
        otherwise "interruptions avoided" would just measure poll frequency.
        """
        try:
            import vigil_metrics as VM
            for i in ids:
                key = (why, i)
                if key in self._quieted:
                    continue
                self._quieted.add(key)
                VM.record("quiet", why=why, sid=str(i)[:40])
        except Exception:
            pass

    def _cooldown(self):
        """Back off hard when things are busy.

        A fixed cooldown still allows ~80 pings an hour. Each recent ping
        doubles the wait, up to 15 minutes. If things are firing constantly you
        are clearly mid-flow at your desk, and the right move is to shut up and
        let the dot carry the status.
        """
        now = time.time()
        self.ping_log = [t for t in self.ping_log if now - t < BURST_WINDOW]
        over = max(0, len(self.ping_log) - BURST_FREE)
        return min(PING_COOLDOWN * (2 ** over), COOLDOWN_MAX)

    def _open(self, sessions, manual=False):
        self.shown = list(sessions)
        self.expanded = True
        self.manual = manual
        if manual:
            self.collapse_at = 0.0
        else:
            # How long after the agent asked did the pill actually appear?
            # This is the latency number the product lives or dies on.
            try:
                import vigil_metrics as VM
                newest = max((s.get("updated", 0) for s in sessions), default=0)
                if newest:
                    VM.record("notified", ms=int(max(0, time.time() - newest) * 1000),
                              pills=len(sessions))
            except Exception:
                pass
            # more pills need more reading time
            extra = max(0, min(len(self.shown), MAX_PILLS) - 1)
            self.collapse_at = time.time() + self.ping_secs + extra * PING_PER_EXTRA
            self.last_ping = time.time()
            self.ping_log.append(self.last_ping)
        self._place()

    def _close(self):
        self.expanded = False
        self.manual = False
        self.collapse_at = 0.0
        self._place()

    def _refresh_pending(self):
        """Which sessions are waiting on an approval we can answer from here."""
        try:
            import vigil_decide as VD
            self.pending = {r.get("session_id"): r for r in VD.pending()}
        except Exception:
            self.pending = {}

    def _poll(self):
        self.sessions = read_sessions()
        self._refresh_pending()
        need = prioritize(waiting(self.sessions), self.pending)
        now = time.time()

        if now < self.greet_until:
            if not self.expanded:
                self.shown = []
                self.expanded = True
                self._place()
            self.update()
            return

        if self.manual:                       # user opened it; their call to close
            self.shown = need or self.sessions[:1]
            self.update()
            return

        ids = {s.get("session_id") for s in need}
        self.pinged_ids &= ids            # a session that resolved can ping again
        self._quieted = {q for q in self._quieted if q[1] in ids}
        fresh = ids - self.pinged_ids

        # ---- anti-spam gauntlet: a ping must survive every one of these ----
        if fresh and not self.expanded:
            if self.muted:
                self._quiet("muted", fresh)
                self.pinged_ids |= fresh                  # silence: swallow it
                fresh = set()
            elif already_looking(need):
                # You are staring at the window that wants you. Telling you
                # about it is noise, so treat it as already delivered.
                self._quiet("looking", fresh)
                self.pinged_ids |= fresh
                fresh = set()
            elif (now - self.last_ping < self._cooldown()
                  and not any(s["tier"] in ALWAYS_PING for s in need)):
                self._quiet("rate_limited", fresh)
                # Rate-limited. The one exception is a destructive action -
                # something about to force-push or rm -rf always gets through,
                # because being quiet there is worse than being annoying.
                fresh = set()
            elif not self.pending_since:
                self.pending_since = now
                fresh = set()          # open a batch window
            elif (now - self.pending_since) * 1000 < BATCH_MS:
                fresh = set()          # still collecting simultaneous blocks
            else:
                self.pending_since = 0.0       # batch closed - one ping for all

        if fresh:
            self.pinged_ids |= fresh
            self._open(need)
        elif self.expanded and need:
            self.shown = need                 # keep contents live while open
            # NB: do not name this "waiting" - it would shadow the module-level
            # waiting() function for the whole method and break _poll entirely.
            still_open = any(s.get("session_id") in self.pending for s in self.shown)
            if self.collapse_at and now > self.collapse_at and not still_open:
                self._close()      # never hide a prompt that is still waiting
        elif self.expanded and not need:
            self._close()

        self.update()

    def _frame(self):
        self.phase += 0.033
        self.update()

    # ---------- paint
    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        if self.expanded:
            self._paint_stack(p)
        else:
            self._paint_dot(p)
        p.end()

    def _dot_tier(self):
        return max((s["tier"] for s in self.sessions), default=1)

    def _paint_dot(self, p):
        import math
        tier = self._dot_tier()
        t = TIERS[tier]
        col = QColor(t["color"])
        r = self.rect()
        cx, cy = r.center().x() + 1, r.center().y() + 1
        base = 5.2 if tier == 1 else 5.8
        if t["pulse"]:
            base += 0.9 * abs(math.sin(self.phase * t["pulse"]))
        for k, a in ((3.2, 26), (2.1, 46)):
            g = QColor(col); g.setAlpha(a if tier != 1 else 24)
            p.setBrush(g); p.setPen(Qt.NoPen)
            p.drawEllipse(QPoint(cx, cy), int(base * k), int(base * k))
        c = QColor(col); c.setAlpha(195 if tier == 1 else 255)
        p.setBrush(c); p.setPen(Qt.NoPen)
        p.drawEllipse(QPoint(cx, cy), int(base), int(base))

        n = len(waiting(self.sessions))
        if n > 1:                              # how many sessions are waiting
            p.setBrush(QColor(col)); p.setPen(Qt.NoPen)
            p.drawEllipse(QPoint(cx + 8, cy - 8), 7, 7)
            p.setFont(QFont("Segoe UI", 7, QFont.Bold))
            p.setPen(QColor("#0E1116"))
            p.drawText(QRect(cx + 1, cy - 15, 14, 14), Qt.AlignCenter, str(n))

    def _paint_stack(self, p):
        if time.time() < self.greet_until:
            self._paint_pill(p, 0, None, "Vigil is watching",
                             "nothing needs you right now", "",
                             TIERS[1]["color"], 0.0)
            return
        self.rows, _ = self._layout()
        for y, h, s, req in self.rows:
            t = TIERS[s["tier"]]
            self._paint_pill(p, y, s,
                             s.get("project") or "session",
                             s.get("detail") or t["name"],
                             ago(s.get("since", time.time())),
                             t["color"], t["pulse"], h, req)
        n, extra = self._rows()
        if extra:
            p.setFont(QFont("Segoe UI", 8))
            p.setPen(QColor("#6E7887"))
            p.drawText(QRect(0, n * (PILL_H + GAP), PILL_W, 20), Qt.AlignCenter,
                       f"+{len(self.shown) - n} more waiting")

    def _paint_pill(self, p, y, s, title, detail, timer, colhex, pulse,
                    h=PILL_H, req=None):
        import math
        col = QColor(colhex)
        r = QRect(0, y, PILL_W - 1, h - 1)
        path = QPainterPath(); path.addRoundedRect(r, 14, 14)
        p.setPen(Qt.NoPen); p.setBrush(QColor(16, 20, 26, 244))
        p.drawPath(path)

        edge = QColor(col)
        edge.setAlpha(int(150 + 105 * abs(math.sin(self.phase * pulse)))
                      if pulse else 210)
        p.setBrush(Qt.NoBrush); p.setPen(QPen(edge, 1.6))
        p.drawPath(path)

        right = self.on_right
        dot_x = PILL_W - 20 if right else 20
        align = Qt.AlignRight if right else Qt.AlignLeft
        tx = 16 if right else 34
        tw = PILL_W - 50

        p.setPen(Qt.NoPen); p.setBrush(QColor(col))
        p.drawEllipse(QPoint(dot_x, y + 26), 5, 5)

        p.setFont(QFont("Segoe UI", 10, QFont.DemiBold))
        p.setPen(QColor("#EEF1F5"))
        p.drawText(QRect(tx, y + 13, tw - 44, 22),
                   Qt.AlignVCenter | align, title[:26])

        if timer:
            p.setFont(QFont("Consolas", 9))
            p.setPen(QColor(col))
            p.drawText(QRect(tx if right else PILL_W - 74, y + 13, 58, 22),
                       Qt.AlignVCenter | (Qt.AlignLeft if right else Qt.AlignRight),
                       timer)

        p.setFont(QFont("Segoe UI", 8.5))
        p.setPen(QColor("#98A1B0"))
        p.drawText(QRect(tx, y + 34, tw, 19), Qt.AlignVCenter | align, detail[:44])

        if req is None:
            p.setFont(QFont("Segoe UI", 7.5))
            p.setPen(QColor("#5D6675"))
            source = (s or {}).get("provider", "").upper()
            hint = "right-click for menu" if s is None else f"{source} · click to jump"
            p.drawText(QRect(tx, y + 50, tw, 15), Qt.AlignVCenter | align, hint)
            return

        # ---- Approve / Deny ----
        source = (s or {}).get("provider", "").upper()
        if source:
            p.setFont(QFont("Consolas", 7, QFont.DemiBold))
            p.setPen(QColor("#6E7887"))
            sr = (QRect(14, y + h - 35, 48, 22) if self.on_right else
                  QRect(PILL_W - 62, y + h - 35, 48, 22))
            p.drawText(sr, Qt.AlignVCenter |
                       (Qt.AlignLeft if self.on_right else Qt.AlignRight), source)
        danger = s.get("tier") == 7
        ax, dx = self._btn_rects(y, h)
        ok_col = QColor("#3DD68C") if not danger else QColor("#FF7A3D")
        self._btn(p, ax, "Approve" if not danger else "Approve anyway", ok_col, danger)
        self._btn(p, dx, "Deny", QColor("#8A93A3"), False)

    def _btn_rects(self, y, h):
        """Approve and Deny rects for a row starting at y. Mirrored with the pill."""
        by = y + h - BTN_H - 12
        if self.on_right:
            dx = QRect(PILL_W - 16 - BTN_W, by, BTN_W, BTN_H)
            ax = QRect(PILL_W - 16 - BTN_W * 2 - 10, by, BTN_W, BTN_H)
        else:
            ax = QRect(16, by, BTN_W, BTN_H)
            dx = QRect(16 + BTN_W + 10, by, BTN_W, BTN_H)
        return ax, dx

    def _btn(self, p, rect, label, col, filled):
        path = QPainterPath(); path.addRoundedRect(rect, 7, 7)
        if filled:
            p.setPen(Qt.NoPen); p.setBrush(col); p.drawPath(path)
            p.setPen(QColor("#12161d"))
        else:
            c = QColor(col); c.setAlpha(38)
            p.setPen(QPen(col, 1.3)); p.setBrush(c); p.drawPath(path)
            p.setPen(col)
        p.setFont(QFont("Segoe UI", 9, QFont.DemiBold))
        p.drawText(rect, Qt.AlignCenter, label)

    # ---------- interaction
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.drag = e.globalPosition().toPoint()
            self._moved = False
            self._hit_y = int(e.position().y())
            self._hit_x = int(e.position().x())
        else:
            self.drag = None

    def mouseMoveEvent(self, e):
        if self.drag is None:
            return
        d = e.globalPosition().toPoint() - self.drag
        if abs(d.x()) + abs(d.y()) > 4:
            self._moved = True
            self.corner += d
            self.drag = e.globalPosition().toPoint()
            self._place(animate=False)

    def mouseReleaseEvent(self, e):
        if self.drag is None:
            return
        if self._moved:
            self._save_corner()
            self.drag = None
            return
        if self.expanded:
            # A button click answers the prompt. Anything else jumps to the window.
            for y, h, sess, req in self.rows:
                if not (y <= self._hit_y < y + h):
                    continue
                if req:
                    ax, dx = self._btn_rects(y, h)
                    pt = QPoint(self._hit_x, self._hit_y)
                    if ax.contains(pt) or dx.contains(pt):
                        self._answer(req, "allow" if ax.contains(pt) else "deny")
                        return
                focus_window_for(sess.get("project", ""))
                break
            self._close()
        else:
            need = waiting(self.sessions)
            self._open(need or self.sessions[:1], manual=True)
        self.drag = None

    def set_muted(self, on):
        self.muted = bool(on); self._save_prefs()

    def set_ping_secs(self, v):
        self.ping_secs = float(v); self._save_prefs()

    def _save_prefs(self):
        try:
            import vigil_setup as VS
            p = VS.load_prefs()
            p["muted"] = self.muted
            p["ping_secs"] = self.ping_secs
            VS.save_prefs(p)
        except Exception:
            pass

    def _answer(self, req, decision):
        """Answer a pending approval, then drop that row and re-fit."""
        try:
            import vigil_decide as VD
            VD.decide(req["id"], decision, "widget")
        except Exception:
            pass
        self.pending.pop(req.get("session_id"), None)
        self._refresh_pending()
        if not self.pending:
            self._close()
        else:
            self._place()
        self.update()
        self.drag = None

    def contextMenuEvent(self, e):
        build_menu(QApplication.instance(), self, self).exec(e.globalPos())

    def _reset(self):
        g = QGuiApplication.primaryScreen().availableGeometry()
        self.corner = QPoint(g.right() - MARGIN_X - DOT_W, g.bottom() - MARGIN_Y)
        self._save_corner()
        self._place(animate=False)


def _msg(title, text):
    from PySide6.QtWidgets import QMessageBox
    b = QMessageBox(); b.setWindowTitle(title); b.setText(text)
    b.setIcon(QMessageBox.Information); b.exec()


# ---------------------------------------------------------------- stats
_STATS_CSS = """
#card { background: #12161D; }
QLabel { color: #E7ECF3; font-family: 'Segoe UI'; }
#eyebrow { color: #8D97A6; font-size: 11px; letter-spacing: 2px; }
#hero { color: #FF8C42; font-size: 44px; font-weight: 600; }
#herolabel { color: #B9C2CF; font-size: 13px; }
#k { color: #8D97A6; font-size: 13px; }
#v { color: #E7ECF3; font-size: 13px; font-weight: 600; }
#foot { color: #6E7887; font-size: 11px; }
QPushButton { background: #1B212B; color: #B9C2CF; border: 0; border-radius: 6px;
              padding: 5px 12px; font-size: 12px; }
QPushButton:checked { background: #FF8C42; color: #0E1116; font-weight: 600; }
"""


class Stats(QWidget):
    """The honest version of "Vigil saves you time": measured, not claimed.

    Deliberately a separate window, opened from the menu. It is never allowed
    to interrupt - the pill is reserved for an agent that needs a human.
    """

    def __init__(self, days=7):
        super().__init__()
        from PySide6.QtWidgets import (QVBoxLayout, QHBoxLayout, QLabel,
                                       QPushButton, QGridLayout, QFrame)
        self.setWindowTitle("Vigil — what it did")
        self.setStyleSheet(_STATS_CSS)
        self.resize(430, 420)

        card = QFrame(self); card.setObjectName("card")
        outer = QVBoxLayout(self); outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(card)
        box = QVBoxLayout(card); box.setContentsMargins(26, 24, 26, 20); box.setSpacing(4)

        eyebrow = QLabel("MEASURED ON THIS COMPUTER"); eyebrow.setObjectName("eyebrow")
        box.addWidget(eyebrow)

        self.hero = QLabel("—"); self.hero.setObjectName("hero")
        box.addWidget(self.hero)
        self.herolabel = QLabel(""); self.herolabel.setObjectName("herolabel")
        self.herolabel.setWordWrap(True)
        box.addWidget(self.herolabel)
        box.addSpacing(18)

        self.grid = QGridLayout(); self.grid.setHorizontalSpacing(16)
        self.grid.setVerticalSpacing(9); self.grid.setColumnStretch(0, 1)
        box.addLayout(self.grid)
        box.addStretch(1)

        row = QHBoxLayout(); row.setSpacing(8)
        self.buttons = {}
        for label, d in (("7 days", 7), ("30 days", 30), ("All time", 3650)):
            b = QPushButton(label); b.setCheckable(True)
            b.clicked.connect(lambda _, v=d: self.show_days(v))
            row.addWidget(b); self.buttons[d] = b
        row.addStretch(1)
        box.addLayout(row)

        foot = QLabel("Nothing on this screen has ever left your computer.")
        foot.setObjectName("foot")
        box.addWidget(foot)

        self.show_days(days)

    def show_days(self, days):
        from PySide6.QtWidgets import QLabel
        import vigil_metrics as VM
        for d, b in self.buttons.items():
            b.setChecked(d == days)

        s = VM.summary(days)
        self.hero.setText(VM.human_secs(s["idle_secs"]) if s["blocks"] else "—")
        self.herolabel.setText(
            f"your agents spent waiting on you, across {s['blocks']} "
            f"{'pause' if s['blocks'] == 1 else 'pauses'}. Vigil's job is to make "
            "this number smaller."
            if s["blocks"] else
            "No agent has waited on you yet in this window. Vigil records what "
            "happens as you work; check back after a session or two.")

        pct = "—" if s["coverage"] is None else f"{round(s['coverage'] * 100)}%"
        rows = [
            ("Approvals answered here", f"{s['answered']} of {s['asked']}  ({pct})"),
            ("…without opening the terminal", str(s["answered_away"])),
            ("How fast you answered", f"{VM.human_secs(s['answer_p50'])} typical"
                                      f" · {VM.human_secs(s['answer_p95'])} slowest"),
            ("Pill appeared after", f"{s['notify_p50_ms'] or '—'} ms"),
            ("Interruptions avoided", str(s["quiet"])),
            ("Sessions seen", str(s["sessions"])),
        ]
        while self.grid.count():
            self.grid.takeAt(0).widget().deleteLater()
        for i, (k, v) in enumerate(rows):
            kl = QLabel(k); kl.setObjectName("k")
            vl = QLabel(v); vl.setObjectName("v")
            self.grid.addWidget(kl, i, 0)
            self.grid.addWidget(vl, i, 1)


def show_stats(stack):
    w = getattr(stack, "_stats", None)
    if w is None:
        w = Stats(); stack._stats = w          # keep a reference or Qt frees it
    w.show_days(7)
    w.show(); w.raise_(); w.activateWindow()


class Updates(QObject):
    """Runs update checks and downloads off the UI thread.

    Deliberately NOT the pill. The pill opens only when a human must act on an
    agent; an update can always wait. Updates and announcements surface in the
    tray menu, plus one tray notification per version or message.
    """
    checked = Signal(object)     # manifest dict, or None
    staged = Signal(str)         # version now ready to install
    failed = Signal(str)         # human-readable reason

    def __init__(self, parent=None):
        super().__init__(parent)
        self.available = None    # manifest of a newer version, if any
        self.ready = None        # version verified and waiting in app.next
        self.busy = False
        self.message = None      # live announcement text, if any
        self._told = set()       # versions/messages already notified

    def check(self, force=False):
        import threading
        import vigil_update as VU

        def run():
            try:
                self.checked.emit(VU.check(force=force))
            except Exception:
                self.checked.emit(None)
        threading.Thread(target=run, daemon=True).start()

    def download(self):
        import threading
        import vigil_update as VU
        if self.busy or not self.available:
            return
        self.busy = True
        manifest = self.available

        def run():
            try:
                self.staged.emit(VU.stage(manifest))
            except Exception as e:
                self.failed.emit(str(e) or "the update could not be downloaded")
        threading.Thread(target=run, daemon=True).start()


def build_menu(app, stack, parent=None):
    """One menu, used by both the tray icon and right-click on the widget."""
    import vigil_setup as VS
    from vigil_version import VERSION
    m = QMenu(parent)

    up = getattr(stack, "_updates", None)
    if up is not None:
        if up.message:
            note = QAction(up.message, m); note.setEnabled(False)
            m.addAction(note); m.addSeparator()
        if up.ready:
            a = QAction(f"Restart to update to v{up.ready}", m)
            a.triggered.connect(lambda: _restart_to_update(app))
            m.addAction(a); m.addSeparator()
        elif up.available and not up.busy:
            a = QAction(f"Download update v{up.available['version']}…", m)
            a.triggered.connect(up.download)
            m.addAction(a); m.addSeparator()
        elif up.busy:
            a = QAction("Downloading update…", m); a.setEnabled(False)
            m.addAction(a); m.addSeparator()

    st = QAction("What Vigil did…", m)
    st.triggered.connect(lambda: show_stats(stack))
    m.addAction(st)
    m.addSeparator()

    mute = QAction("Mute pop-ups", m); mute.setCheckable(True)
    mute.setChecked(stack.muted)
    mute.triggered.connect(lambda on: stack.set_muted(on))
    m.addAction(mute)

    auto = QAction("Start at login", m); auto.setCheckable(True)
    auto.setChecked(VS.is_autostart())
    auto.triggered.connect(lambda on: VS.set_autostart(on))
    m.addAction(auto)

    m.addSeparator()
    hold = QMenu("Pop-up stays for", m)
    for secs in (3, 5, 8, 12):
        a = QAction(f"{secs} seconds", hold); a.setCheckable(True)
        a.setChecked(abs(stack.ping_secs - secs) < 0.1)
        a.triggered.connect(lambda _, v=secs: stack.set_ping_secs(v))
        hold.addAction(a)
    m.addMenu(hold)

    r = QAction("Reset position", m); r.triggered.connect(stack._reset)
    m.addAction(r)

    m.addSeparator()
    if VS.hooks_installed():
        u = QAction("Disconnect Claude + Codex", m)
        u.triggered.connect(lambda: _msg("Vigil", VS.uninstall_hooks()[1]))
    else:
        u = QAction("Connect Claude + Codex", m)
        u.triggered.connect(lambda: _msg("Vigil", VS.install_hooks()[1]))
    m.addAction(u)

    m.addSeparator()
    if up is not None:
        c = QAction("Check for updates", m)
        c.triggered.connect(lambda: up.check(force=True))
        m.addAction(c)
    v = QAction(f"Vigil v{VERSION}", m); v.setEnabled(False)
    m.addAction(v)

    q = QAction("Quit Vigil", m); q.triggered.connect(app.quit)
    m.addSeparator(); m.addAction(q)
    return m


def _restart_to_update(app):
    import vigil_update as VU
    if VU.apply():
        app.quit()          # the swap script waits for us to exit


def wire_updates(app, stack, tray):
    """Connect the updater to the tray. Quiet by default, one notice each."""
    import vigil_remote as VR
    import vigil_update as VU

    up = Updates(stack)
    stack._updates = up
    up.ready = VU.staged_version()
    up.message = VR.load()["message"]

    def notify(key, title, text):
        if key in up._told:
            return
        up._told.add(key)
        try:
            tray.showMessage(title, text, QSystemTrayIcon.Information, 8000)
        except Exception:
            pass

    def on_checked(manifest):
        up.message = VR.load()["message"]
        if up.message:
            notify(("msg", up.message), "Vigil", up.message)
        if manifest and not up.ready:
            up.available = manifest
            notify(("ver", manifest["version"]), f"Vigil v{manifest['version']} is available",
                   "Right-click the dot or the tray icon to update. Nothing changes until you do.")

    def on_staged(version):
        up.busy = False
        up.ready = version
        up.available = None
        notify(("ready", version), f"Vigil v{version} is ready",
               "It installs the next time Vigil starts, or choose Restart to update now.")

    def on_failed(reason):
        up.busy = False
        notify(("fail", reason), "Vigil update didn’t install",
               f"{reason}. Your current version is unchanged.")

    up.checked.connect(on_checked)
    up.staged.connect(on_staged)
    up.failed.connect(on_failed)

    if VU.installed():
        QTimer.singleShot(20_000, up.check)          # not during startup
        t = QTimer(stack); t.timeout.connect(up.check); t.start(3600_000)
        stack._update_timer = t                       # keep a reference
    return up


def wire_health(stack, tray):
    """Say something if Vigil has quietly stopped being connected.

    The worst failure for this product is silence that looks like calm: an
    agent asks, nothing appears, and you only notice much later. An update, a
    settings edit, or a re-installed agent can all drop the hooks. So we check,
    and if they are gone we say so once - in the tray, never the pill.
    """
    import vigil_setup as VS
    warned = set()

    def check():
        try:
            ok = VS.hooks_installed()
        except Exception:
            return
        if ok:
            warned.discard("hooks")
            return
        if "hooks" in warned:
            return
        warned.add("hooks")
        try:
            tray.showMessage(
                "Vigil isn’t connected to your agents",
                "Nothing will appear when Claude Code or Codex needs you. "
                "Right-click the tray icon and choose Connect Claude + Codex.",
                QSystemTrayIcon.Warning, 10000)
        except Exception:
            pass

    QTimer.singleShot(8_000, check)
    t = QTimer(stack); t.timeout.connect(check); t.start(1800_000)   # every 30 min
    stack._health_timer = t


def tray_icon(app, stack):
    pm = QPixmap(32, 32); pm.fill(Qt.transparent)
    p = QPainter(pm); p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(QColor("#FF8C42")); p.setPen(Qt.NoPen); p.drawEllipse(6, 6, 20, 20)
    p.setBrush(QColor("#0E1116")); p.drawEllipse(12, 12, 8, 8); p.end()
    t = QSystemTrayIcon(QIcon(pm), app); t.setToolTip("Vigil")
    def refresh():
        t.setContextMenu(build_menu(app, stack))
    t.activated.connect(lambda *_: refresh())
    refresh(); t.show()
    stack._tray = t
    return t


# ---------------------------------------------------------------- demo
DEMO = [
    (6,  "alpha", 2, "npm run dev"),
    (10, "alpha", 5, "npm run build"),                  # one waiting
    (18, "beta",  2, "pytest -q"),
    (24, "beta",  4, "which database should I use?"),   # two waiting
    (34, "gamma", 7, "git push --force origin main"),   # three waiting
    (60, "alpha", 3, "finished"),
    (66, "beta",  3, "finished"),
    (72, "gamma", 3, "finished"),
]


def start_demo(stack):
    """Fake sessions in their OWN folder so real activity is never touched."""
    global SESSIONS
    SESSIONS = os.path.join(HERE, "demo_sessions")
    os.makedirs(SESSIONS, exist_ok=True)
    for f in glob.glob(os.path.join(SESSIONS, "*.json")):
        try:
            os.remove(f)
        except Exception:
            pass
    stack.greet_until = time.time() + 3.0
    stack.pinged_ids = set()

    def write(name, tier, detail):
        try:
            with open(os.path.join(SESSIONS, name + ".json"), "w",
                      encoding="utf-8") as f:
                json.dump({"session_id": name, "tier": tier,
                           "state": TIERS[tier]["name"],
                           "label": TIERS[tier]["name"], "project": name,
                           "detail": detail, "since": time.time() - 300,
                           "updated": time.time()}, f)
        except Exception:
            pass

    for secs, name, tier, detail in DEMO:
        QTimer.singleShot(int(secs * 1000),
                          lambda n=name, t=tier, d=detail: write(n, t, d))
    QTimer.singleShot(90000, lambda: start_demo(stack))


def claim_single_instance():
    """True if we are the only Vigil. False if one is already running.

    Windows gets a kernel named mutex, POSIX an exclusive flock - see
    vigil_platform. Before that, non-Windows had no guard at all, which is
    exactly how five dots once ended up on one screen.
    """
    return _single_instance()


def main():
    # --hook runs in the agent's critical path. Handle it before Qt is imported
    # or it would pay ~200ms of Qt startup on every event.
    if "--hook" in sys.argv:
        i = sys.argv.index("--hook")
        state = sys.argv[i + 1] if len(sys.argv) > i + 1 else "idle"
        import vigil_hook
        provider = sys.argv[i + 2] if len(sys.argv) > i + 2 else None
        return vigil_hook.run(state, provider)

    import vigil_setup
    if "--install" in sys.argv:
        print(vigil_setup.install_hooks()[1]); return 0
    if "--uninstall" in sys.argv:
        print(vigil_setup.full_uninstall()[1]); return 0

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    # Open the numbers on their own, even while Vigil is already running.
    if "--stats" in sys.argv:
        app.setQuitOnLastWindowClosed(True)
        w = Stats(); w.show()
        return app.exec()

    global _LOCK
    if not claim_single_instance():
        print("Vigil is already running. Use its tray icon to quit it.")
        return 0

    # An update verified last session installs now: hand off to the swap
    # script and exit. It relaunches the new version when it is done.
    import vigil_update as VU
    if VU.staged_version() and VU.apply():
        return 0
    VU.cleanup()

    stack = Stack()
    stack.show()
    tray = tray_icon(app, stack)      # noqa: F841  keep a reference alive
    wire_updates(app, stack, tray)
    wire_health(stack, tray)
    if "--demo" in sys.argv:
        start_demo(stack)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
