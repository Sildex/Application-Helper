# -*- mode: python ; coding: utf-8 -*-
import certifi
from pathlib import Path

block_cipher = None

a = Analysis(
    ['start.py'],
    pathex=[str(Path('.').resolve())],
    binaries=[],
    datas=[
        ('backend', 'backend'),
        ('app', 'app'),
        ('autoapply.ico', '.'),
        (certifi.where(), 'certifi'),
    ],
    hiddenimports=[
        'PyQt6', 'PyQt6.QtWidgets', 'PyQt6.QtCore', 'PyQt6.QtGui',
        'sqlmodel', 'sqlalchemy', 'sqlalchemy.dialects.sqlite',
        'pydantic', 'pydantic_settings',
        'httpx', 'ollama', 'dotenv', 'psutil', 'certifi',
        'backend.services.ba_fetch',
        'backend.services.ai_scorer',
        'app.ai_score_engine',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['customtkinter', 'tkinter', 'uvicorn', 'fastapi', 'starlette'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='Application Helper',
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
    icon='autoapply.ico',
    runtime_tmpdir=None,
)
