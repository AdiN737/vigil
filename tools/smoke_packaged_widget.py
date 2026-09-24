"""Windows packaged-widget smoke test with isolated fixture data.
Usage: python tools/smoke_packaged_widget.py path/to/Vigil.exe
Requires no existing Vigil process (the app has a global single-instance guard).
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import win32con
import win32gui
import win32process


def main():
    executable = Path(sys.argv[1]).resolve(strict=True)
    corner = tuple(map(int, sys.argv[2].split(","))) if len(sys.argv) > 2 else None
    with tempfile.TemporaryDirectory(prefix="vigil-packaged-smoke-") as td:
        if corner:
            (Path(td) / "widget.json").write_text(json.dumps(dict(x=corner[0], y=corner[1])))
        sessions = Path(td) / "sessions"
        sessions.mkdir()
        now = time.time()
        for i in range(4):
            record = dict(session_id=f"fixture-{i}", project=f"Project {i // 2 + 1}",
                          cwd=f"C:/VigilFixture/Project-{i // 2}", provider="codex" if i % 2 else "claude",
                          tier=2, state="working", since=now, updated=now, detail="Isolated smoke test")
            (sessions / f"{i}.json").write_text(json.dumps(record), encoding="utf-8")
        proc = subprocess.Popen([str(executable)], env=dict(os.environ, VIGIL_DATA_DIR=td))
        try:
            deadline = time.monotonic() + 15
            windows = []
            while time.monotonic() < deadline:
                if proc.poll() is not None:
                    raise RuntimeError(f"Widget exited during startup: {proc.returncode}")
                windows.clear()
                def collect(hwnd, _):
                    if win32process.GetWindowThreadProcessId(hwnd)[1] == proc.pid and win32gui.IsWindowVisible(hwnd):
                        windows.append(hwnd)
                win32gui.EnumWindows(collect, None)
                if windows:
                    break
                time.sleep(.1)
            assert windows, "No visible widget window"
            hwnd = windows[0]
            # Let the greeting expire; working fixtures must return to a dot.
            deadline = time.monotonic() + 12
            while time.monotonic() < deadline:
                rect = win32gui.GetClientRect(hwnd)
                if rect[2] < 60 and rect[3] < 60:
                    break
                time.sleep(.1)
            assert rect[2] < 60 and rect[3] < 60, f"Did not collapse: {rect}"
            dot = rect
            if corner:
                actual = win32gui.GetWindowRect(hwnd)[:2]
                assert actual == corner, f"Saved monitor position changed: {actual} != {corner}"
            pos = (8 << 16) | 8
            win32gui.PostMessage(hwnd, win32con.WM_LBUTTONDOWN, win32con.MK_LBUTTON, pos)
            win32gui.PostMessage(hwnd, win32con.WM_LBUTTONUP, 0, pos)
            time.sleep(1)
            expanded = win32gui.GetClientRect(hwnd)
            assert expanded[2] > 200 and expanded[3] >= 300, f"Four rows missing: {expanded}"
            # Removing one session must shrink the manual panel, preserving three.
            (sessions / "3.json").unlink()
            time.sleep(1)
            resized = win32gui.GetClientRect(hwnd)
            assert 150 < resized[3] < expanded[3], f"Panel did not resize: {resized}"
            assert proc.poll() is None
            print(json.dumps(dict(started=True, dot=dot, four_sessions=expanded, three_sessions=resized)))
        finally:
            if proc.poll() is None:
                proc.terminate()
            proc.wait(timeout=10)

if __name__ == "__main__":
    main()
