# subtitleInfoCollection

Windows 桌面字幕信息采集工具：TMDb 电影榜单、多字幕源搜索下载、本地 SRT/ASS 解析、SQLite 历史，以及 33 台词相关自动化。

## 技术栈

| 层 | 技术 |
|---|---|
| 桌面外壳 | Python 3.12+、pywebview 6.2、WebView2 |
| 后端 | Python asyncio、httpx、Playwright、SQLite |
| 前端 | Vue 3、TypeScript、Vite、Element Plus、Pinia、vue-router |
| 打包 | PyInstaller onedir、Velopack Portable |
| 测试 | pytest、Ruff、vue-tsc |

前端与后端分目录维护：

```text
frontend/                 Vue 3 + TypeScript 前端工程
backend/                  Python 后端、测试、资源与打包 spec
  src/subtitle_info_collection/
    adapters/             外部 API/站点交互
    engines/              解码、打分、解压、OCR、分词等纯逻辑
    automation/           33 台词自动化
    web/                  pywebview 外壳、js_api、任务与更新服务
  tests/                  pytest
scripts/                  开发、打包、发布辅助脚本
docs/                     架构与开发文档
outputs/                  会话产物、截图、原型
work/                     临时脚本与中间文件（不入库）
```

`outputs/` 与 `work/` 都属于本地会话产物，不纳入 Git 跟踪。

## 架构

```text
Vue 3 页面
  ↕ window.pywebview.api（请求-响应）
AppApi（web/api.py）
  ↕
web/services（采集 / 解析 / 自动化）
  ↕
orchestrator / local_parser / automation
  ↕
adapters + engines + storage
```

- 业务逻辑只放在 `web/services` 与既有 Python 模块，页面不直连网络。
- 长任务运行在专用 asyncio 线程，页面用 500ms 轮询任务快照与增量日志。
- 日志使用统一滚动控制台，默认跟随最新输出，手动上滚后可一键回到最新。
- 顶栏图钉按钮可切换窗口置顶，状态保存在 WebView 本地存储中。
- 配置、数据库、输出目录都在用户目录，更新只替换程序目录。

更完整的接口与状态机见 `docs/architecture.md`。

## 环境准备

- Windows 10/11 x64
- Python 3.12 或更高版本
- Node.js 20 或更高版本
- Microsoft Edge WebView2 Runtime（Windows 10/11 通常已预装）

首次准备：

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

`requirements.txt` 仅保留兼容入口，依赖以 `backend/pyproject.toml` 为准。

## 本地运行

一键启动 Vite 与 pywebview：

```powershell
.\scripts\run_dev.ps1
```

也可以分开启动：

```powershell
# 终端 1：前端
cd frontend
npm run dev

# 终端 2：桌面壳
.\.venv\Scripts\python.exe -m subtitle_info_collection --dev-url http://127.0.0.1:5173
```

只调试页面时，可直接在浏览器打开 `http://127.0.0.1:5173`。`frontend/src/api/bridge.ts` 检测不到 `window.pywebview` 时会启用 `mock.ts`，9 个页面都能独立操作。

本地验证生产构建：

```powershell
cd frontend
npm run build
cd ..
.\.venv\Scripts\python.exe -m subtitle_info_collection
```

## 配置

- 源码运行：读取仓库根目录 `.env`。
- 打包运行：读取 `%APPDATA%\subtitleInfoCollection\.env`。
- 旧版升级：首次启动若新位置不存在、旧版 exe 目录存在 `.env`，会复制到 APPDATA，旧文件保留。
- 数据目录：默认 `~/subtitleInfoCollection`，可用 `SUBTITLE_COLLECTION_DATA_DIR` 覆盖。
- WebView2 缓存：`%LOCALAPPDATA%\subtitleInfoCollection\webview`。

`.env` 禁止提交，`.env.example` 只保留空值或安全默认值。修改配置项时同步更新 `backend/src/subtitle_info_collection/config.py`、`backend/tests/test_config_checks.py`、`.env.example` 与本 README。

完整配置说明以 `.env.example` 为权威来源。

## 测试

```powershell
# 后端
cd backend
..\.venv\Scripts\python.exe -m pytest -q
..\.venv\Scripts\python.exe -m ruff check src tests
cd ..

# 前端
cd frontend
npm run typecheck
npm run build
cd ..
```

## 打包

只生成便携目录（原始 onedir 产物，不支持自更新）：

```powershell
.\scripts\build_windows.ps1
```

输出：`dist\字幕采集工具\字幕采集工具.exe`。

生成 Velopack 发布资产，并把便携目录替换为可自更新的 Velopack 便携结构：

```powershell
.\scripts\build_windows.ps1 -Pack
```

输出目录 `dist\releases`，包含：

- `releases.win.json`
- `SubtitleInfoCollection-<version>-full.nupkg`
- `SubtitleInfoCollection-win-Setup.exe`
- `SubtitleInfoCollection-win-Portable.zip`

打包脚本会：

1. 安装后端与前端依赖；
2. `npm ci` + `npm run build`；
3. 运行 PyInstaller onedir；
4. 复制并精简 Playwright 无头浏览器；
5. 校验产物不含 `.env` 与疑似密钥；
6. `-Pack` 时自动准备本地 .NET 8 运行时与 `vpk`，生成 Velopack 资产；
7. `-Pack` 时把 `SubtitleInfoCollection-win-Portable.zip` 展开到便携目录，便携目录变为 `.portable` + `Update.exe` + 启动器 + `current\` 结构。

`vpk` 不需要全局 .NET SDK；首次打包会把运行时和工具下载到 `scripts/tools/`（该目录不入库）。

## 运行形态与自更新

自更新依赖 Velopack 的应用清单 `sq.version`，只有被 Velopack 注册过的运行形态才具备该能力：

| 运行形态 | 目录结构 | 自更新 |
|---------|---------|--------|
| 安装版 | `Setup.exe` 安装到 `%LOCALAPPDATA%\Velopack\SubtitleInfoCollection` | 支持 |
| 便携解压版 | 解压 `SubtitleInfoCollection-win-Portable.zip`，运行顶层启动器 | 支持 |
| 便携目录原始产物 | `build_windows.ps1`（不带 `-Pack`）生成的 onedir 目录 | 不支持 |
| 源码开发版 | `.\scripts\run_dev.ps1` | 不支持 |

程序会在「设置与维护 → 运行模式」显示当前形态；形态不支持自更新时，「检查更新」按钮会禁用并给出中文说明，不会再抛出 Velopack 的英文异常。

## 更新与发布

客户端使用匿名 `GithubSource` 读取公开仓库 Releases：

```text
https://github.com/jingge007/subtitleInfoCollection
```

源码仓库已公开，因此不需要再建单独的公开 Releases 仓库。发布时：

1. 修改 `backend/src/subtitle_info_collection/__init__.py` 与 `backend/pyproject.toml` 的版本号；
2. 更新 `CHANGELOG.md`；
3. 执行 `.\scripts\build_windows.ps1 -Pack`；
4. 创建与版本一致的 tag（例如 `v0.2.3`）；
5. 把 `dist\releases` 中全部资产上传到该 Release；
6. 确认 `releases.win.json` 可匿名访问。

注意：

- GitHub 匿名 API 有每小时 60 次的单 IP 限制，更新检查失败时应提示稍后重试。
- 当前未配置代码签名，Setup/Portable 首次运行可能触发 SmartScreen 提示。
- `VELOPACK_GITHUB_TOKEN` 只用于本地发布或 CI 上传，不要写入仓库、`.env.example` 或客户端。

## 公开仓库安全

本项目已公开，公开范围包括完整 Git 历史。当前仓库没有提交真实 `.env`，打包 spec 只包含 `.env.example`，构建脚本会再次扫描产物。

仍需注意：

- 如果曾经在聊天、日志、截图或旧提交中暴露过 Token/密码，应在对应平台轮换。
- 不要把真实 `.env`、Cookie、抓包结果、账号密码放进 `outputs/`、`work/` 或提交历史。
- `outputs/` 属于会话产物，`.gitignore` 已全量忽略，不要提交截图与原型文件。
- 新增配置项时，密钥键在 `.env.example` 中必须保持空值，并补充中文说明。

## 相关文档

- `docs/architecture.md`：分层、js_api 契约、任务状态机、数据路径
- `docs/development.md`：本地开发、调试、测试、打包、发布
- `CHANGELOG.md`：版本变更
- `AGENTS.md`：仓库协作约束
