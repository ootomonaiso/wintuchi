# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for EnvMonitor.
# Build (onefile, default):  pyinstaller build/envmon.spec
# For onedir, set ONEFILE = False below.
import os
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ONEFILE = True

block_cipher = None

# SPECPATH = directory of this spec file. Resolve paths independent of cwd.
ROOT = os.path.dirname(SPECPATH)
ICON = os.path.join(ROOT, "envmon", "assets", "app.ico")
ENTRY = os.path.join(ROOT, "run_envmon.py")

# customtkinter ships theme JSON data files that must be bundled.
datas = collect_data_files("customtkinter")
datas += [(ICON, "envmon/assets")]

hiddenimports = []
hiddenimports += collect_submodules("windows_toasts")
hiddenimports += collect_submodules("pystray")
hiddenimports += ["win32api", "win32event", "winerror", "PIL._tkinter_finder"]

a = Analysis(
    [ENTRY],
    pathex=[ROOT],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter.test", "test"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

if ONEFILE:
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.zipfiles,
        a.datas,
        [],
        name="EnvMonitor",
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=True,
        upx_exclude=[],
        runtime_tmpdir=None,
        console=False,  # windowless (tray-resident)
        disable_windowed_traceback=False,
        icon=ICON,
    )
else:
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name="EnvMonitor",
        debug=False,
        strip=False,
        upx=True,
        console=False,
        icon=ICON,
    )
    coll = COLLECT(
        exe, a.binaries, a.zipfiles, a.datas,
        strip=False, upx=True, upx_exclude=[], name="EnvMonitor",
    )
