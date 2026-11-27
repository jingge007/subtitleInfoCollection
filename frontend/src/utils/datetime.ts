// 兼容后端 ISO 时间、带时区偏移的时间以及简写时间串
const DATE_TIME_PATTERN = /^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})(?::(\d{2}))?/
// 末尾带 Z 或 ±HH:MM 偏移时按真实时刻换算到本地时区
const ZONE_PATTERN = /(?:Z|[+-]\d{2}:?\d{2})$/i

function pad(value: number): string {
  return String(value).padStart(2, '0')
}

// 解析时间串，带时区偏移走 Date 解析，无偏移按本地时间构造
export function parseDateTime(value?: string | null): Date | null {
  if (!value) {
    return null
  }
  const text = String(value).trim()
  const matched = DATE_TIME_PATTERN.exec(text)
  if (!matched) {
    return null
  }
  const [, year, month, day, hour, minute, second = '00'] = matched
  if (ZONE_PATTERN.test(text)) {
    const parsed = new Date(text)
    return Number.isNaN(parsed.getTime()) ? null : parsed
  }
  return new Date(
    Number(year),
    Number(month) - 1,
    Number(day),
    Number(hour),
    Number(minute),
    Number(second),
  )
}

// 把时间串格式化为本地时区的 YYYY-MM-DD HH:mm:ss
export function formatDateTime(value?: string | null): string {
  if (!value) {
    return '—'
  }
  const parsed = parseDateTime(value)
  if (!parsed) {
    return String(value).trim()
  }
  return (
    `${parsed.getFullYear()}-${pad(parsed.getMonth() + 1)}-${pad(parsed.getDate())} ` +
    `${pad(parsed.getHours())}:${pad(parsed.getMinutes())}:${pad(parsed.getSeconds())}`
  )
}

// 根据开始与结束时间计算任务耗时，缺结束时间时返回占位符
export function formatDuration(startedAt?: string | null, finishedAt?: string | null): string {
  const start = parseDateTime(startedAt)
  const end = parseDateTime(finishedAt)
  if (!start || !end) {
    return '—'
  }
  const seconds = Math.round((end.getTime() - start.getTime()) / 1000)
  if (seconds <= 0) {
    return '—'
  }
  if (seconds < 60) {
    return `${seconds} 秒`
  }
  if (seconds < 3600) {
    const minutes = Math.floor(seconds / 60)
    const rest = seconds % 60
    return rest ? `${minutes} 分 ${rest} 秒` : `${minutes} 分`
  }
  const hours = Math.floor(seconds / 3600)
  const minutes = Math.floor((seconds % 3600) / 60)
  return minutes ? `${hours} 小时 ${minutes} 分` : `${hours} 小时`
}
