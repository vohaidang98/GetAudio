# -*- mode: python ; coding: utf-8 -*-

import os

a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=[('yt-dlp.exe', '.'), ('deno.exe', '.'), ('ffmpeg.exe', '.')],
    datas=[
        ('icon.ico', '.'),
        ('ffprobe.exe', '.'),
        ('dropdown-arrow-light.svg', '.'),
        ('dropdown-arrow-dark.svg', '.'),
    ],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

# Prevent unrelated native libraries from the build host from being bundled.
# These can be discovered through PATH when PyInstaller scans Qt plugins. In
# particular, their ICU/UCRT/API-set DLLs can shadow the Windows/Qt libraries
# and stop QtWidgets from loading in the frozen application.
def _is_codex_runtime_native(path):
    normalized = os.path.normcase(os.path.abspath(path))
    return (
        os.path.normcase(os.sep + 'codex-runtimes' + os.sep) in normalized
        and os.path.normcase(os.sep + 'dependencies' + os.sep + 'native' + os.sep) in normalized
    )


a.binaries = [entry for entry in a.binaries if not _is_codex_runtime_native(entry[1])]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='Gen Audio 4.2.0',
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
    icon=['icon.ico'],
)
