# subtitleInfoCollection

Windows 桌面字幕信息自动采集工具，用于采集电影字幕候选、下载最佳字幕，并解析本地 SRT/ASS 双语字幕文件。

## 功能概览

- 从 TMDb 获取指定年份 Top 电影。
- 从 SubHD、SubDL、ASSRT、OpenSubtitles 搜索字幕候选。
- 校验字幕格式、语言和文件大小，优先筛选真实文件大于 100KB 的中英双语 ASS/SRT 字幕。
- 下载最佳字幕并打包为 ZIP。
- 解析本地 SRT/ASS 文件，导出电影 JSON 和字幕 JSON。
- 使用 SQLite 保存采集历史和缓存。
- 提供 PySide6 桌面界面，支持复制日志、清空历史、删除采集输出文件。

## 环境准备

推荐使用 Python 3.12 或更高版本。

```powershell
cd D:\资料\subtitleInfoCollection
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
python -m playwright install chromium
copy .env.example .env
```

也可以直接运行开发脚本，它会自动创建虚拟环境并安装依赖：

```powershell
.\scripts\run_dev.ps1
```

## 配置 .env

首次运行前，把 `.env.example` 复制为 `.env`，然后只在本机 `.env` 中填写真实密钥。  
配置项以仓库根目录 `.env.example` 为准；修改示例文件时须同步更新本节说明。

### 配置项一览

```dotenv
# TMDb / 字幕源
TMDB_TOKEN=
ASSRT_TOKEN=
ASSRT_API_BASE_URL=https://api.assrt.net/v1
SUBDL_API_KEY=
SUBDL_BASE_URL=https://api.subdl.com/api/v1
SUBDL_DOWNLOAD_BASE_URL=https://dl.subdl.com
SUBDL_LANGUAGES=ZH,EN
SUBDL_INCLUDE_TRADITIONAL=false
OPENSUBTITLES_API_KEY=
OPENSUBTITLES_USERNAME=
OPENSUBTITLES_PASSWORD=
OPENSUBTITLES_BASE_URL=https://api.opensubtitles.com/api/v1
OPENSUBTITLES_USER_AGENT=subtitleInfoCollection v0.1

# 33 台词自动化 / 翻译
TODAYS_LINES_USERNAME=
TODAYS_LINES_PASSWORD=
TODAYS_LINES_TOKEN=
TODAYS_LINES_TOKEN_TIME=
BAIDU_TRANSLATE_APP_ID=
BAIDU_TRANSLATE_SECRET=

# 采集策略与 SubHD
SUBTITLE_PROVIDER_PRIORITY=subhd,subdl,assrt,opensubtitles
SUBTITLE_PROVIDER_DISABLED=
SUBTITLE_REQUEST_INTERVAL_MS=13000
SUBTITLE_MOVIE_CONCURRENCY=2
SUBTITLE_MIN_BILINGUAL_RATIO=0.70
SUBHD_CAPTCHA_OCR_ENABLED=true
SUBHD_CAPTCHA_AUTO_SUBMIT_MIN_CONFIDENCE=0.85
SUBHD_CAPTCHA_OCR_MAX_ATTEMPTS=
SUBHD_SEARCH_TIMEOUT=120
PROVIDER_SEARCH_TIMEOUT=90
CAPTCHA_SOUND_ENABLED=true

# 目录与代理
SUBTITLE_COLLECTION_PACKAGE_DIST_DIR=
SUBTITLE_COLLECTION_DATA_DIR=
HTTP_PROXY=
HTTPS_PROXY=
```

### 配置说明

- `TMDB_TOKEN`：TMDb Bearer Token，用于指定年份电影榜单采集，也用于本地字幕解析匹配电影信息；留空则电影榜单采集不可用。
- `ASSRT_TOKEN`：ASSRT API 令牌；填写后启用 ASSRT 搜索和下载，留空判定为未配置。
- `ASSRT_API_BASE_URL`：ASSRT API 基础地址；通常保持默认，仅官方地址变更或走代理网关时修改。
- `SUBDL_API_KEY`：SubDL 官方 API 密钥；填写后启用 SubDL，留空判定为未配置。
- `SUBDL_BASE_URL` / `SUBDL_DOWNLOAD_BASE_URL`：SubDL 搜索与下载基础地址；通常保持默认。
- `SUBDL_LANGUAGES`：SubDL 搜索语言，逗号分隔；默认 `ZH,EN` 扩大中英召回，最终仍以下载后双语校验为准。
- `SUBDL_INCLUDE_TRADITIONAL`：是否允许 SubDL 搜索繁体候选；默认 `false`。
- `OPENSUBTITLES_API_KEY`：OpenSubtitles 搜索用 API Key；留空判定为未配置。
- `OPENSUBTITLES_USERNAME` / `OPENSUBTITLES_PASSWORD`：OpenSubtitles 下载所需账号密码。
- `OPENSUBTITLES_BASE_URL` / `OPENSUBTITLES_USER_AGENT`：API 地址与 User-Agent；User-Agent 建议包含应用名与版本。
- `TODAYS_LINES_USERNAME` / `TODAYS_LINES_PASSWORD`：33 台词自动化登录账号密码；仅自动化功能使用，本地 token 不可用时才用密码登录。
- `TODAYS_LINES_TOKEN` / `TODAYS_LINES_TOKEN_TIME`：登录成功后由程序自动写入的缓存 token 与时间戳；手工可留空。
- `BAIDU_TRANSLATE_APP_ID` / `BAIDU_TRANSLATE_SECRET`：百度翻译开放平台凭证，用于自动化脚本补全英文字幕；留空则跳过英文补全。
- `SUBTITLE_PROVIDER_PRIORITY`：字幕源搜索优先级，逗号分隔，支持 `subhd`、`subdl`、`assrt`、`opensubtitles`，越靠前越优先。
- `SUBTITLE_PROVIDER_DISABLED`：禁用的字幕源，逗号分隔；留空表示不额外禁用。
- `SUBTITLE_REQUEST_INTERVAL_MS`：字幕源请求间隔（毫秒），降低限流/验证码概率；过低值会被程序限制到安全下限（不低于 12000）。
- `SUBTITLE_MOVIE_CONCURRENCY`：同时处理的电影数（1～4）；默认 `2` 为有限并发，`1` 为串行（旧行为）。
- `SUBTITLE_MIN_BILINGUAL_RATIO`：下载后双语条目最低占比（0.0–1.0）；`0.70` 表示至少 70% 有效条目须同时含简体中文与英文。
- `SUBHD_CAPTCHA_OCR_ENABLED`：是否启用 SubHD 验证码辅助识别；`true` 尝试自动识别，`false` 需人工输入。图片 OCR 需本机安装对应 OCR 依赖与 Tesseract。
- `SUBHD_CAPTCHA_AUTO_SUBMIT_MIN_CONFIDENCE`：验证码自动提交最低置信度（0.0–1.0）；低于该值等待人工确认。
- `SUBHD_CAPTCHA_OCR_MAX_ATTEMPTS`：OCR 最大尝试次数；留空则按预处理 × PSM × 白名单组合自动计算（通常约 30–50 次）。
- `SUBHD_SEARCH_TIMEOUT`：SubHD 单次搜索超时（秒）；建议不低于 60，留空默认 120。
- `PROVIDER_SEARCH_TIMEOUT`：非 SubHD 源（SubDL、ASSRT、OpenSubtitles）单次搜索超时（秒）；留空默认 90。
- `CAPTCHA_SOUND_ENABLED`：验证码弹出时是否播放系统提示音；即使静默仍会托盘通知与任务栏闪烁。
- `SUBTITLE_COLLECTION_PACKAGE_DIST_DIR`：Windows 打包产物输出目录，只影响 `scripts/build_windows.ps1` / `字幕采集工具.spec`；留空默认 `项目目录/dist/字幕采集工具`。可填最终目录（如 `D:\软件\字幕采集工具`），或父级目录（如 `D:\软件`，则输出为 `D:\软件\字幕采集工具`）；相对路径按项目根解析。
- `SUBTITLE_COLLECTION_DATA_DIR`：运行数据目录（字幕输出、解析结果、本地数据库）；留空默认使用当前用户目录下的 `subtitleInfoCollection`。
- `HTTP_PROXY` / `HTTPS_PROXY`：HTTP/HTTPS 代理，例如 `http://127.0.0.1:7890`；留空表示不使用代理。

界面设置页只允许修改数据目录；密钥、请求间隔、代理和字幕源策略都从 `.env` 读取。  
开发运行：`.\scripts\run_dev.ps1`。打包：`.\scripts\build_windows.ps1`（会读取 `SUBTITLE_COLLECTION_PACKAGE_DIST_DIR`）。
## 启动应用

方式一：开发脚本启动。

```powershell
.\scripts\run_dev.ps1
```

方式二：手动启动。

```powershell
.\.venv\Scripts\Activate.ps1
python -m subtitle_info_collection
```

## 界面操作

### 采集任务

1. 打开“采集任务”页。
2. 设置年份和 Top 数量。
3. 选择字幕源，按需开启“源兜底”和“下载字幕”。
4. 点击“开始采集”。
5. 下载校验会检查解压后的真实字幕文件，低于 100KB 的 ASS/SRT 会判定为无效电影字幕。
6. 采集过程中可查看进度、结果摘要和日志。
7. 点击“复制日志”可以一键复制当前采集日志。

采集使用的 Token、请求间隔、API 地址、代理和字幕源优先级均来自 `.env`。

### 字幕解析

1. 打开“字幕解析”页。
2. 点击“选择 SRT/ASS 文件”。
3. 选择一个或多个本地字幕文件，文件必须是 `.srt` 或 `.ass`，且真实文件大小不低于 100KB。
4. 解析完成后，列表会展示完整文件路径、电影信息、原始字幕数量、导出字幕数量和匹配关键词。
5. 解析产物写入 `数据目录/parsed`。

### 历史记录

打开“历史记录”页可查看最近的采集任务，包括年份、Top 数量、开始时间、结束时间和输出目录，时间按 `YYYY-MM-DD HH:mm:ss` 展示。

### 设置和维护

打开“设置”页可以：

- 修改数据目录并保存到 `.env`。
- 点击“重置历史”清空采集历史记录，保留输出文件。
- 点击“删除输出文件”删除 `数据目录/output`，并同时清空采集历史记录。

“删除输出文件”不会删除 `数据目录/parsed`，也不会删除数据库文件、电影缓存或字幕候选缓存。

## 输出目录

采集任务每次都会在数据目录下创建独立输出目录：

```text
数据目录/
  subtitle_info_collection.sqlite3
  output/
    YYYYMMDDHHMMSS-YYYY-topN/
      *.srt
      *.ass
  parsed/
    YYYYMMDD-HHMMSS-movies.json
    YYYYMMDD-HHMMSS-subtitles.json
```

## 测试

```powershell
.\.venv\Scripts\Activate.ps1
pytest
```

如果没有激活虚拟环境，也可以直接使用虚拟环境中的 Python：

```powershell
.\.venv\Scripts\python.exe -m pytest
```

## Windows 打包

运行打包脚本：

```powershell
.\scripts\build_windows.ps1
```

脚本会执行：

- 创建 `.venv`，如果不存在。
- 升级 pip。
- 安装项目和开发依赖。
- 安装 Playwright Chromium。
- 使用 PyInstaller 生成 Windows 桌面程序。

打包完成后，默认程序位于：

```text
dist\字幕采集工具
```

可通过 `.env` 中的 `SUBTITLE_COLLECTION_PACKAGE_DIST_DIR` 指定打包输出目录（不影响运行数据目录）。

如果需要指定 Python 命令：

```powershell
.\scripts\build_windows.ps1 -Python "py -3.12"
```
## 常见问题

### 无法采集电影列表

检查 `.env` 中的 `TMDB_TOKEN` 是否填写，并确认网络可以访问 TMDb。

### 某个字幕源没有结果

检查对应 Token 或账号配置。也可以通过 `SUBTITLE_PROVIDER_DISABLED` 临时禁用某个字幕源，例如：

```dotenv
SUBTITLE_PROVIDER_DISABLED=opensubtitles
```

### 下载或搜索太频繁

调大 `.env` 中的请求间隔：

```dotenv
SUBTITLE_REQUEST_INTERVAL_MS=20000
```

### 输出文件越来越多

在“设置”页点击“删除输出文件”。该操作会删除 `数据目录/output` 并清空采集历史，但会保留本地解析产物和数据库缓存。
