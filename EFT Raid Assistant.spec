# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

env_bin = Path('C:\\Users\\zetia\\miniconda3\\envs\\eft-raid-assistant\\Library\\bin')
env_bin_names = {
    'Qt6Core.dll',
    'Qt6Gui.dll',
    'Qt6Widgets.dll',
    'Qt6Network.dll',
    'pyside6.cp311-win_amd64.dll',
    'pyside6qml.cp311-win_amd64.dll',
    'shiboken6.cp311-win_amd64.dll',
    'MSVCP140.dll',
    'MSVCP140_1.dll',
    'MSVCP140_2.dll',
    'VCRUNTIME140.dll',
    'VCRUNTIME140_1.dll',
    'zlib-ng2.dll',
    'libwebpdemux.dll',
    'libwebp.dll',
    'libwebpmux.dll',
    'lcms2.dll',
    'libexpat.dll',
    'ffi-8.dll',
    'libssl-3-x64.dll',
    'libcrypto-3-x64.dll',
}
env_bin_binaries = [
    (str(env_bin / name), '.')
    for name in sorted(env_bin_names)
    if (env_bin / name).exists()
]
qt_binaries = collect_dynamic_libs('PySide6') + collect_dynamic_libs('shiboken6')
rapidocr_datas = collect_data_files(
    'rapidocr',
    includes=[
        'config.yaml',
        'default_models.yaml',
        'models/*.onnx',
        'inference_engine/pytorch/networks/*.yaml',
    ],
)
qt_hiddenimports = [
    'PySide6.QtCore',
    'PySide6.QtGui',
    'PySide6.QtWidgets',
    'shiboken6',
    'rapidocr',
    'onnxruntime',
    'numpy',
    'cv2',
]

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=qt_binaries + env_bin_binaries,
    datas=rapidocr_datas + [('config.json', '.'), ('cache', 'cache'), ('data', 'data'), ('assets', 'assets'), ('README.md', '.'), ('RELEASE_README_zh.txt', '.'), ('CHANGELOG.md', '.'), ('LICENSE', '.'), ('THIRD_PARTY_NOTICES.md', '.'), ('VERSION', '.')],
    hiddenimports=qt_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['pandas', 'scipy', 'matplotlib', 'sqlalchemy', 'lxml', 'cryptography', 'bcrypt', 'psycopg2', 'IPython', 'notebook', 'traitlets'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='EFT Raid Assistant',
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
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='EFT Raid Assistant',
)
