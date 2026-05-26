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

datas = [('.env.example', '.'), ('.env', '.'), ('assets', 'assets')]
binaries = []
hiddenimports = []

# 项目自身包
tmp_ret = collect_all('subtitle_info_collection')
datas += [(src, dst) for src, dst in tmp_ret[0] if not src.endswith('.pyi')]
binaries += tmp_ret[1]
hiddenimports += tmp_ret[2]

# PySide6 - 收集后过滤 .pyi 和 .qm 文件
tmp_ret = collect_all('PySide6')
datas_pyside6 = [(src, dst) for src, dst in tmp_ret[0]
                  if not (src.endswith('.pyi') or src.endswith('.qm') or 'qtwebengine' in str(src).lower() or 'qml' in str(dst).lower().replace('\\\\', '/').split('/')[0] or src.endswith('.debug.pak') or src.endswith('.debug.bin'))]
datas += datas_pyside6
binaries += tmp_ret[1]
hiddenimports += tmp_ret[2]

# PySide6-Fluent-Widgets - 收集后过滤 .pyi 文件
tmp_ret = collect_all('qfluentwidgets')
datas_qfw = [(src, dst) for src, dst in tmp_ret[0]
              if not src.endswith('.pyi')]
datas += datas_qfw
binaries += tmp_ret[1]
hiddenimports += tmp_ret[2]

# PySideSix-Frameless-Window
tmp_ret = collect_all('PySideSix_Frameless_Window')
datas += [(src, dst) for src, dst in tmp_ret[0] if not src.endswith('.pyi')]
binaries += tmp_ret[1]
hiddenimports += tmp_ret[2]

# Playwright - 收集后过滤 .pyi 文件
tmp_ret = collect_all('playwright')
datas_playwright = [(src, dst) for src, dst in tmp_ret[0]
                    if not src.endswith('.pyi')]
datas += datas_playwright
binaries += tmp_ret[1]
hiddenimports += tmp_ret[2]

# 其他运行时依赖
for _pkg in ['httpx', 'tenacity', 'aiolimiter', 'charset_normalizer',
             'pysubs2', 'dotenv', 'keyring', 'darkdetect',
             'bs4', 'py7zr', 'Cryptodome', 'greenlet']:
    try:
        tmp_ret = collect_all(_pkg)
        datas += [(src, dst) for src, dst in tmp_ret[0] if not src.endswith('.pyi')]
        binaries += tmp_ret[1]
        hiddenimports += tmp_ret[2]
    except Exception:
        pass

# Playwright 浏览器 - 保留（根据用户选择）
datas += collect_playwright_local_browsers()


a = Analysis(
    ['src\\subtitle_info_collection\\main.py'],
    pathex=[str(PROJECT_ROOT / 'src')],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # 未使用的 PySide6 模块
        'PySide6.Qt3DAnimation',
        'PySide6.Qt3DCore',
        'PySide6.Qt3DExtras',
        'PySide6.Qt3DInput',
        'PySide6.Qt3DLogic',
        'PySide6.Qt3DRender',
        'PySide6.Qt3DQuick',
        'PySide6.Qt3DQuickAnimation',
        'PySide6.Qt3DQuickExtras',
        'PySide6.Qt3DQuickInput',
        'PySide6.Qt3DQuickLogic',
        'PySide6.Qt3DQuickRender',
        'PySide6.Qt3DQuickScene2D',
        'PySide6.QtCharts',
        'PySide6.QtDataVisualization',
        'PySide6.QtScxml',
        'PySide6.QtSensors',
        'PySide6.QtSerialPort',
        'PySide6.QtVirtualKeyboard',
        'PySide6.QtWebEngine',
        'PySide6.QtWebEngineCore',
        'PySide6.QtWebEngineWidgets',
        'PySide6.QtWebEngineQuick',
        'PySide6.QtWebChannel',
        'PySide6.QtWebSockets',
        'PySide6.QtHttpServer',
        'PySide6.QtBluetooth',
        'PySide6.QtDesigner',
        'PySide6.QtHelp',
        'PySide6.QtMultimedia',
        'PySide6.QtMultimediaWidgets',
        'PySide6.QtNfc',
        'PySide6.QtOpenGL',
        'PySide6.QtOpenGLWidgets',
        'PySide6.QtPdf',
        'PySide6.QtPdfWidgets',
        'PySide6.QtPositioning',
        'PySide6.QtPrintSupport',
        'PySide6.QtQuick',
        'PySide6.QtQuick3D',
        'PySide6.QtQuickControls2',
        'PySide6.QtQuickWidgets',
        'PySide6.QtRemoteObjects',
        'PySide6.QtTest',
        'PySide6.QtTextToSpeech',
        'PySide6.QtUiTools',
        'PySide6.QtLocation',
        'PySide6.QtQml',
        
        # 标准库中未使用的模块
        'unittest',
        'unittest.mock',
        'ensurepip',
        'venv',
        'pydoc',
        'doctest',
        'lib2to3',
        'tkinter',
        'turtle',
        'antigravity',
        
        # 开发工具（不应打包到生产环境）
        'pip',
        'setuptools',
        'wheel',
        'pytest',
        'pytest-asyncio',
        'ruff',
        'pyinstaller',
    ],
    noarchive=False,
    optimize=2,  # 使用 Python 优化模式，移除文档字符串
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    icon='assets/head_logo.ico',
    debug=False,
    bootloader_ignore_signals=False,
    strip=True,
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
    strip=True,
    upx=True,
    upx_exclude=['*.local-browsers*'],
    name=APP_NAME,
)
