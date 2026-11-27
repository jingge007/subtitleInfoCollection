# 本地开发与发布

## 前置条件

- Windows 10/11 x64
- Python 3.12+
- Node.js 20+
- WebView2 Runtime

## 首次准备

```powershell
cd <项目根目录>
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e "backend[dev]"
python -m playwright install chromium

cd frontend
npm ci
cd ..

Copy-Item .env.example .env
```

## 开发模式

一键启动：

```powershell
.\scripts\run_dev.ps1
```

脚本会启动 Vite（`127.0.0.1:5173`），等待就绪后启动 pywebview，并把 `--dev-url` 指向 Vite。

分开启动：

```powershell
cd frontend
npm run dev
```

```powershell
.\.venv\Scripts\python.exe -m subtitle_info_collection --dev-url http://127.0.0.1:5173
```

打开开发者工具：

```powershell
.\.venv\Scripts\python.exe -m subtitle_info_collection --dev-url http://127.0.0.1:5173 --devtools
```

## 纯浏览器调试

直接访问 `http://127.0.0.1:5173`。`bridge.ts` 检测不到 `window.pywebview` 时使用 `mock.ts`，可以独立调试 9 个页面的布局、交互和状态。

注意：浏览器 mock 不执行真实采集、解析、更新或文件对话框；涉及后端行为时仍需在 pywebview 中验证。

窗口置顶可在 pywebview 窗口顶栏用图钉按钮验证；浏览器 mock 只验证按钮状态和 `localStorage["ui.alwaysOnTop"]` 记忆，不改变真实窗口层级。

## 生产构建本地验证

```powershell
cd frontend
npm run build
cd ..
.\.venv\Scripts\python.exe -m subtitle_info_collection
```

`shell.py` 在源码运行时会回退读取 `frontend/dist`。

## 测试

```powershell
cd backend
..\.venv\Scripts\python.exe -m pytest -q
..\.venv\Scripts\python.exe -m ruff check src tests
cd ..

cd frontend
npm run typecheck
npm run build
cd ..
```

新增后端接口时，至少补充：

- `backend/tests/test_web_api.py`：参数校验、返回结构、路径边界。
- `backend/tests/test_updater.py`：更新状态转换与进度回调。
- 涉及配置时补充 `backend/tests/test_config_checks.py`。

## 打包

只生成便携目录（原始 onedir，不支持自更新）：

```powershell
.\scripts\build_windows.ps1
```

生成 Velopack 资产，并把便携目录替换为可自更新的 Velopack 便携结构：

```powershell
.\scripts\build_windows.ps1 -Pack
```

常用参数：

```powershell
.\scripts\build_windows.ps1 -Pack -PackVersion 0.2.2
.\scripts\build_windows.ps1 -SkipFrontend
.\scripts\build_windows.ps1 -SkipPlaywright
```

打包脚本行为：

1. 创建/复用 `.venv`，安装 `backend[dev]`。
2. `npm ci` + `npm run build`。
3. 检查 Playwright Chromium，必要时安装。
4. PyInstaller 按 `backend/字幕采集工具.spec` 生成 onedir。
5. 复制 Playwright 浏览器到 `_internal` 并精简完整 Chromium。
6. 删除 `.pyi`、`__pycache__`、`.dist-info` 等运行时无关文件。
7. 检查产物不含 `.env`，扫描疑似密钥。
8. `-Pack` 时准备 vpk 并生成 `Setup.exe`、`Portable.zip`、`nupkg`、`releases.win.json`。
9. `-Pack` 时展开 `Portable.zip` 到便携目录：顶层为 `.portable`、`Update.exe` 与 Velopack 启动器，真实程序位于 `current\`。

### 便携目录的两种形态

| 打包参数 | 便携目录内容 | 自更新 |
|---------|-------------|--------|
| 不带 `-Pack` | PyInstaller onedir 原始产物（`字幕采集工具.exe` + `_internal`） | 不支持 |
| 带 `-Pack` | Velopack 便携结构（`.portable` + `Update.exe` + 启动器 + `current\`） | 支持 |

不带 `-Pack` 重新构建时，脚本会先清空便携目录，不会残留上一次的 Velopack 文件。

Velopack 自更新依赖程序目录下的应用清单 `sq.version`：

- 安装版：`%LOCALAPPDATA%\Velopack\SubtitleInfoCollection\current\sq.version`；
- 便携解压版：`<解压目录>\current\sq.version`，`<解压目录>` 带 `.portable` 标记；
- 原始 onedir 目录没有任何 Velopack 清单，调用 `UpdateManager` 会抛 `Could not auto-locate app manifest`。

后端通过 `web/updater.py` 的 `detect_run_mode()` 识别这四种形态（`source` / `installed` / `portable` / `onedir`），不可更新的形态直接返回 `unsupported` 状态与中文说明，`app.info.runMode` 会把当前形态透传给前端展示。

### vpk 说明

Velopack 当前不提供官方 `vpk-win-x64.zip`，只发布 `vpk.<version>.nupkg`。打包脚本会：

- 下载 `dotnet-install.ps1`，把 .NET 8 运行时安装到 `scripts/tools/dotnet`；
- 下载 `vpk.<version>.nupkg`，解压到 `scripts/tools/vpk/<version>`；
- 通过 `dotnet exec .../vpk.dll` 执行打包。

因此不需要全局安装 .NET SDK。`scripts/tools/` 已加入 `.gitignore`。

### 版本号

`PackVersion` 默认读取 `backend/src/subtitle_info_collection/__init__.py` 的 `__version__`。发布前同时更新 `backend/pyproject.toml` 和 `frontend/package.json`，保持三处一致。

## 发布到 GitHub Releases

源码仓库与 Releases 使用同一个公开仓库：

```text
https://github.com/jingge007/subtitleInfoCollection
```

不需要再建单独的公开 Releases 仓库。步骤：

1. 更新版本号与 `CHANGELOG.md`。
2. 执行 `.\scripts\build_windows.ps1 -Pack`。
3. 创建 tag，例如 `v0.2.2`。
4. 把 `dist\releases` 下全部文件上传到 Release。
5. 确认 `releases.win.json` 可匿名访问。

客户端使用：

```python
GithubSource("https://github.com/jingge007/subtitleInfoCollection")
```

不内置 Token。若要提高 GitHub API 限额，可在发布端使用 `VELOPACK_GITHUB_TOKEN` 上传，但不要把它放进客户端或仓库。

## 常见问题

### 启动提示缺少 WebView2

安装 Microsoft Edge WebView2 Runtime 后重试。Windows 10/11 通常已预装。

### 前端页面 404

源码运行需要先执行 `cd frontend; npm run build`，或使用 `--dev-url` 指向 Vite。

### 单实例导致窗口没有出现

程序使用命名互斥体；再次启动会尝试激活已有窗口。若旧进程异常残留，先在任务管理器结束 `字幕采集工具.exe`。

### 更新检查失败

- 确认 Release 中存在 `releases.win.json`。
- 确认仓库为公开，且 Release 资产可匿名下载。
- GitHub 匿名 API 可能触发 60 次/小时限制，稍后重试。

### 打包时提示占用

先关闭正在运行的 `字幕采集工具.exe` 和 Playwright 浏览器子进程，再重新执行打包。
