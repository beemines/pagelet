# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
import site
ROOT = Path(SPECPATH).parent
site.addsitedir(str(ROOT / 'vendor'))

a = Analysis(
    [str(ROOT / 'desktop.py')],
    pathex=[str(ROOT), str(ROOT/'vendor'), str(ROOT/'vendor/win32'), str(ROOT/'vendor/win32/lib')],
    binaries=[(str(file),'winpty') for file in (ROOT/'vendor/winpty').iterdir() if file.suffix in {'.dll','.exe'}],
    datas=[(str(ROOT/'static'), 'static'), (str(ROOT/'featured_books.json'), '.'),
           (str(ROOT/'vendor'), 'vendor')],
    hiddenimports=['server', 'launcher', 'pythoncom', 'pywintypes', 'winpty', 'winpty.winpty',
                   'win32com.shell.shell', 'win32com.server.policy', 'win32com.server.exception',
                   'send2trash.win.IFileOperationProgressSink'],
    excludes=['tkinter', 'pytest', 'numpy', 'pandas', 'IPython', 'matplotlib'],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='Pagelet', debug=False,
          bootloader_ignore_signals=False, strip=False, upx=False, console=False,
          icon=str(ROOT/'assets/pagelet.ico'), version=str(ROOT/'packaging/version.txt'))
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='Pagelet')
