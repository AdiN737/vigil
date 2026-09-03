# -*- mode: python ; coding: utf-8 -*-
a = Analysis(
    ['vigil_widget.py'],
    hiddenimports=['vigil_setup','vigil_hook','win32gui','win32con'],
    excludes=['tkinter','matplotlib','numpy','PIL','pytest',
              'PySide6.QtNetwork','PySide6.QtQml','PySide6.QtQuick',
              'PySide6.QtWebEngineCore','PySide6.Qt3DCore',
              'PySide6.QtMultimedia','PySide6.QtSql','PySide6.QtTest'],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True,
          name='Vigil', console=False, icon=None)
coll = COLLECT(exe, a.binaries, a.datas, name='Vigil')
