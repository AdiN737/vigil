# PyInstaller spec for the macOS build.  Run ON a Mac:  pyinstaller Vigil-macos.spec
#
# Two targets, exactly as on Windows, and for the same reason: the hook runs on
# every agent turn, so it must not link Qt.  Loading the UI framework to decide
# there was nothing to say cost 3 seconds per turn; the split hook is ~170ms.
#
# Build the hook FIRST (Hook-macos.spec), then this, then drop the resulting
# `vigil-hook` next to Vigil.app.

block_cipher = None

a = Analysis(
    ['vigil_widget.py'],
    pathex=['.'],
    binaries=[],
    datas=[],
    hiddenimports=['vigil_platform', 'vigil_setup', 'vigil_decide'],
    hookspath=[],
    runtime_hooks=[],
    # pywin32 is Windows-only and must never be pulled into a Mac build.
    excludes=['win32gui', 'win32con', 'win32api', 'winreg', 'tkinter'],
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name='Vigil',
    debug=False,
    strip=False,
    upx=False,
    console=False,
)

coll = COLLECT(
    exe, a.binaries, a.zipfiles, a.datas,
    strip=False, upx=False, name='Vigil',
)

app = BUNDLE(
    coll,
    name='Vigil.app',
    icon=None,
    bundle_identifier='com.vigil.widget',
    info_plist={
        # A status widget belongs in the menu bar, not the Dock or the
        # app switcher.  LSUIElement is what makes it an accessory app.
        'LSUIElement': True,
        'CFBundleShortVersionString': '0.1.1',
        'CFBundleVersion': '0.1.1',
        'NSHighResolutionCapable': True,
        # macOS shows this string when it asks for Accessibility permission.
        # Say plainly what it is for; a vague reason gets denied.
        'NSAppleEventsUsageDescription':
            'Vigil reads the title of the window you are looking at, so it can '
            'stay silent when you are already watching the agent that needs you, '
            'and bring that window forward when you click a notification.',
    },
)
