# -*- mode: python ; coding: utf-8 -*-

import sys
from pathlib import Path


_conda_bin = Path(sys.prefix) / 'Library' / 'bin'
_runtime_dll_names = (
    'libcrypto-3-x64.dll',
    'libssl-3-x64.dll',
    'liblzma.dll',
    'libbz2.dll',
    'ffi-8.dll',
)
_runtime_binaries = [
    (str(_conda_bin / name), '.')
    for name in _runtime_dll_names
    if (_conda_bin / name).is_file()
]


a = Analysis(
    ['updater_main.py'],
    pathex=[],
    binaries=_runtime_binaries,
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['PySide6', 'PIL', 'numpy', 'cv2', 'onnxruntime', 'rapidocr'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='EFT Raid Assistant Updater',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='assets/app_icon.ico',
)
