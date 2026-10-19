# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_submodules, collect_data_files, copy_metadata


a = Analysis(
    ['UAVDesignTool.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('uav_app/templates/*', 'templates'),
        ('plane.ico', '.'),
        # Shipped as source so it can be copied into project Tools/ folders
        # and still run under a plain Python interpreter.
        ('uavlib', 'uavlib'),
    ] + collect_data_files('pymoo') + copy_metadata('moocore') + copy_metadata('pymoo'),
    hiddenimports=['matplotlib', 'matplotlib.backends.backend_agg'] + collect_submodules('pymoo') + collect_submodules('moocore'),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Only the Agg backend is used; the GUI backends pull in large,
        # redundant toolkits.
        'matplotlib.backends.backend_qtagg',
        'matplotlib.backends.backend_tkagg',
        'matplotlib.backends.backend_webagg',
        'tkinter', 'PyQt5', 'PySide2', 'PySide6',
        'pandas', 'IPython', 'notebook',
    ],
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
    name='UAVDesignTool',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['plane.ico'],
)
