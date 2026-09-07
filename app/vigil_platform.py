"""Everything Vigil does that is not portable, behind one small API.

Before this module, four Windows-only calls were scattered through the widget
and the hook, each guarded with `if os.name != "nt": return`. That ran on macOS
but silently gave up three features and the single-instance guard - which is the
bug that once put five dots on someone's screen.

Every function here answers the same way on every platform, and every one of
them fails soft: if the OS refuses, the permission is missing, or the tool is
absent, you get False or "" and Vigil carries on. None of this is worth
crashing a status widget over.

Platform notes
--------------
macOS needs **Accessibility** permission (System Settings -> Privacy &
Security -> Accessibility) before it can read window titles or raise a window.
Without it, `foreground_title()` returns the app name only and
`focus_window_for()` returns False. Vigil still works; it just loses the
"you are already looking at it" gate and click-to-jump.
"""

import os
import subprocess
import sys
import time

WINDOWS = os.name == "nt"
MACOS = sys.platform == "darwin"
LINUX = sys.platform.startswith("linux")

_LOCK = None                    # kept alive for the life of the process


# --------------------------------------------------------------- data dir
def data_dir():
    """Where session state lives. Deliberately the home directory root.

    Not %LOCALAPPDATA% (the Microsoft Store build of Python virtualises writes
    there into a hidden per-package sandbox) and not a synced folder like
    OneDrive or Dropbox, which produced phantom sessions from other machines.
    """
    d = os.path.join(os.path.expanduser("~"), ".vigil")
    os.makedirs(d, exist_ok=True)
    return d


# ------------------------------------------------------- applescript help
def _osa(script, timeout=1.5):
    """Run AppleScript, return stdout, or "" for any failure at all.

    Timeout matters: System Events can hang for seconds when Accessibility
    permission has not been granted, and this runs on the path that decides
    whether to show a pill.
    """
    try:
        r = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=timeout,
            stdin=subprocess.DEVNULL,
        )
        return (r.stdout or "").strip()
    except Exception:
        return ""


# ------------------------------------------------- what am I looking at?
_fg_cache = (0.0, "")


def foreground_title(ttl=0.8):
    """Lower-cased title of the window the user is actually looking at.

    Returns "" when unknown - callers must treat that as "no idea", never as
    "not looking".

    The cache exists for macOS: each call spawns `osascript`, which costs tens
    of milliseconds. This sits on the notify path, so a short TTL keeps a burst
    of decisions from spawning a burst of processes.
    """
    global _fg_cache
    now = time.time()
    if now - _fg_cache[0] < ttl:
        return _fg_cache[1]

    title = ""
    if WINDOWS:
        try:
            import win32gui
            title = (win32gui.GetWindowText(win32gui.GetForegroundWindow()) or "")
        except Exception:
            title = ""
    elif MACOS:
        # Ask for the app name too: without Accessibility permission the window
        # title comes back empty, and the app name alone still catches the
        # common "am I sitting in Terminal right now" case.
        title = _osa(
            'tell application "System Events"\n'
            '  set p to first application process whose frontmost is true\n'
            '  set n to name of p\n'
            '  set t to ""\n'
            '  try\n'
            '    set t to value of attribute "AXTitle" of front window of p\n'
            '  end try\n'
            '  return n & " " & t\n'
            'end tell'
        )
    elif LINUX:
        try:
            r = subprocess.run(["xdotool", "getactivewindow", "getwindowname"],
                               capture_output=True, text=True, timeout=1.0,
                               stdin=subprocess.DEVNULL)
            title = (r.stdout or "").strip()
        except Exception:
            title = ""

    title = title.lower()
    _fg_cache = (now, title)
    return title


# ------------------------------------------------------- raise a window
def focus_window_for(project):
    """Best effort: bring the window for `project` to the front.

    Returns True only if we are reasonably sure something was raised. False
    means "could not", and the caller should not pretend otherwise.
    """
    if not project:
        return False

    if WINDOWS:
        return _focus_windows(project)
    if MACOS:
        return _focus_macos(project)
    return False


def _focus_windows(project):
    try:
        import ctypes
        import win32gui
        import win32con
    except Exception:
        return False

    needles = [project.lower(), "claude"]
    found = []

    def cb(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd):
            return
        title = win32gui.GetWindowText(hwnd)
        if not title:
            return
        low = title.lower()
        for rank, needle in enumerate(needles):
            if needle in low:
                found.append((rank, hwnd))
                break

    try:
        win32gui.EnumWindows(cb, None)
    except Exception:
        return False
    if not found:
        return False
    found.sort()
    hwnd = found[0][1]
    try:
        if win32gui.IsIconic(hwnd):
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        u32 = ctypes.windll.user32
        cur = u32.GetWindowThreadProcessId(u32.GetForegroundWindow(), None)
        tgt = u32.GetWindowThreadProcessId(hwnd, None)
        u32.AttachThreadInput(cur, tgt, True)
        win32gui.SetForegroundWindow(hwnd)
        u32.AttachThreadInput(cur, tgt, False)
        return True
    except Exception:
        return False


def _focus_macos(project):
    """Walk visible windows for a title match, raise the first one.

    Needs Accessibility permission. The timeout is generous because this only
    runs when the user has actually clicked a pill - unlike foreground_title,
    nothing is waiting on it.
    """
    safe = project.replace('"', "").replace("\\", "")
    if not safe:
        return False
    out = _osa(
        'tell application "System Events"\n'
        '  repeat with p in (every application process '
        '    whose background only is false)\n'
        '    try\n'
        '      repeat with w in (every window of p)\n'
        '        set t to ""\n'
        '        try\n'
        '          set t to value of attribute "AXTitle" of w\n'
        '        end try\n'
        f'        if t contains "{safe}" then\n'
        '          set frontmost of p to true\n'
        '          try\n'
        '            perform action "AXRaise" of w\n'
        '          end try\n'
        '          return "ok"\n'
        '        end if\n'
        '      end repeat\n'
        '    end try\n'
        '  end repeat\n'
        'end tell\n'
        'return "no"',
        timeout=4.0,
    )
    return out == "ok"


# --------------------------------------------------------- single instance
def single_instance():
    """True if we are the only Vigil; False if one is already running.

    Windows uses a kernel named mutex rather than QSharedMemory, which silently
    failed in the frozen build and let a second dot onto the screen. POSIX uses
    an exclusive flock. Both are released by the OS when the process dies, so a
    crash cannot strand the lock.
    """
    global _LOCK

    if WINDOWS:
        try:
            import ctypes
            from ctypes import wintypes
            k32 = ctypes.windll.kernel32
            k32.CreateMutexW.restype = wintypes.HANDLE
            _LOCK = k32.CreateMutexW(None, True, "Global\\VigilWidgetSingleInstance")
            ERROR_ALREADY_EXISTS = 183
            if k32.GetLastError() == ERROR_ALREADY_EXISTS:
                return False
            return True
        except Exception:
            return True                # never block startup over a failed guard

    try:
        import fcntl
        path = os.path.join(data_dir(), "widget.lock")
        f = open(path, "w")
        try:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            f.close()
            return False               # someone else holds it
        f.write(str(os.getpid()))
        f.flush()
        _LOCK = f                      # keep the fd open or the lock drops
        return True
    except Exception:
        return True


# -------------------------------------------------------------- autostart
_PLIST_LABEL = "com.vigil.widget"


def _plist_path():
    return os.path.join(os.path.expanduser("~"), "Library", "LaunchAgents",
                        _PLIST_LABEL + ".plist")


def set_autostart(on, command=None):
    """Start Vigil at login. `command` is an argv list."""
    if WINDOWS:
        return _autostart_windows(on, command)
    if MACOS:
        return _autostart_macos(on, command)
    return False


def _autostart_windows(on, command):
    RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0,
                            winreg.KEY_SET_VALUE) as k:
            if on:
                cmd = " ".join(f'"{p}"' if " " in p else p for p in (command or []))
                winreg.SetValueEx(k, "Vigil", 0, winreg.REG_SZ, cmd)
            else:
                try:
                    winreg.DeleteValue(k, "Vigil")
                except FileNotFoundError:
                    pass
        return True
    except Exception:
        return False


def _autostart_macos(on, command):
    from xml.sax.saxutils import escape
    path = _plist_path()
    try:
        if on:
            if not command:
                return False
            os.makedirs(os.path.dirname(path), exist_ok=True)
            args = "".join(f"    <string>{escape(str(a))}</string>\n" for a in command)
            plist = (
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
                '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
                '<plist version="1.0">\n'
                '<dict>\n'
                f'  <key>Label</key><string>{_PLIST_LABEL}</string>\n'
                '  <key>ProgramArguments</key>\n'
                f'  <array>\n{args}  </array>\n'
                '  <key>RunAtLoad</key><true/>\n'
                # Deliberately no KeepAlive: if the user quits Vigil from the
                # tray, launchd must not immediately resurrect it.
                '  <key>KeepAlive</key><false/>\n'
                '</dict>\n'
                '</plist>\n'
            )
            with open(path, "w", encoding="utf-8") as f:
                f.write(plist)
            subprocess.run(["launchctl", "unload", path],
                           capture_output=True, stdin=subprocess.DEVNULL)
            subprocess.run(["launchctl", "load", path],
                           capture_output=True, stdin=subprocess.DEVNULL)
        else:
            if os.path.exists(path):
                subprocess.run(["launchctl", "unload", path],
                               capture_output=True, stdin=subprocess.DEVNULL)
                os.remove(path)
        return True
    except Exception:
        return False


def is_autostart():
    if WINDOWS:
        RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
                winreg.QueryValueEx(k, "Vigil")
            return True
        except Exception:
            return False
    if MACOS:
        return os.path.exists(_plist_path())
    return False


def platform_name():
    return "windows" if WINDOWS else "macos" if MACOS else "linux" if LINUX else "unknown"
