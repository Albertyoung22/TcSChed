# -*- mode: python ; coding: utf-8 -*-
import sys
import os
import shutil

sys.modules['matplotlib'] = None
sys.modules['matplotlib.pyplot'] = None

# Pre-clean output dist directory safely
dist_target = os.path.join(SPECPATH, 'build_dist', '舟歌AI排課')
if os.path.exists(dist_target):
    try:
        shutil.rmtree(dist_target, ignore_errors=True)
    except Exception:
        pass

a = Analysis(
    ['desktop_app.py'],
    pathex=[],
    binaries=[],
    datas=[('templates', 'templates'), ('static', 'static'), ('config_rules.json', '.')],
    hiddenimports=['dbfread', 'ortools.sat.python.cp_model', 'waitress', 'flask', 'jinja2'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['torch', 'scipy', 'matplotlib', 'gevent', 'tkinter', 'IPython', 'notebook'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='舟歌AI排課',
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
    name='舟歌AI排課',
)
