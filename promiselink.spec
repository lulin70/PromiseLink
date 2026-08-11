# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for PromiseLink packaging.

Build command:
    pyinstaller promiselink.spec --clean --noconfirm

Output:
    dist/PromiseLink.app (macOS) or dist/PromiseLink.exe (Windows)
"""

import os
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

block_cipher = None

# Collect all submodules for libraries with dynamic imports
# NOTE: collect_submodules('promiselink') is required because launcher.py
# imports the app via the string "promiselink.main:app" passed to uvicorn.run,
# which PyInstaller's static analysis cannot see. Collecting the whole package
# ensures promiselink.main and all submodules (api, services, core, db, ...) are
# bundled and resolvable at runtime.
hiddenimports = (
    collect_submodules('sqlalchemy.dialects')
    + collect_submodules('uvicorn')
    + collect_submodules('promiselink')
    + collect_submodules('promiselink.services.steps')
    + collect_submodules('promiselink.api.v1')
    + [
        'uvicorn.logging',
        'uvicorn.loops',
        'uvicorn.loops.auto',
        'uvicorn.protocols',
        'uvicorn.protocols.http.auto',
        'uvicorn.protocols.websockets.auto',
        'sqlalchemy.dialects.sqlite',
        'sqlalchemy.dialects.postgresql',
        # SQLAlchemy imports DBAPI drivers dynamically via import_dbapi(),
        # so PyInstaller cannot detect them. List them explicitly.
        'aiosqlite',
        'asyncpg',
        'psycopg2',
        # certifi CA bundle — required for SSL verification in PyInstaller bundle
        # (launcher.py sets SSL_CERT_FILE=certifi.where() at startup)
        'certifi',
        # API routers
        'promiselink.api.v1.events',
        'promiselink.api.v1.entities',
        'promiselink.api.v1.pair',
        'promiselink.api.v1.event_pipeline_api',
        # Services (relay_client lives in services/, not api/v1/)
        'promiselink.services.relay_client',
        'promiselink.services.relay_wss_client',
        'promiselink.services.relay_endpoints',
        'promiselink.services.event_processor',
        'promiselink.services.event_pipeline',
        # Pipeline steps (13 steps, collect_submodules covers them but list critical ones)
        'promiselink.services.steps.step_01_verify',
        'promiselink.services.steps.step_02_extract',
        'promiselink.services.steps.step_03_embedding',
        'promiselink.services.steps.step_04_todo',
        'promiselink.services.steps.step_05_promise',
        'promiselink.services.steps.step_13_complete',
    ]
)

a = Analysis(
    ['launcher.py'],
    pathex=[os.path.abspath('src')],
    binaries=[],
    datas=[
        # Frontend static files (built via `npm run build:h5` in CI workflow)
        ('frontend/dist', 'frontend/dist'),
    ]
    # certifi CA bundle — required for SSL verification (relay WSS, OAuth, etc.)
    # Without this, PyInstaller bundle fails: "unable to get local issuer certificate"
    + collect_data_files('certifi'),
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        'matplotlib',
        'pandas',
        'PIL',
        'tkinter',
        'pytest',
        'mypy',
        'ruff',
        'black',
        # Heavy ML/scientific libraries not required by PromiseLink runtime.
        # Excluding them keeps the DMG ~36MB instead of ~300MB.
        'torch',
        'transformers',
        'tokenizers',
        'sklearn',
        'scipy',
        'cv2',
        'tensorflow',
        'datasets',
        'pygame',
        'IPython',
        'jupyter',
        'notebook',
    ],
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
    name='PromiseLink',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    runtime_tmpdir=None,
    console=True,  # Set to False for windowed mode (no terminal)
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

# macOS app bundle
app = BUNDLE(
    exe,
    name='PromiseLink.app',
    icon=None,  # TODO: Add .icns icon
)
