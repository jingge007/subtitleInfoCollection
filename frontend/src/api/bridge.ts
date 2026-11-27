import { mockCall } from './mock'

const REQUEST_TIMEOUT_MS = 60_000
const UPDATE_DOWNLOAD_TIMEOUT_MS = 30 * 60_000
const BRIDGE_READY_TIMEOUT_MS = 15_000

export class BridgeError extends Error {}

// 是否已注入可用的 pywebview 接口（api 空对象阶段不能视为就绪）
export function hasBridge(): boolean {
  return typeof window.pywebview?.api?.app_info === 'function'
}

// WebView2 宿主在 pywebview 注入 js_api 之前就已存在，用于区分浏览器预览
function isWebViewHost(): boolean {
  const chromeHost = (window as unknown as { chrome?: { webview?: unknown } }).chrome
  return Boolean(chromeHost?.webview) || /\bEdg\//.test(navigator.userAgent)
}

let bridgeReady: Promise<void> | null = null

// 等待 pywebview 注入 js_api，避免启动瞬间误用浏览器 mock
function waitForBridge(): Promise<void> {
  if (hasBridge()) {
    return Promise.resolve()
  }
  if (!bridgeReady) {
    bridgeReady = new Promise<void>((resolve, reject) => {
      let timer = 0
      let poll = 0

      const cleanup = () => {
        window.clearTimeout(timer)
        window.clearInterval(poll)
        window.removeEventListener('pywebviewready', onReady)
      }
      const onReady = () => {
        if (!hasBridge()) {
          return
        }
        cleanup()
        resolve()
      }

      window.addEventListener('pywebviewready', onReady)
      poll = window.setInterval(onReady, 50)
      timer = window.setTimeout(() => {
        cleanup()
        reject(new BridgeError('应用接口初始化超时，请重启应用'))
      }, BRIDGE_READY_TIMEOUT_MS)
    }).catch((error) => {
      bridgeReady = null
      throw error
    })
  }
  return bridgeReady
}

// 前端点号接口名转 Python snake_case 方法名
function toPythonMethod(name: string): string {
  return name
    .replace(/\./g, '_')
    .replace(/([a-z0-9])([A-Z])/g, '$1_$2')
    .toLowerCase()
}

// 按指定超时调用接口，供下载等长耗时操作使用
async function invokeApi<T>(name: string, args: unknown[], timeoutMs: number): Promise<T> {
  if (isWebViewHost()) {
    await waitForBridge()
  }
  if (!hasBridge()) {
    return mockCall<T>(name, args)
  }

  const methodName = toPythonMethod(name)
  const method = window.pywebview?.api[methodName]
  if (typeof method !== 'function') {
    throw new BridgeError(`接口未实现：${methodName}`)
  }

  let timer = 0
  const timeout = new Promise<never>((_, reject) => {
    timer = window.setTimeout(() => reject(new BridgeError('请求超时，请稍后重试')), timeoutMs)
  })

  try {
    return (await Promise.race([method(...args), timeout])) as T
  } catch (error) {
    if (error instanceof BridgeError) {
      throw error
    }
    throw new BridgeError(error instanceof Error ? error.message : String(error))
  } finally {
    window.clearTimeout(timer)
  }
}

// 统一调用入口：窗口内走 js_api，浏览器内走 mock
export async function callApi<T = unknown>(name: string, ...args: unknown[]): Promise<T> {
  return invokeApi<T>(name, args, REQUEST_TIMEOUT_MS)
}

// 长耗时接口入口，避免更新包下载被默认超时打断
export async function callApiWithTimeout<T = unknown>(
  name: string,
  timeoutMs: number,
  ...args: unknown[]
): Promise<T> {
  return invokeApi<T>(name, args, timeoutMs)
}

export const api = {
  appInfo: () => callApi<AppInfo>('app.info'),
  checkUpdate: () => callApi<UpdateState>('app.checkUpdate'),
  updateState: () => callApi<UpdateState>('app.updateState'),
  downloadUpdate: () =>
    callApiWithTimeout<void>('app.downloadUpdate', UPDATE_DOWNLOAD_TIMEOUT_MS),
  applyUpdate: () => callApi<void>('app.applyUpdateAndRestart'),
  setAlwaysOnTop: (enabled: boolean) => callApi<boolean>('app.setAlwaysOnTop', enabled),
  appStatus: () => callApi<AppStatus>('app.status'),
  configList: () => callApi<ConfigGroup[]>('config.list'),
  configSave: (values: Record<string, string>) => callApi<void>('config.save', values),
  collectorStart: (options: Record<string, unknown>) => callApi<boolean>('collector.start', options),
  collectorPause: () => callApi<void>('collector.pause'),
  collectorResume: () => callApi<void>('collector.resume'),
  collectorAbort: () => callApi<void>('collector.abort'),
  collectorState: (logCursor = 0) => callApi<TaskState>('collector.state', logCursor),
  collectorSubmitVerification: (code: string) =>
    callApi<boolean>('collector.submitVerification', code),
  collectorRefreshCaptcha: () => callApi<boolean>('collector.refreshCaptcha'),
  parserPickFiles: () => callApi<string[]>('parser.pickFiles'),
  parserInspectFiles: (paths: string[]) =>
    callApi<ParserFile[]>('parser.inspectFiles', paths),
  parserStart: (options: Record<string, unknown>) => callApi<boolean>('parser.start', options),
  parserState: (logCursor = 0) => callApi<TaskState>('parser.state', logCursor),
  parserAbort: () => callApi<void>('parser.abort'),
  automationStartTodays: (options: Record<string, unknown>) =>
    callApi<boolean>('automation.startTodays', options),
  automationStartClassic: (options: Record<string, unknown>) =>
    callApi<boolean>('automation.startClassic', options),
  automationState: (logCursor = 0) => callApi<TaskState>('automation.state', logCursor),
  automationAbort: () => callApi<void>('automation.abort'),
  historyList: (page = 1, pageSize = 20, keyword = '') =>
    callApi<HistoryPage>('history.list', page, pageSize, keyword),
  historyReset: () => callApi<void>('history.reset'),
  shellOpenPath: (path: string) => callApi<boolean>('shell.openPath', path),
  shellPickDirectory: () => callApi<string | null>('shell.pickDirectory'),
  shellDeleteOutputs: () => callApi<boolean>('shell.deleteOutputs'),
}

export interface AppInfo {
  version: string
  dataDir: string
  envPath: string
  programDir: string
  platform: string
  frozen: boolean
}

export interface AppStatus {
  collector: string
  parser: string
  automation: string
  active: boolean
}

export type UpdateStatus =
  | 'idle'
  | 'checking'
  | 'latest'
  | 'available'
  | 'downloading'
  | 'ready'
  | 'restarting'
  | 'error'

export interface UpdateState {
  status: UpdateStatus
  available: boolean
  currentVersion: string
  latestVersion: string
  notes: string
  progress: number
  error: string
}

export interface ConfigField {
  key: string
  label: string
  group: string
  widget: string
  description: string
  value: string
  secret: boolean
}

export interface ConfigGroup {
  key: string
  label: string
  fields: ConfigField[]
}

export interface VerificationRequest {
  provider: string
  providerSubtitleId: string
  subtitleTitle: string
  detailUrl: string
  verificationHtml: string
  verificationImageDataUri: string
  suggestedCode: string
  suggestedConfidence: number
  ocrMessage: string
}

export interface TaskState {
  status: string
  current: number
  total: number
  currentItem: string
  stats: Record<string, unknown>
  error: string
  outputPaths: string[]
  logs: string[]
  nextLogCursor: number
  verification: VerificationRequest | null
  startedAt: number
  finishedAt: number
}

export interface ParserFile {
  path: string
  name: string
  size: number
  valid: boolean
  reason: string
}

export interface HistoryItem {
  id: number
  startedAt: string
  finishedAt: string
  year: number
  limit: number
  status: string
  movieCount: number
  failedCount: number
  downloadCount: number
  downloadDir: string
}

export interface HistoryPage {
  items: HistoryItem[]
  total: number
  page: number
  pageSize: number
}
