// 将任务进度转换为 0-100 的整数，避免接口总数偏小导致超过 100%
export function progressPercent(current: number, total: number): number {
  const safeCurrent = Number.isFinite(current) ? Math.max(0, current) : 0
  const safeTotal = Number.isFinite(total) ? Math.max(0, total) : 0
  if (safeTotal <= 0) {
    return 0
  }
  return Math.min(100, Math.max(0, Math.round((safeCurrent / safeTotal) * 100)))
}
