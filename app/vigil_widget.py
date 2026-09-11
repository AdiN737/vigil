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

from PySide6.QtCore import (Qt, QTimer, QPoint, QRect, QPropertyAnimation,
                            QEasingCurve, QSharedMemory)
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
            return QPoint(p["x"], p["y"])
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
        need = waiting(self.sessions)
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
        fresh = ids - self.pinged_ids

        # ---- anti-spam gauntlet: a ping must survive every one of these ----
        if fresh and not self.expanded:
            if self.muted:
                self.pinged_ids |= fresh                  # silence: swallow it
                fresh = set()
            elif already_looking(need):
                # You are staring at the window that wants you. Telling you
                # about it is noise, so treat it as already delivered.
                self.pinged_ids |= fresh
                fresh = set()
            elif (now - self.last_ping < self._cooldown()
                  and not any(s["tier"] in ALWAYS_PING for s in need)):
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


def build_menu(app, stack, parent=None):
    """One menu, used by both the tray icon and right-click on the widget."""
    import vigil_setup as VS
    m = QMenu(parent)

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

    q = QAction("Quit Vigil", m); q.triggered.connect(app.quit)
    m.addSeparator(); m.addAction(q)
    return m


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

    global _LOCK
    if not claim_single_instance():
        print("Vigil is already running. Use its tray icon to quit it.")
        return 0

    stack = Stack()
    stack.show()
    tray = tray_icon(app, stack)      # noqa: F841  keep a reference alive
    if "--demo" in sys.argv:
        start_demo(stack)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
