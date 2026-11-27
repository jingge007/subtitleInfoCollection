# subtitleInfoCollection — Agent 约束

本文件约束在本仓库中工作的 AI Agent 与协作者。优先级高于一般性「少注释 / 英文默认」习惯。

## 语言与编码

- 所有回复、分析、计划、进度说明、总结必须使用**简体中文**。
- 代码标识符、命令、文件路径、环境变量名保持原文，不做翻译。
- 项目文本文件必须使用 **UTF-8 无 BOM**。
- **例外**：`scripts/*.ps1` 必须使用 **UTF-8 with BOM**。Windows PowerShell 5.1 在无 BOM 时会按系统 ANSI（中文环境多为 GBK）解析，含中文的脚本会出现引号错位与 `ParserError`。
- 读写文本文件必须显式指定 `encoding="utf-8"`，禁止依赖系统默认编码。
- 导出含中文的 JSON 时使用 `ensure_ascii=False`。
- 字幕内容解码复用 `engines/subtitle_engine.py` 的多编码逻辑，禁止在各 adapter 内自行猜测编码。

## 项目定位

Windows 桌面字幕信息采集工具：TMDb 电影榜单、多字幕源搜索下载、本地 SRT/ASS 解析、SQLite 历史，以及 33 台词相关自动化。

当前表现层为 **pywebview + Vue 3**，不再使用 PySide6。

## 目录职责

| 路径 | 职责 |
|------|------|
| `frontend/` | Vue 3 + TypeScript + Vite + Element Plus + Pinia 前端 |
| `frontend/src/api/bridge.ts` | `window.pywebview.api` 封装；浏览器环境走 `mock.ts` |
| `frontend/src/views/` | 9 个页面；只负责展示与交互 |
| `frontend/src/stores/` | Pinia：`task` / `config` / `app` |
| `backend/src/subtitle_info_collection/` | Python 主包 |
| `backend/src/subtitle_info_collection/web/` | pywebview 外壳、`AppApi`、任务运行时、更新服务 |
| `backend/src/subtitle_info_collection/web/services/` | 采集、解析、自动化服务层 |
| `backend/src/subtitle_info_collection/adapters/` | 外部 API/站点交互 |
| `backend/src/subtitle_info_collection/engines/` | 无 I/O 或弱 I/O 纯逻辑（解码、打分、解压、OCR、分词） |
| `backend/src/subtitle_info_collection/automation/` | 33 台词等自动化 |
| `backend/tests/` | pytest |
| `backend/字幕采集工具.spec` | PyInstaller 配置 |
| `scripts/` | 开发/打包正式脚本；历史补丁脚本勿再扩展 |
| `docs/` | 架构与开发文档 |
| `outputs/` | 会话产物、截图、原型 |
| `work/` | 临时脚本与中间文件，不入库 |

调用链：

```text
Vue 页面
  → frontend/src/api/bridge.ts
    → AppApi（web/api.py）
      → web/services
        → orchestrator / local_parser / automation
          → adapters + engines + storage
```

## 代码约定

- Python ≥ 3.12；新模块文件顶部使用 `from __future__ import annotations`。
- 包内使用相对导入；测试与外部入口使用 `subtitle_info_collection.*` 绝对导入。
- 命名：类 `PascalCase`，函数/变量 `snake_case`，模块常量 `UPPER_SNAKE_CASE`，私有实现 `_` 前缀。
- 数据类优先 `@dataclass(slots=True)`；类型使用 `X | None`，不用 `Optional[X]`。
- 跨 js_api / 前端 / 任务快照的 dict 键名使用 camelCase；Python 字段保持 snake_case。
- 文档字符串与用户可见日志/错误消息使用简体中文；仅极少数纯技术辅助函数可用简短英文 docstring。
- 新增或修改的方法/函数上一行用简体中文单行注释说明业务意图。
- 遵循 Ruff：`line-length = 100`，`target-version = py312`。
- 前端 TypeScript 保持严格类型；不要在视图里复制后端业务逻辑。
- 前端构建产物 `frontend/dist/` 不入库；后端 `__pycache__`、`.pytest_cache` 不入库。

## 错误与分层

- 业务错误抛出 `CollectorError`（或既有专用异常），设置 `error_type`（`ErrorType.*`）与 `provider`。
- 新增错误类型时同步更新 `ERROR_TYPE_LABELS`。
- 未知异常经 `classify_exception()` 归类；整批采集中单条失败写入失败记录，不轻易中断整批。
- 页面与 `AppApi` 不得直接调用 httpx / Playwright；网络与站点逻辑放 `adapters/`。
- 字幕采集流程变更必须走 `SubtitleCollectionOrchestrator`；`web/services` 只做参数转换与任务包装。
- 新增字幕源须实现 `ProviderAdapter`（`id` / `health` / `search` / `download`），并在注册表中注册。
- 自动化选项与执行器命名：`*AutomationOptions` + `*AutomationRunner`，放在 `automation/`。
- `web/api.py` 只做参数校验、camelCase 转换与服务调用，不承载业务规则。
- 新增 js_api 方法时同步更新 `frontend/src/api/bridge.ts` 与 `docs/architecture.md`。
- 窗口置顶统一使用 `AppApi.app_set_always_on_top`，前端状态只保存在 `localStorage["ui.alwaysOnTop"]`，不要写入 `.env`。
- 页面日志统一使用 `frontend/src/components/LogConsole.vue`，不要另写固定 `overflow: hidden` 的日志容器。
- 页面标题统一由 `PageHeader` 呈现，顶栏不要重复页面标题。

## 配置与安全

- 源码运行读取仓库根 `.env`；打包运行读取 `%APPDATA%\subtitleInfoCollection\.env`。
- 密钥与策略只来自 `.env`；通过 `AppSettings.from_env` / `bootstrap_env_file` 加载。
- **禁止**在代码、测试、文档、提交、截图、日志中硬编码真实 Token / 密码 / Cookie。
- `.env` 禁止提交；`.env.example` 可提交，且每个配置项上方须有中文注释；密钥键保持空值。
- 修改 `.env.example`（新增、删除、重命名或变更默认值/含义）时必须同步：
  1. `backend/src/subtitle_info_collection/config.py` 解析逻辑与 `ENV_FIELD_META`
  2. `backend/tests/test_config_checks.py` 中的 `ENV_KEYS`
  3. `README.md` 与 `docs/architecture.md` 相关说明
- 打包 spec 只能包含 `.env.example`，不能包含真实 `.env`；`build_windows.ps1` 会再次校验并扫描疑似密钥。
- 仓库已公开，Git 历史同样公开；若发现历史泄露，先轮换凭证，再评估是否清理历史。
- 更新源使用公开仓库 Releases + 匿名 `GithubSource`；发布 Token 只走环境变量，不写入客户端。

## 测试与运行

- 测试文件：`backend/tests/test_<模块>.py`；函数式 pytest；异步依赖 `pytest-asyncio`。
- 改动 provider / engine / config / automation 时补对应测试。
- **完成/交付改动前必须自动跑相关测试**，不得跳过或仅口头声称通过：
  1. 有明确对应测试文件时：`cd backend; ..\.venv\Scripts\python.exe -m pytest tests/test_<相关>.py -q`
  2. 改动面广或无单一对应时：`cd backend; ..\.venv\Scripts\python.exe -m pytest -q`
  3. 前端改动：`cd frontend; npm run typecheck; npm run build`
  4. 失败则修复后重跑，直至通过
  5. 向用户汇报时附带测试结果（通过数或失败摘要）
- 开发启动：`.\scripts\run_dev.ps1`
- 模块启动：`.\.venv\Scripts\python.exe -m subtitle_info_collection`
- 打包：`.\scripts\build_windows.ps1`；Velopack：`.\scripts\build_windows.ps1 -Pack`
- 依赖安装：`python -m pip install -e "backend[dev]"`；OCR 可选 `backend[ocr]`。

## 脚本边界

正式脚本（可维护、可文档化）：

- `scripts/run_dev.ps1`
- `scripts/build_windows.ps1`
- `scripts/copy_playwright_browsers.ps1`
- `scripts/generate_icon.py`

历史补丁/调试脚本（勿再新增同类）：`scripts/fix_*`、`apply_*`、`add_*`、`replace_*`、`check_*`、`find_block.py` 等。新功能直接改源码并补测试。

`scripts/tools/` 用于下载 vpk/.NET 运行时，已忽略，不入库。

## Agent 禁止项

- 禁止将真实密钥写入仓库或规则示例中的「可运行值」。
- 禁止重新引入 PySide6/Qt 作为表现层，除非用户明确要求回退。
- 禁止在 Vue 页面或 `AppApi` 中直连外部 HTTP / 浏览器自动化。
- 禁止绕过 Orchestrator 在服务层复制一套采集主流程。
- 禁止新增一次性 `fix_*` / `apply_*` 批量改码脚本作为交付方式。
- 禁止提交 `frontend/dist/`、`frontend/node_modules/`、`scripts/tools/`、`work/`、真实 `.env`。
- 禁止把个人 Cursor 配置写进本仓库以外路径的要求当作本仓库规范；本仓库的 `AGENTS.md` 与 `.cursor/rules/` 仅服务本项目。

## 分支流程

- 改代码前先执行 `git status`，确认当前分支和工作区状态。
- 当前在默认分支且工作区干净：从默认分支创建 `codex/<简短英文主题>` 分支后再改。
- 已在 `codex/*` 分支：分支主题与当前任务一致则继续，不重复创建；不一致则先报告。
- 当前在默认分支但有未提交改动：停止并报告文件清单，不擅自 `stash`、`checkout`、丢弃或覆盖。
- 在分支上按逻辑单元提交，提交信息使用 Conventional Commits（`feat:`、`fix:`、`chore:`、`style:` 等）。
- 验证通过后：切回默认分支 → `git merge --no-ff <分支> -m "merge: <中文说明>"` → `git branch -d <分支>`。
- 验证失败或合并冲突：保留分支并停止，报告失败项/冲突文件，不合并、不删除、不强行解决。
- 不自动 `git push`；需要推送时等用户明确要求。
