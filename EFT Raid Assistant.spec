# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

from PyInstaller.utils.hooks import collect_dynamic_libs

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
qt_hiddenimports = [
    'PySide6.QtCore',
    'PySide6.QtGui',
    'PySide6.QtWidgets',
    'shiboken6',
]

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=qt_binaries + env_bin_binaries + [('C:\\Users\\zetia\\miniconda3\\envs\\eft-raid-assistant\\Library\\bin\\archive.dll', 'tesseract'), ('C:\\Users\\zetia\\miniconda3\\envs\\eft-raid-assistant\\Library\\bin\\charset.dll', 'tesseract'), ('C:\\Users\\zetia\\miniconda3\\envs\\eft-raid-assistant\\Library\\bin\\deflate.dll', 'tesseract'), ('C:\\Users\\zetia\\miniconda3\\envs\\eft-raid-assistant\\Library\\bin\\gif-7.dll', 'tesseract'), ('C:\\Users\\zetia\\miniconda3\\envs\\eft-raid-assistant\\Library\\bin\\iconv.dll', 'tesseract'), ('C:\\Users\\zetia\\miniconda3\\envs\\eft-raid-assistant\\Library\\bin\\icudt78.dll', 'tesseract'), ('C:\\Users\\zetia\\miniconda3\\envs\\eft-raid-assistant\\Library\\bin\\icuuc78.dll', 'tesseract'), ('C:\\Users\\zetia\\miniconda3\\envs\\eft-raid-assistant\\Library\\bin\\jpeg8.dll', 'tesseract'), ('C:\\Users\\zetia\\miniconda3\\envs\\eft-raid-assistant\\Library\\bin\\leptonica-1.87.0.dll', 'tesseract'), ('C:\\Users\\zetia\\miniconda3\\envs\\eft-raid-assistant\\Library\\bin\\lerc.dll', 'tesseract'), ('C:\\Users\\zetia\\miniconda3\\envs\\eft-raid-assistant\\Library\\bin\\libbz2.dll', 'tesseract'), ('C:\\Users\\zetia\\miniconda3\\envs\\eft-raid-assistant\\Library\\bin\\libcrypto-3-x64.dll', 'tesseract'), ('C:\\Users\\zetia\\miniconda3\\envs\\eft-raid-assistant\\Library\\bin\\libcurl.dll', 'tesseract'), ('C:\\Users\\zetia\\miniconda3\\envs\\eft-raid-assistant\\Library\\bin\\liblzma.dll', 'tesseract'), ('C:\\Users\\zetia\\miniconda3\\envs\\eft-raid-assistant\\Library\\bin\\libpng16.dll', 'tesseract'), ('C:\\Users\\zetia\\miniconda3\\envs\\eft-raid-assistant\\Library\\bin\\libsharpyuv.dll', 'tesseract'), ('C:\\Users\\zetia\\miniconda3\\envs\\eft-raid-assistant\\Library\\bin\\libssh2.dll', 'tesseract'), ('C:\\Users\\zetia\\miniconda3\\envs\\eft-raid-assistant\\Library\\bin\\libwebp.dll', 'tesseract'), ('C:\\Users\\zetia\\miniconda3\\envs\\eft-raid-assistant\\Library\\bin\\libwebpmux.dll', 'tesseract'), ('C:\\Users\\zetia\\miniconda3\\envs\\eft-raid-assistant\\Library\\bin\\libxml2.dll', 'tesseract'), ('C:\\Users\\zetia\\miniconda3\\envs\\eft-raid-assistant\\Library\\bin\\lz4.dll', 'tesseract'), ('C:\\Users\\zetia\\miniconda3\\envs\\eft-raid-assistant\\Library\\bin\\msvcp140.dll', 'tesseract'), ('C:\\Users\\zetia\\miniconda3\\envs\\eft-raid-assistant\\Library\\bin\\openjp2.dll', 'tesseract'), ('C:\\Users\\zetia\\miniconda3\\envs\\eft-raid-assistant\\Library\\bin\\tesseract.exe', 'tesseract'), ('C:\\Users\\zetia\\miniconda3\\envs\\eft-raid-assistant\\Library\\bin\\tesseract55.dll', 'tesseract'), ('C:\\Users\\zetia\\miniconda3\\envs\\eft-raid-assistant\\Library\\bin\\tiff.dll', 'tesseract'), ('C:\\Users\\zetia\\miniconda3\\envs\\eft-raid-assistant\\Library\\bin\\vcruntime140.dll', 'tesseract'), ('C:\\Users\\zetia\\miniconda3\\envs\\eft-raid-assistant\\Library\\bin\\vcruntime140_1.dll', 'tesseract'), ('C:\\Users\\zetia\\miniconda3\\envs\\eft-raid-assistant\\Library\\bin\\zlib.dll', 'tesseract'), ('C:\\Users\\zetia\\miniconda3\\envs\\eft-raid-assistant\\Library\\bin\\zstd.dll', 'tesseract')],
    datas=[('config.json', '.'), ('cache', 'cache'), ('data', 'data'), ('assets', 'assets'), ('C:\\Users\\zetia\\miniconda3\\envs\\eft-raid-assistant\\Library\\share\\tessdata', 'tessdata')],
    hiddenimports=qt_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['pandas', 'numpy', 'scipy', 'matplotlib', 'sqlalchemy', 'lxml', 'cryptography', 'bcrypt', 'psycopg2', 'IPython', 'notebook', 'traitlets'],
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
