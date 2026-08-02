# -*- mode: python ; coding: utf-8 -*-

import os
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
    'jpeg8.dll',
    'tiff.dll',
    'openjp2.dll',
    'deflate.dll',
    'Lerc.dll',
    'yaml.dll',
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
app_datas = [
    ('data', 'data'),
    ('assets', 'assets'),
    ('README.md', '.'),
    ('RELEASE_README_zh.txt', '.'),
    ('CHANGELOG.md', '.'),
    ('LICENSE', '.'),
    ('THIRD_PARTY_NOTICES.md', '.'),
    ('VERSION', '.'),
]
release_cache_dir = Path(os.environ.get('EFT_RELEASE_CACHE_DIR', 'cache'))
if release_cache_dir.exists():
    app_datas.append((str(release_cache_dir), 'cache'))
debug_build = os.environ.get('EFT_BUILD_CONSOLE') == '1'
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
    datas=rapidocr_datas + app_datas,
    hiddenimports=qt_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['pandas', 'scipy', 'matplotlib', 'sqlalchemy', 'lxml', 'cryptography', 'bcrypt', 'psycopg2', 'IPython', 'notebook', 'traitlets'],
    noarchive=False,
    optimize=0,
)
mkl_runtime_keep = {
    'mkl_rt.3.dll',
    'mkl_core.3.dll',
    'mkl_intel_thread.3.dll',
    'mkl_def.3.dll',
}
a.binaries = [
    entry
    for entry in a.binaries
    if not Path(entry[0]).name.lower().startswith('mkl')
    or Path(entry[0]).name.lower() in mkl_runtime_keep
]
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='EFT Raid Assistant',
    debug=debug_build,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=debug_build,
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
