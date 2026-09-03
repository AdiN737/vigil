"""
Tiny entry point for the hook half of Vigil.

This is built as its OWN executable, deliberately separate from the widget.
The widget imports PySide6 at module level; a frozen build loads that whole
bundle before any of our code runs, which cost ~3 SECONDS per hook. This file
touches nothing but the standard library.

    vigil-hook.exe blocked
"""
import sys

import vigil_hook


if __name__ == "__main__":
    state = sys.argv[1] if len(sys.argv) > 1 else "idle"
    # tolerate being called as "--hook blocked" too
    if state == "--hook":
        state = sys.argv[2] if len(sys.argv) > 2 else "idle"
    sys.exit(vigil_hook.run(state))
