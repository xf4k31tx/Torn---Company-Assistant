# -*- mode: python ; coding: utf-8 -*-
import atexit
import json
import shutil
import tempfile
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

project_root = Path(SPECPATH)
oauth_sources = sorted(project_root.glob('client_secret_*.json'))
if len(oauth_sources) != 1:
    raise SystemExit('Production build requires exactly one local OAuth desktop-client configuration.')
oauth_config = json.loads(oauth_sources[0].read_text(encoding='utf-8'))
if not oauth_config.get('installed', {}).get('client_id') or not oauth_config['installed'].get('client_secret'):
    raise SystemExit('The local OAuth desktop-client configuration is invalid.')
oauth_stage_dir = Path(tempfile.mkdtemp(prefix='tca-oauth-'))
oauth_resource = oauth_stage_dir / '_tca_oauth.dat'
shutil.copyfile(oauth_sources[0], oauth_resource)
atexit.register(shutil.rmtree, oauth_stage_dir, ignore_errors=True)

datas = [(str(oauth_resource), '.')]
binaries = []
hiddenimports = []
tmp_ret = collect_all('matplotlib')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('google_auth_oauthlib')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
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
    name='Knotty Oil Tracker',
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
    icon=str(project_root / 'TCA-v3.ico'),
)
