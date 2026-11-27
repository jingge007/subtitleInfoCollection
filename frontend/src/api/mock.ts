import type {
  AppInfo,
  ConfigGroup,
  HistoryPage,
  ParserFile,
  TaskState,
  UpdateState,
} from './bridge'

const APP_INFO: AppInfo = {
  version: '0.2.3',
  dataDir: 'C:\\Users\\huangjing\\subtitleInfoCollection',
  envPath: '%APPDATA%\\subtitleInfoCollection\\.env',
  programDir: '%LocalAppData%\\SubtitleInfoCollection\\current',
  platform: 'win32',
  frozen: false,
  runMode: 'source',
}

let updateState: UpdateState = {
  status: 'latest',
  available: false,
  currentVersion: '0.2.3',
  latestVersion: '0.2.3',
  notes: '',
  progress: 0,
  error: '',
}

const CONFIG_GROUPS: ConfigGroup[] = [
  {
    key: 'secrets',
    label: '密钥与账号',
    fields: [
      { key: 'TMDB_TOKEN', label: 'TMDb Token', group: 'secrets', widget: 'secret', description: '电影榜单采集与本地字幕匹配。', value: 'demo-tmdb-token', secret: true },
      { key: 'ASSRT_TOKEN', label: 'ASSRT Token', group: 'secrets', widget: 'secret', description: 'ASSRT 字幕源令牌。', value: '', secret: true },
      { key: 'SUBDL_API_KEY', label: 'SubDL API Key', group: 'secrets', widget: 'secret', description: 'SubDL 官方 API 密钥。', value: '', secret: true },
      { key: 'OPENSUBTITLES_API_KEY', label: 'OpenSubtitles API Key', group: 'secrets', widget: 'secret', description: 'OpenSubtitles REST API 密钥。', value: '', secret: true },
      { key: 'OPENSUBTITLES_USERNAME', label: 'OpenSubtitles 用户名', group: 'secrets', widget: 'text', description: '下载字幕时与密码一起使用。', value: '', secret: false },
      { key: 'OPENSUBTITLES_PASSWORD', label: 'OpenSubtitles 密码', group: 'secrets', widget: 'secret', description: '下载字幕时与用户名一起使用。', value: '', secret: true },
      { key: 'TODAYS_LINES_USERNAME', label: '33 台词账号', group: 'secrets', widget: 'text', description: '自动化脚本登录账号。', value: 'demo_user', secret: false },
      { key: 'TODAYS_LINES_PASSWORD', label: '33 台词密码', group: 'secrets', widget: 'secret', description: '本地 token 不可用时用于登录。', value: 'secret', secret: true },
      { key: 'TODAYS_LINES_TOKEN', label: '33 台词 Token', group: 'secrets', widget: 'secret', description: '通常由程序自动写入。', value: '', secret: true },
      { key: 'TODAYS_LINES_TOKEN_TIME', label: '33 台词 Token 时间', group: 'secrets', widget: 'text', description: 'Token 缓存时间戳。', value: '', secret: false },
      { key: 'BAIDU_TRANSLATE_APP_ID', label: '百度翻译 App ID', group: 'secrets', widget: 'text', description: '自动化英文补全。', value: '', secret: false },
      { key: 'BAIDU_TRANSLATE_SECRET', label: '百度翻译 Secret', group: 'secrets', widget: 'secret', description: '与 App ID 配套使用。', value: '', secret: true },
    ],
  },
  {
    key: 'strategy',
    label: '字幕源策略',
    fields: [
      { key: 'SUBTITLE_PROVIDER_PRIORITY', label: '字幕源优先级', group: 'strategy', widget: 'text', description: '逗号分隔的字幕源顺序。', value: 'subhd,assrt,opensubtitles,subdl', secret: false },
      { key: 'SUBTITLE_PROVIDER_DISABLED', label: '禁用字幕源', group: 'strategy', widget: 'text', description: '逗号分隔，留空表示不额外禁用。', value: '', secret: false },
      { key: 'SUBTITLE_REQUEST_INTERVAL_MS', label: '请求间隔（ms）', group: 'strategy', widget: 'int', description: '过低数值会自动抬升到 8000。', value: '8000', secret: false },
      { key: 'SUBTITLE_MOVIE_CONCURRENCY', label: '电影并发', group: 'strategy', widget: 'int', description: '有效范围 1-4。', value: '2', secret: false },
      { key: 'SUBTITLE_MIN_BILINGUAL_RATIO', label: '双语最低占比', group: 'strategy', widget: 'float', description: '0.0-1.0，例如 0.70。', value: '0.70', secret: false },
    ],
  },
  {
    key: 'subhd',
    label: 'SubHD 与验证码',
    fields: [
      { key: 'SUBHD_CAPTCHA_OCR_ENABLED', label: '验证码 OCR', group: 'subhd', widget: 'bool', description: '启用后尝试自动识别验证码。', value: 'true', secret: false },
      { key: 'SUBHD_CAPTCHA_AUTO_SUBMIT_MIN_CONFIDENCE', label: 'OCR 自动提交置信度', group: 'subhd', widget: 'float', description: '0.0-1.0。', value: '0.85', secret: false },
      { key: 'CAPTCHA_SOUND_ENABLED', label: '验证码提示音', group: 'subhd', widget: 'bool', description: '弹出验证码时播放提示音。', value: 'true', secret: false },
    ],
  },
  {
    key: 'network',
    label: '网络与接口',
    fields: [
      { key: 'HTTP_PROXY', label: 'HTTP 代理', group: 'network', widget: 'text', description: '例如 http://127.0.0.1:7890。', value: '', secret: false },
      { key: 'HTTPS_PROXY', label: 'HTTPS 代理', group: 'network', widget: 'text', description: '例如 http://127.0.0.1:7890。', value: '', secret: false },
      { key: 'ASSRT_API_BASE_URL', label: 'ASSRT API 地址', group: 'network', widget: 'text', description: '默认 https://api.assrt.net/v1。', value: 'https://api.assrt.net/v1', secret: false },
    ],
  },
  {
    key: 'local',
    label: '本机与打包',
    fields: [
      { key: 'SUBTITLE_COLLECTION_DATA_DIR', label: '数据目录', group: 'local', widget: 'path', description: '留空使用用户目录默认路径。', value: '', secret: false },
      { key: 'SUBTITLE_COLLECTION_PACKAGE_DIST_DIR', label: '打包输出目录', group: 'local', widget: 'path', description: '仅影响打包脚本。', value: '', secret: false },
    ],
  },
]

let collectorState: TaskState = {
  status: 'idle',
  current: 0,
  total: 50,
  currentItem: '',
  stats: { downloadCount: 0, failedCount: 0, movieCount: 0 },
  error: '',
  outputPaths: [],
  logs: [],
  nextLogCursor: 0,
  verification: null,
  startedAt: 0,
  finishedAt: 0,
}

let parserState: TaskState = {
  status: 'idle',
  current: 0,
  total: 0,
  currentItem: '',
  stats: {},
  error: '',
  outputPaths: [],
  logs: [],
  nextLogCursor: 0,
  verification: null,
  startedAt: 0,
  finishedAt: 0,
}

let automationState: TaskState = {
  ...parserState,
  total: 120,
}

const MOCK_HISTORY: HistoryPage = {
  page: 1,
  pageSize: 20,
  total: 5,
  items: [
    { id: 5, startedAt: '2026-11-27T06:21:48+00:00', finishedAt: '', year: 2026, limit: 50, status: 'running', movieCount: 0, failedCount: 0, downloadCount: 0, downloadDir: '' },
    { id: 4, startedAt: '2026-11-26T06:20:00+00:00', finishedAt: '2026-11-26T07:08:00+00:00', year: 2026, limit: 50, status: 'completed', movieCount: 47, failedCount: 3, downloadCount: 44, downloadDir: 'C:\\Users\\huangjing\\subtitleInfoCollection\\output\\20261126-142000-2026-top50' },
    { id: 3, startedAt: '2026-11-25T13:10:00+00:00', finishedAt: '2026-11-25T13:41:00+00:00', year: 2026, limit: 30, status: 'completed', movieCount: 30, failedCount: 0, downloadCount: 30, downloadDir: 'C:\\Users\\huangjing\\subtitleInfoCollection\\output\\20261125-211000-2026-top30' },
    { id: 2, startedAt: '2026-11-24T02:02:00+00:00', finishedAt: '2026-11-24T03:00:00+00:00', year: 2025, limit: 50, status: 'completed', movieCount: 41, failedCount: 9, downloadCount: 32, downloadDir: 'C:\\Users\\huangjing\\subtitleInfoCollection\\output\\20261124-100200-2025-top50' },
    { id: 1, startedAt: '2026-11-23T08:40:00+00:00', finishedAt: '2026-11-23T08:55:00+00:00', year: 2025, limit: 20, status: 'completed', movieCount: 20, failedCount: 0, downloadCount: 20, downloadDir: 'C:\\Users\\huangjing\\subtitleInfoCollection\\output\\20261123-164000-2025-top20' },
  ],
}

const MOCK_FILES: ParserFile[] = [
  { path: 'D:\\字幕\\沙丘2.2024.srt', name: '沙丘2.2024.srt', size: 182_400, valid: true, reason: '' },
  { path: 'D:\\字幕\\奥本海默.2023.ass', name: '奥本海默.2023.ass', size: 243_100, valid: true, reason: '' },
  { path: 'D:\\字幕\\损坏样本.srt', name: '损坏样本.srt', size: 8_200, valid: false, reason: '文件小于 100KB（当前 8.0 KB）' },
]

// 按游标返回增量日志，模拟后端游标语义，避免浏览器预览时日志重复
function withLogs(state: TaskState, cursor: unknown): TaskState {
  const start = Math.max(0, Number(cursor ?? 0))
  return {
    ...state,
    logs: state.logs.slice(start),
    nextLogCursor: state.logs.length,
  }
}

// 浏览器内预览用的假数据，保证 npm run dev 可独立开发
export async function mockCall<T>(name: string, args: unknown[]): Promise<T> {
  await new Promise((resolve) => window.setTimeout(resolve, 160))

  switch (name) {
    case 'app.info':
      return APP_INFO as T
    case 'app.checkUpdate':
      updateState = {
        status: 'available',
        available: true,
        currentVersion: '0.2.3',
        latestVersion: '0.2.3',
        notes: '修复 SubHD 验证码重试偶发卡住\n优化采集日志增量拉取\n完善 9 页交互与侧栏折叠',
        progress: 0,
        error: '',
      }
      return updateState as T
    case 'app.updateState':
      return updateState as T
    case 'app.downloadUpdate':
      updateState = { ...updateState, status: 'ready', progress: 100 }
      return undefined as T
    case 'app.applyUpdateAndRestart':
      return undefined as T
    case 'app.setAlwaysOnTop':
      return Boolean(args[0]) as T
    case 'app.status': {
      const activeStatuses = ['starting', 'running', 'pausing', 'paused', 'aborting']
      const active =
        activeStatuses.includes(collectorState.status) ||
        activeStatuses.includes(parserState.status) ||
        activeStatuses.includes(automationState.status)
      return {
        collector: collectorState.status,
        parser: parserState.status,
        automation: automationState.status,
        active,
      } as T
    }
    case 'config.save':
    case 'history.reset':
    case 'shell.openPath':
    case 'shell.deleteOutputs':
      return undefined as T
    case 'config.list':
      return CONFIG_GROUPS as T
    case 'collector.state':
      return withLogs(collectorState, args[0]) as T
    case 'collector.start': {
      collectorState = {
        ...collectorState,
        status: 'running',
        current: 21,
        total: 50,
        currentItem: '沙丘 2',
        stats: { downloadCount: 18, failedCount: 3, movieCount: 50 },
        logs: [
          '14:20:03 TMDb 榜单 2026 拉取成功，共 50 部',
          '14:20:08 [1/50] 沙丘 2 · SubHD 搜索…',
          '14:20:19 命中双语字幕，评分 0.92',
          '14:20:31 请求过于频繁，等待 8s 后重试',
        ],
        nextLogCursor: 4,
      }
      return true as T
    }
    case 'collector.pause':
      collectorState.status = 'paused'
      return undefined as T
    case 'collector.resume':
      collectorState.status = 'running'
      return undefined as T
    case 'collector.abort':
      collectorState.status = 'aborted'
      return undefined as T
    case 'collector.submitVerification':
    case 'collector.refreshCaptcha':
      return true as T
    case 'parser.pickFiles':
      return MOCK_FILES.map((item) => item.path) as T
    case 'parser.inspectFiles':
      return MOCK_FILES as T
    case 'parser.start':
      parserState = {
        ...parserState,
        status: 'finished',
        current: 3,
        total: 3,
        stats: { successCount: 2, failureCount: 1, exportCount: 642 },
        outputPaths: ['C:\\Users\\huangjing\\subtitleInfoCollection\\parsed\\20261126-153000-movies.json'],
        logs: ['解析字幕：沙丘2.2024.srt', '解析成功：奥本海默.2023.ass', '解析失败：损坏样本.srt'],
      }
      return true as T
    case 'parser.state':
      return withLogs(parserState, args[0]) as T
    case 'parser.abort':
    case 'automation.abort':
      return undefined as T
    case 'automation.startTodays':
      automationState = {
        ...automationState,
        status: 'finished',
        current: 120,
        total: 120,
        stats: { totalCount: 120, inputCount: 126, skippedCount: 6, pageCount: 3 },
        outputPaths: ['C:\\Users\\huangjing\\subtitleInfoCollection\\automation\\todays-lines.json'],
        logs: [
          '启动 33 台词今日台词采集',
          ...Array.from({ length: 60 }, (_, i) => `请求第 ${i + 1} 页，累计 ${(i + 1) * 2} 条`),
          '导出 120 条数据',
        ],
      }
      return true as T
    case 'automation.startClassic':
      automationState = {
        ...automationState,
        status: 'running',
        current: 86,
        total: 240,
        stats: { totalMovies: 86, failedMovies: 2, totalLines: 1260, pageCount: 10 },
        logs: ['共找到 240 部电影', '第 4/10 页（本页 24 部）'],
      }
      return true as T
    case 'automation.state':
      return withLogs(automationState, args[0]) as T
    case 'history.list': {
      const keyword = String(args[2] ?? '').trim().toLowerCase()
      const items = keyword
        ? MOCK_HISTORY.items.filter(
            (item) =>
              String(item.year).includes(keyword) ||
              item.status.includes(keyword) ||
              item.startedAt.includes(keyword),
          )
        : MOCK_HISTORY.items
      return { ...MOCK_HISTORY, items, total: items.length } as T
    }
    case 'shell.pickDirectory':
      return 'C:\\示例目录' as T
    default:
      throw new Error(`mock 未实现：${name}`)
  }
}
