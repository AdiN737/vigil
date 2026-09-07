# PyInstaller spec for the macOS HOOK.  Run ON a Mac:  pyinstaller Hook-macos.spec
#
# The whole point of this file is what it EXCLUDES.  This binary runs on every
# single agent turn, so it must not link Qt, PySide6, or anything that costs
# import time.  If you ever find yourself adding one of those to make an import
# work, you have broken the reason this file exists - fix the import instead.

block_cipher = None

a = Analysis(
    ['vigil_hook_main.py'],
    pathex=['.'],
    binaries=[],
    datas=[],
    hiddenimports=['vigil_platform'],
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        'PySide6', 'shiboken6', 'PyQt5', 'PyQt6',      # the expensive ones
        'win32gui', 'win32con', 'win32api', 'winreg',  # Windows-only
        'tkinter', 'numpy', 'PIL',
    ],
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz, a.scripts, a.binaries, a.zipfiles, a.datas, [],
    name='vigil-hook',
    debug=False,
    strip=False,
    upx=False,
    console=True,          # no window: it is invoked by Claude Code, not a user
)
