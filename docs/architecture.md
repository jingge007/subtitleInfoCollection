# 架构说明

## 目标

把原有 Python 采集/解析/自动化能力保留为后端，只替换表现层：

- 桌面外壳：pywebview 6.2 + WebView2。
- 前端：Vue 3 + TypeScript + Vite + Element Plus + Pinia + vue-router。
- 打包：PyInstaller onedir + Velopack Portable。

不引入 FastAPI/uvicorn，避免端口占用、防火墙弹窗和额外进程。

## 分层

```text
frontend/src/views/*.vue
  ↓ 调用 api（bridge.ts）
window.pywebview.api
  ↓
backend/src/subtitle_info_collection/web/api.py（AppApi）
  ↓
web/services/*（参数校验、任务上下文、结果整理）
  ↓
orchestrator / local_parser / automation
  ↓
adapters + engines + storage
```

职责边界：

- 页面只负责展示、表单与交互，不直接发 HTTP、不启动 Playwright。
- `web/api.py` 只做参数校验、camelCase 转换、调用服务、返回前端结构。
- `web/services/` 负责把页面参数转成领域调用，并写入任务进度/日志。
- `orchestrator`、`adapters`、`engines`、`storage` 保持原有领域职责。
- 新增字幕源仍实现 `ProviderAdapter` 并注册，不在页面里写站点逻辑。

## 目录

```text
frontend/
  src/api/bridge.ts       js_api 封装；浏览器环境自动走 mock
  src/api/mock.ts         9 页浏览器 mock
  src/components/         AppShell、SideBar、LogConsole 等
  src/composables/        任务轮询等组合式逻辑
  src/stores/             Pinia：task/config/app
  src/views/              9 个页面

backend/
  src/subtitle_info_collection/
    web/api.py            js_api 门面
    web/shell.py          pywebview 窗口、单实例、关闭确认
    web/tasks.py          任务线程、状态、日志环、验证码等待
    web/updater.py        Velopack 检查/下载/重启
    web/services/         采集、解析、自动化服务
  tests/                  pytest
  字幕采集工具.spec        PyInstaller 配置
```

## js_api 契约

前端使用点号接口名，`bridge.ts` 转为 Python snake_case。

| 前端接口 | Python 方法 | 返回 |
|---|---|---|
| `app.info` | `app_info` | 版本、数据目录、配置路径、程序目录、运行形态 `runMode` |
| `app.checkUpdate` | `app_check_update` | 更新状态 |
| `app.updateState` | `app_update_state` | 当前更新状态快照 |
| `app.downloadUpdate` | `app_download_update` | 无 |
| `app.applyUpdateAndRestart` | `app_apply_update_and_restart` | 无 |
| `app.setAlwaysOnTop` | `app_set_always_on_top` | 是否成功启用窗口置顶 |
| `config.list` | `config_list` | 分组配置（含 secret 标记） |
| `config.save` | `config_save` | 无 |
| `collector.start` | `collector_start` | `true` |
| `collector.pause` / `resume` / `abort` | `collector_pause` / `collector_resume` / `collector_abort` | 无 |
| `collector.state` | `collector_state` | 任务快照 + 增量日志 |
| `collector.submitVerification` | `collector_submit_verification` | 是否已接收 |
| `collector.refreshCaptcha` | `collector_refresh_captcha` | 是否已请求刷新 |
| `parser.pickFiles` | `parser_pick_files` | 文件路径数组 |
| `parser.inspectFiles` | `parser_inspect_files` | 文件校验结果 |
| `parser.start` / `parser.state` / `parser.abort` | `parser_start` / `parser_state` / `parser_abort` | 任务控制 |
| `automation.startTodays` / `startClassic` | `automation_start_todays` / `automation_start_classic` | `true` |
| `automation.state` / `automation.abort` | `automation_state` / `automation_abort` | 任务控制 |
| `history.list` / `history.reset` | `history_list` / `history_reset` | 历史分页/清空 |
| `shell.pickDirectory` | `shell_pick_directory` | 目录或 `null` |
| `shell.openPath` | `shell_open_path` | `true` |
| `shell.deleteOutputs` | `shell_delete_outputs` | `true` |

`TaskState` 字段：

```text
status current total currentItem stats error outputPaths
logs nextLogCursor verification startedAt finishedAt
```

日志采用游标增量：前端保存 `nextLogCursor`，下一次请求把游标传回；后端只返回该游标之后的日志，环形缓冲最多 2000 条。

进度字段约束：`current >= 0`；`total == 0` 表示未知总数；`current > total` 时后端自动将 `total` 抬升到 `current`，前端再把百分比夹紧到 `0–100`。

窗口置顶由 `AppApi.app_set_always_on_top` 调用 pywebview 的 `Window.on_top`，前端使用 `localStorage["ui.alwaysOnTop"]` 记忆状态。

## 任务状态机

采集：

```text
idle → starting → running → pausing → paused → running
                    ↓
                 aborting → aborted
                    ↓
                 finished / error
```

解析 / 自动化：

```text
idle → starting → running → finished / error / aborted
```

更新：

```text
idle → checking → latest
              ↘ available → downloading(%) → ready → restarting
              ↘ error
```

验证码：

- 后端 `request_verification` 最多等待 300 秒。
- 前端提交验证码或请求刷新；超时后跳过当前验证码。

## 数据与配置路径

| 内容 | 源码运行 | 打包运行 |
|---|---|---|
| `.env` | 仓库根目录 | `%APPDATA%\subtitleInfoCollection\.env` |
| SQLite | `SUBTITLE_COLLECTION_DATA_DIR` 或 `~/subtitleInfoCollection` | 同左 |
| 采集输出 | `<数据目录>/output` | 同左 |
| 解析输出 | `<数据目录>/parsed` | 同左 |
| WebView2 缓存 | `%LOCALAPPDATA%\subtitleInfoCollection\webview` | 同左 |
| 崩溃日志 | `%APPDATA%\subtitleInfoCollection\crash.log` | 同左 |

更新只替换程序目录；`.env`、数据库、输出目录、WebView2 缓存都在用户目录，不受影响。

## 更新流程

1. `main.py` 在创建窗口前执行 `velopack.App().run()`。
2. `web/updater.py` 的 `detect_run_mode()` 识别运行形态：`source`（源码）、`installed`（安装版）、`portable`（便携解压版）、`onedir`（便携目录原始产物）。
3. 设置页调用 `app.checkUpdate`；形态不支持自更新时直接返回 `unsupported` 状态与中文说明，不请求 GitHub。
4. `UpdateService` 通过 `GithubSource(REPOSITORY_URL)` 匿名读取公开 Releases。
5. 有新版本时前端显示版本号、更新说明与「立即更新」。
6. 下载完成状态为 `ready`，用户点击重启安装。
7. Velopack 替换程序目录并重启。

匿名 GitHub API 有每小时 60 次的单 IP 限制；检查失败时界面显示错误，不影响本地功能。

`runMode` 由 `app.info` 返回，前端在「设置与维护 → 运行模式」展示，并据此禁用「检查更新」按钮。

## 打包结构

```text
dist/
  字幕采集工具/                便携目录
    .portable                  便携解压版标记（-Pack 时才有）
    Update.exe                 Velopack 更新器（-Pack 时才有）
    字幕采集工具.exe             Velopack 启动器（-Pack 时才有）
    current/                   实际程序目录（-Pack 时才有）
      字幕采集工具.exe
      sq.version               Velopack 应用清单
      _internal/
        webui/                 frontend/dist
        assets/                head_logo.ico
        .env.example           配置模板
        webview/               pywebview + WebView2 DLL
        playwright/            Playwright driver + 无头浏览器
  releases/                  Velopack 资产
```

不带 `-Pack` 时便携目录只有 PyInstaller onedir 原始产物，没有 `sq.version`，因此不具备自更新能力。

PyInstaller spec 明确不打包真实 `.env`；构建脚本会再次检查产物并扫描疑似密钥。
