# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_data_files

APP_NAME = "字幕采集工具"
BACKEND_DIR = Path(SPECPATH).resolve()
PROJECT_ROOT = BACKEND_DIR.parent
SRC_DIR = BACKEND_DIR / "src"
FRONTEND_DIST = PROJECT_ROOT / "frontend" / "dist"

if not (FRONTEND_DIST / "index.html").exists():
    raise SystemExit(
        "未找到前端构建产物，请先执行：cd frontend; npm ci; npm run build"
    )

# 只打包配置模板；真实 .env 由用户在用户目录生成，禁止随产物分发
datas = [
    (str(PROJECT_ROOT / ".env.example"), "."),
    (str(BACKEND_DIR / "assets"), "assets"),
    (str(FRONTEND_DIST), "webui"),
]
binaries = []
hiddenimports = []


def collect_package(
    name: str,
    *,
    skip_browsers: bool = False,
    skip_tests: bool = True,
) -> None:
    """收集第三方包的数据、二进制与隐式导入。"""
    try:
        package_datas, package_binaries, package_hiddenimports = collect_all(name)
    except Exception as exc:  # noqa: BLE001
        print(f"跳过无法收集的依赖 {name}：{exc}")
        return

    for source, target in package_datas:
        normalized = source.replace("\\", "/").lower()
        if source.endswith(".pyi"):
            continue
        if skip_browsers and ".local-browsers" in normalized:
            continue
        if skip_tests and any(
            marker in normalized for marker in ("/selftest/", "/tests/", "/test/")
        ):
            continue
        datas.append((source, target))
    binaries.extend(package_binaries)
    for hiddenimport in package_hiddenimports:
        parts = hiddenimport.lower().split(".")
        if skip_tests and any(part in {"test", "tests", "selftest"} for part in parts):
            continue
        hiddenimports.append(hiddenimport)


collect_package("subtitle_info_collection")
collect_package("velopack")
collect_package("playwright", skip_browsers=True)

for package in (
    "httpx",
    "tenacity",
    "aiolimiter",
    "charset_normalizer",
    "pysubs2",
    "dotenv",
    "keyring",
    "bs4",
    "py7zr",
    "Cryptodome",
    "greenlet",
    "jieba",
    "rarfile",
):
    collect_package(package)

# pywebview 的 hook 只收集 lib，js 注入脚本需要显式加入
datas.extend(collect_data_files("webview", subdir="js"))
hiddenimports.extend(
    [
        "clr",
        "pythonnet",
        "webview.platforms.winforms",
        "webview.platforms.edgechromium",
        "webview.platforms.win32",
        "playwright.async_api",
    ]
)


a = Analysis(
    [str(SRC_DIR / "subtitle_info_collection" / "main.py")],
    pathex=[str(SRC_DIR)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "pytest",
        "ruff",
        "pyinstaller",
        "setuptools",
        "pip",
        "wheel",
        "tkinter",
    ],
    noarchive=False,
    optimize=2,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    icon=str(BACKEND_DIR / "assets" / "head_logo.ico"),
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
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
    upx=False,
    name=APP_NAME,
)
