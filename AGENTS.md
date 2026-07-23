# subtitleInfoCollection — Agent 约束

本文件约束在本仓库中工作的 AI Agent 与协作者。优先级高于一般性「少注释 / 英文默认」习惯。

## 语言与编码

- 所有回复、分析、计划、进度说明、总结必须使用**简体中文**。
- 代码标识符、命令、文件路径、环境变量名保持原文，不做翻译。
- 项目文本文件（源码、配置、文档、规则）必须使用 **UTF-8**（无 BOM）。
- 读写文本文件必须显式指定 `encoding="utf-8"`，禁止依赖系统默认编码。
- 导出含中文的 JSON 时使用 `ensure_ascii=False`。
- 字幕内容解码复用 `engines/subtitle_engine.py` 的多编码逻辑，禁止在各 adapter 内自行猜测编码。

## 项目定位

Windows 桌面字幕信息采集工具：TMDb 电影榜单、多字幕源搜索下载、本地 SRT/ASS 解析、SQLite 历史，以及 33 台词相关自动化。

主包路径：`src/subtitle_info_collection/`。

## 目录职责

| 路径 | 职责 |
|------|------|
| `orchestrator.py` | 字幕采集主流程编排 |
| `config.py` / `models.py` / `errors.py` / `storage.py` | 配置、领域模型、错误体系、SQLite |
| `local_parser.py` | 本地字幕解析与导出 |
| `adapters/` | 外部 API/站点交互（SubHD、SubDL、ASSRT、OpenSubtitles、TMDb） |
| `engines/` | 无 I/O 或弱 I/O 纯逻辑（解码、打分、解压、OCR、分词） |
| `gui/` | PySide6 界面；后台任务放 `gui/worker.py` |
| `automation/` | 33 台词等自动化，与采集主流程解耦 |
| `tests/` | pytest 测试 |
| `scripts/` | 开发/打包正式脚本；历史补丁脚本勿再扩展 |

调用链：

```text
gui/main_window → gui/worker (QThread + asyncio.run)
  → orchestrator / local_parser / automation
    → adapters + engines + storage
```

## 代码约定

- Python ≥ 3.12；新模块文件顶部使用 `from __future__ import annotations`。
- 包内使用相对导入；测试与外部入口使用 `subtitle_info_collection.*` 绝对导入。
- 命名：类 `PascalCase`，函数/变量 `snake_case`，模块常量 `UPPER_SNAKE_CASE`，私有实现 `_` 前缀。
- 数据类优先 `@dataclass(slots=True)`；类型使用 `X | None`，不用 `Optional[X]`。
- 跨 GUI / Worker / Signal 的 dict 键名使用 camelCase；Python 字段保持 snake_case。
- 文档字符串与用户可见日志/错误消息使用简体中文；仅极少数纯技术辅助函数可用简短英文 docstring。
- 新增或修改的方法/函数上一行用简体中文单行 `//` 风格注释说明业务意图（Python 为 `#`）。
- 遵循 Ruff：`line-length = 100`，`target-version = py312`。

## 错误与分层

- 业务错误抛出 `CollectorError`（或既有专用异常），设置 `error_type`（`ErrorType.*`）与 `provider`。
- 新增错误类型时同步更新 `ERROR_TYPE_LABELS`。
- 未知异常经 `classify_exception()` 归类；整批采集中单条失败写入失败记录，不轻易中断整批。
- GUI 不得直接调用 httpx / Playwright；网络与站点逻辑放 `adapters/`。
- 字幕采集流程变更必须走 `SubtitleCollectionOrchestrator`；GUI 仅通过 Worker 异步调用。
- 新增字幕源须实现 `ProviderAdapter`（`id` / `health` / `search` / `download`），并在注册表中注册。
- 自动化选项与执行器命名：`*AutomationOptions` + `*AutomationRunner`，放在 `automation/`。

## 配置与安全

- 密钥与策略只来自 `.env`；通过 `AppSettings.from_env` / `bootstrap_env_file` 加载。
- **禁止**在代码、测试、文档、提交中硬编码真实 Token / 密码。
- `.env` 禁止提交；`.env.example` 可提交，且每个配置项上方须有中文注释。
- 修改 `.env.example`（新增、删除、重命名或变更默认值/含义）时必须同步：
  1. `config.py` 解析逻辑
  2. `tests/test_config_checks.py` 中的 `ENV_KEYS`
  3. `README.md`「配置 .env」章节（配置项一览与配置说明）
- `README.md` 的环境变量说明以 `.env.example` 为权威来源，禁止只改其一导致文档过期。
- GUI 设置页原则上只改数据目录等有限项；Token、代理、字幕源优先级等仍以 `.env` 为准。

## 测试与运行

- 测试文件：`tests/test_<模块>.py`；函数式 pytest；异步依赖 `pytest-asyncio`。
- 改动 provider / engine / config / automation 时补对应测试。
- **完成/交付改动前必须自动跑相关测试**，不得跳过或仅口头声称通过：
  1. 有明确对应测试文件时：`python -m pytest tests/test_<相关>.py -q`
  2. 改动面广或无单一对应时：`python -m pytest -q`
  3. 失败则修复后重跑，直至通过
  4. 向用户汇报时附带测试结果（通过数或失败摘要）
  5. 仅改文档/规则且不影响可测代码时，可说明「无需跑测」及原因
- 开发启动：`.\scripts\run_dev.ps1`
- 模块启动：`python -m subtitle_info_collection`
- 打包：`.\scripts\build_windows.ps1`
- 依赖安装：`python -m pip install -e ".[dev]"`；OCR 可选 `".[ocr]"`。

## 脚本边界

正式脚本（可维护、可文档化）：

- `scripts/run_dev.ps1`
- `scripts/build_windows.ps1`
- `scripts/copy_playwright_browsers.ps1`
- `scripts/generate_icon.py`

历史补丁/调试脚本（勿再新增同类）：`scripts/fix_*`、`apply_*`、`add_*`、`replace_*`、`check_*`、`find_block.py` 等。新功能直接改源码并补测试。

## Agent 禁止项

- 禁止将真实密钥写入仓库或规则示例中的「可运行值」。
- 禁止在 GUI 层直连外部 HTTP / 浏览器自动化。
- 禁止绕过 Orchestrator 在界面里复制一套采集主流程。
- 禁止新增一次性 `fix_*` / `apply_*` 批量改码脚本作为交付方式。
- 禁止引入与项目不一致的框架或模式（本项目为 PySide6 + asyncio Worker，非 Web 前端）。
- 禁止把个人 Cursor 配置写进本仓库以外路径的要求当作本仓库规范；本仓库的 `AGENTS.md` 与 `.cursor/rules/` 仅服务本项目。
