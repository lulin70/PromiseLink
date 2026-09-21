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
        # SQLAlchemy imports DBAPI drivers dynamically via import_dbapi(),
        # so PyInstaller cannot detect them. List them explicitly.
        'aiosqlite',
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
    # console=False（窗口化，⑥ / L-16，2026-09-21）：PyInstaller 在
    # console=True 时会顺带写 LSBackgroundOnly=true（源码：if self.console:
    # info_plist_dict['LSBackgroundOnly'] = True），结果是"黑底终端窗口可见
    # + Dock 无图标 / 不参与 Cmd-Tab"——恰好取了两者的缺点。
    # 改窗口化后终端窗口消失，故**必须先有文件日志**（core/logging.py 写
    # ~/.promiselink/logs/，轮转保留 3 份）作为非技术用户唯一可交付的诊断证据；
    # 顺序不可颠倒，否则排障能力归零。
    console=False,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

# macOS app bundle
#
# L-12（2026-09-21）：此前 BUNDLE 未传 version= / bundle_identifier=，
# PyInstaller 便用默认值 —— CFBundleShortVersionString="0.0.0"、
# CFBundleIdentifier=appname（"PromiseLink"）。实测 v1.1.1 的 dmg：
#     plutil -p PromiseLink.app/Contents/Info.plist
#     "CFBundleShortVersionString" => "0.0.0"
#     "CFBundleIdentifier" => "PromiseLink"
# 用户「显示简介」看到的就是 0.0.0，无法判断装的是哪一版；售后排查与"该升级了"
# 的引导都失去依据（应用内版本号正常，来自 src/promiselink/__init__.py）。
#
# 版本号单一事实源 = 仓库根 VERSION 文件（与本仓 CI 的 Version consistency gate
# 同源），在 spec 内直接读取，因此不会与代码漂移；读不到就让构建失败，
# 而不是又静默退回 0.0.0。
_version_file = os.path.join(SPECPATH, 'VERSION')
with open(_version_file, encoding='utf-8') as _fh:
    _version = _fh.read().strip()
if not _version:
    raise SystemExit(f'VERSION file is empty: {_version_file}')

app = BUNDLE(
    exe,
    name='PromiseLink.app',
    icon=None,  # TODO: Add .icns icon
    version=_version,
    bundle_identifier='com.carrymem.promiselink',
)
