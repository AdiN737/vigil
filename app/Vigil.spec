# -*- mode: python ; coding: utf-8 -*-
# onedir, NOT onefile: onefile unpacks to temp on every launch, which would add
# hundreds of ms to startup. The hook is built separately by Hook.spec - it must
# NOT link Qt, or every agent event pays ~3s of bootloader time.
a = Analysis(
    ['vigil_widget.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=['vigil_hook', 'vigil_setup', 'vigil_decide',
                   'vigil_version', 'vigil_remote', 'vigil_update', 'vigil_metrics',
                   'cryptography.hazmat.primitives.asymmetric.ed25519',
                   'win32gui', 'win32con'],
    excludes=['tkinter', 'matplotlib', 'numpy', 'PIL', 'pytest',
              'PySide6.QtNetwork', 'PySide6.QtQml', 'PySide6.QtQuick',
              'PySide6.QtWebEngineCore', 'PySide6.Qt3DCore',
              'PySide6.QtMultimedia', 'PySide6.QtSql', 'PySide6.QtTest'],
    noarchive=False,
)
# Qt uses Windows' ICU API. A third-party icuuc.dll found on PATH can
# export version-suffixed symbols and break QtCore before the window opens.
# Leave ICU resolution to Windows, as the unfrozen Qt installation does.
a.binaries = [entry for entry in a.binaries
              if entry[0].replace('\\', '/').rsplit('/', 1)[-1].lower()
              not in ('icuuc.dll', 'icudt78.dll')]
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True,
          name='Vigil', console=False, icon=None)
coll = COLLECT(exe, a.binaries, a.datas, name='Vigil')
