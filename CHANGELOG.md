# 变更记录

## 0.2.2

### 修复

- 修复自动化与本地字幕解析启动时 `TaskContext.update_stats()` 参数不匹配导致的立即失败。
- 修复任务实际数量超过接口总数时进度显示超过 100% 的问题，统一约束为 0–100%。
- 修复运行日志区域无法滚动、长路径和长错误不可见的问题。
- 修复历史记录搜索和分页只处理当前已加载页的问题，改由 SQLite 分页查询。
- 修复任务中心“下载成功”统计口径错误。
- 历史重置和输出清理增加活动任务保护。
- 修复简体字幕中“行、用、解、析、流、程”等常用字被误判为繁体并遭过滤的问题。

### 新增

- 新增窗口置顶按钮，状态在本地记忆。
- 新增可复用日志控制台，支持自动跟随、手动上滚与“回到最新”。

### 优化

- 重新设计浅色工具风视觉系统、字号层级、卡片间距和导航布局。
- 侧边栏品牌块移除，折叠按钮改为侧栏顶部面板图标。
- 字幕源优先级改用六点拖拽把手，优化拖动区域与悬停反馈。
- 顶栏不再重复页面标题，统一由页面标题组件呈现。
- 版本号升级为 `0.2.2`。

## 0.2.0

### 新增

- 使用 pywebview 6.2 + WebView2 替换 PySide6 桌面界面。
- 新增 Vue 3 + TypeScript + Element Plus 前端，9 个页面与可折叠侧边栏。
- 新增 Velopack Portable 自更新：检查、下载进度、立即更新并重启。
- 新增公开 GitHub Releases 匿名更新源。
- 新增 `docs/architecture.md`、`docs/development.md`。

### 变更

- 目录重组为 `frontend/`（前端）与 `backend/`（Python 后端、测试、资源、spec）。
- `.env` 在打包版迁移到 `%APPDATA%\subtitleInfoCollection\.env`，旧 exe 目录配置自动复制迁移。
- WebView2 用户数据固定到 `%LOCALAPPDATA%\subtitleInfoCollection\webview`。
- 配置页支持密钥掩码、分组表单、路径选择与未保存提示。
- 打包脚本改为前端构建 + PyInstaller onedir + Velopack。

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
