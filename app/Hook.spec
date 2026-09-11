# -*- mode: python ; coding: utf-8 -*-
# The hook, built COMPLETELY separately from the widget so its folder contains
# nothing but the stdlib. Sharing a folder with Qt made the bootloader slow.
a = Analysis(
    ['vigil_hook_main.py'],
    hiddenimports=['vigil_hook'],
    excludes=['PySide6','shiboken6','tkinter','matplotlib','numpy','PIL','pytest',
              'unittest','email','http','xml','pydoc_data','sqlite3','ssl',
              'asyncio','multiprocessing','logging','decimal','pickle','socket',
              'lzma','bz2','csv','argparse','difflib','inspect'],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True,
          name='vigil-hook', console=True, icon=None)
coll = COLLECT(exe, a.binaries, a.datas, name='vigil-hook')
