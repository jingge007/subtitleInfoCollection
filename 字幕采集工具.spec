# -*- mode: python ; coding: utf-8 -*-
import os
from pathlib import Path

import playwright
from PyInstaller.config import CONF
from PyInstaller.utils.hooks import collect_all

APP_NAME = '字幕采集工具'
PACKAGE_DIST_ENV_KEY = 'SUBTITLE_COLLECTION_PACKAGE_DIST_DIR'
PROJECT_ROOT = Path(SPECPATH).resolve()


def read_env_value(env_path: Path, key: str) -> str:
    if not env_path.exists():
        return ''

    text = env_path.read_text(encoding='utf-8-sig')
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        name, value = line.split('=', 1)
        if name.strip() == key:
            return value.strip().strip('"').strip("'")

    marker = f'{key}='
    if marker in text:
        return text.rsplit(marker, 1)[1].splitlines()[0].strip().strip('"').strip("'")
    return ''


def resolve_package_dist_paths() -> tuple[Path | None, Path | None]:
    configured = read_env_value(PROJECT_ROOT / '.env', PACKAGE_DIST_ENV_KEY)
    if not configured:
        return None, None

    configured_path = Path(configured).expanduser()
    if not configured_path.is_absolute():
        configured_path = PROJECT_ROOT / configured_path
    configured_path = configured_path.resolve()

    # 如果配置值最后一级已经是应用名，就把它视为最终产物目录。
    if configured_path.name == APP_NAME:
        return configured_path.parent, configured_path
    return configured_path, configured_path / APP_NAME


def collect_playwright_local_browsers() -> list[tuple[str, str]]:
    package_browsers_path = (
        Path(playwright.__file__).resolve().parent
        / 'driver'
        / 'package'
        / '.local-browsers'
    )
    default_cache_path = Path(os.environ.get('LOCALAPPDATA', '')) / 'ms-playwright'
    for browsers_path in (package_browsers_path, default_cache_path):
        if not browsers_path.exists():
            continue
        has_chromium = next(browsers_path.rglob('chrome.exe'), None)
        has_headless_shell = next(browsers_path.rglob('chrome-headless-shell.exe'), None)
        if has_chromium and has_headless_shell:
            return [(str(browsers_path), 'playwright/driver/package/.local-browsers')]
    print(f'未找到完整的 Playwright 浏览器目录：{package_browsers_path} 或 {default_cache_path}')
    print('请先运行：$env:PLAYWRIGHT_BROWSERS_PATH="0"; python -m playwright install chromium')
    return []


package_dist_root, package_output_path = resolve_package_dist_paths()
if package_dist_root:
    CONF['distpath'] = str(package_dist_root)
    print(f'检测到自定义打包输出目录：{package_output_path}')

datas = [('.env.example', '.'), ('.env', '.')]
binaries = []
hiddenimports = []
tmp_ret = collect_all('PySide6')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('playwright')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
datas += collect_playwright_local_browsers()


a = Analysis(
    ['src\\subtitle_info_collection\\main.py'],
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
    [],
    exclude_binaries=True,
    name=APP_NAME,
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
    name=APP_NAME,
)
