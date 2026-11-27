# 变更记录

## 0.2.3

### 修复

- 修复「检查更新」在便携目录原始产物上必然失败的问题：Velopack 需要应用清单 `sq.version` 才能定位程序，原产物目录既无 `Update.exe` 也无清单，会抛 `Could not auto-locate app manifest`。
- 修复自更新后界面全白：pywebview 的 `no-store` 响应头会被 `bottle.static_file` 覆盖，PyInstaller 又把文件时间归零，导致 ETag 恒定、浏览器条件请求始终命中缓存，更新替换程序目录后缓存里的旧 `index.html` 指向已删除的旧资源并返回 404。入口地址现在附带 `index.html` 内容指纹作为缓存键，重新打包或自更新后都会拉到最新页面。

### 变更

- `-Pack` 打包时把 `SubtitleInfoCollection-win-Portable.zip` 展开到便携目录，便携目录变为 `.portable` + `Update.exe` + Velopack 启动器 + `current\` 结构，可正常自更新。
- 后端新增运行形态识别（`source` / `installed` / `portable` / `onedir`），不可更新的形态直接返回 `unsupported` 状态与中文说明，不再抛出 Velopack 英文异常。
- `app.info` 新增 `runMode` 字段，设置页「运行模式」区分安装版、便携解压版、便携目录与源码开发版，并据此禁用「检查更新」按钮。

### 维护

- `outputs/` 会话产物全部移出 Git 跟踪，`.gitignore` 不再放行 `outputs/ui-wireframe`。

## 0.2.2

### 新增

- 使用 pywebview 6.2 + WebView2 替换 PySide6 桌面界面。
- 新增 Vue 3 + TypeScript + Element Plus 前端，9 个页面与可折叠侧边栏。
- 新增 Velopack Portable 自更新：检查、下载进度、立即更新并重启。
- 新增公开 GitHub Releases 匿名更新源。
- 新增窗口置顶按钮，状态在本地记忆。
- 新增可复用日志控制台，支持自动跟随、手动上滚与“回到最新”。
- 新增 `docs/architecture.md`、`docs/development.md`。

### 变更

- 目录重组为 `frontend/`（前端）与 `backend/`（Python 后端、测试、资源、spec）。
- `.env` 在打包版迁移到 `%APPDATA%\subtitleInfoCollection\.env`，旧 exe 目录配置自动复制迁移。
- WebView2 用户数据固定到 `%LOCALAPPDATA%\subtitleInfoCollection\webview`。
- 配置页支持密钥明文展示、分组表单、路径选择与未保存提示。
- 打包脚本改为前端构建 + PyInstaller onedir + Velopack。
- 经典台词页重排为参数置顶、进度与产物并排、日志铺满剩余高度。
- 历史记录列表补齐影片与耗时字段，状态标签中文化。

### 修复

- 修复自动化与本地字幕解析启动时 `TaskContext.update_stats()` 参数不匹配导致的立即失败。
- 修复任务实际数量超过接口总数时进度显示超过 100% 的问题，统一约束为 0–100%。
- 修复运行日志区域无法滚动、长路径和长错误不可见的问题。
- 修复历史记录搜索和分页只处理当前已加载页的问题，改由 SQLite 分页查询。
- 修复任务中心“下载成功”统计口径错误。
- 修复任务中心与历史记录直接展示后端 ISO 时间串的问题，统一换算为本地 `YYYY-MM-DD HH:mm:ss`。
- 历史重置和输出清理增加活动任务保护。
- 修复简体字幕中“行、用、解、析、流、程”等常用字被误判为繁体并遭过滤的问题。

### 优化

- 重新设计浅色工具风视觉系统、字号层级、卡片间距和导航布局。
- 侧边栏移除品牌头部，展开/收起按钮移到应用顶栏左侧，并记忆折叠状态。
- 字幕源优先级改用六点拖拽把手，优化拖动区域与悬停反馈。
- 顶栏不再重复页面标题，统一由页面标题组件呈现。
- 版本号升级为 `0.2.2`。

### 移除

- 移除 PySide6、PySide6-Fluent-Widgets、PySideSix-Frameless-Window 依赖。
- 删除 `gui/` 与 `test_main_window_style.py`。
- 删除仓库中的 `debug.log`、一次性调试脚本与本地工具配置。

### 安全

- PyInstaller 不打包真实 `.env`，构建脚本二次校验。
- 构建产物增加疑似密钥扫描。
- 公开仓库前确认没有提交真实 Token/密码；后续新增配置项必须保持 `.env.example` 密钥为空。

### 破坏性变更

- 启动入口改为 `subtitle_info_collection.main` + pywebview，不再启动 Qt。
- 旧 PySide6 界面相关脚本与测试不再适用。
- 打包产物结构变为 Velopack 发布目录，不再只有单个 PyInstaller 目录。
