# subtitleInfoCollection

Windows 桌面字幕信息自动采集工具，用于采集电影字幕候选、下载最佳字幕，并解析本地 SRT/ASS 双语字幕文件。

## 功能概览

- 从 TMDb 获取指定年份 Top 电影。
- 从 SubHD、ASSRT、OpenSubtitles 搜索字幕候选。
- 校验字幕格式和语言，优先筛选中英双语 ASS/SRT 字幕。
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

常用配置项：

```dotenv
TMDB_TOKEN=你的 TMDb Bearer Token
ASSRT_TOKEN=你的 ASSRT Token
ASSRT_API_BASE_URL=https://api.assrt.net/v1

OPENSUBTITLES_API_KEY=你的 OpenSubtitles API Key
OPENSUBTITLES_USERNAME=你的 OpenSubtitles 用户名
OPENSUBTITLES_PASSWORD=你的 OpenSubtitles 密码
OPENSUBTITLES_BASE_URL=https://api.opensubtitles.com/api/v1
OPENSUBTITLES_USER_AGENT=subtitleInfoCollection v0.1

SUBTITLE_PROVIDER_PRIORITY=subhd,assrt,opensubtitles
SUBTITLE_PROVIDER_DISABLED=
SUBTITLE_REQUEST_INTERVAL_MS=13000

SUBTITLE_COLLECTION_DATA_DIR=

HTTP_PROXY=
HTTPS_PROXY=
```

说明：

- `TMDB_TOKEN` 是采集电影列表所需的主要配置。
- `ASSRT_TOKEN` 填写后可使用 ASSRT 字幕源。
- `OPENSUBTITLES_API_KEY` 用于搜索，用户名和密码用于下载。
- `SUBTITLE_COLLECTION_DATA_DIR` 留空时默认使用当前用户目录下的 `subtitleInfoCollection` 文件夹。
- 界面设置页只允许修改数据目录，密钥、请求间隔、代理和字幕源策略都从 `.env` 读取。

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
5. 采集过程中可查看进度、结果摘要和日志。
6. 点击“复制日志”可以一键复制当前采集日志。

采集使用的 Token、请求间隔、API 地址、代理和字幕源优先级均来自 `.env`。

### 字幕解析

1. 打开“字幕解析”页。
2. 点击“选择 SRT/ASS 文件”。
3. 选择一个或多个本地字幕文件。
4. 解析完成后，列表会展示完整文件路径、电影信息、原始字幕数量、导出字幕数量和匹配关键词。
5. 解析产物写入 `数据目录/parsed`。

### 历史记录

打开“历史记录”页可查看最近的采集任务，包括状态、年份、Top 数量、开始时间、结束时间和输出目录。

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
      subtitles/
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

打包完成后，程序位于：

```text
dist\字幕采集工具
```

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
