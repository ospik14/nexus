export function bytes(value: number | null | undefined, rate = false) {
  if (value == null || !Number.isFinite(value)) return '—'
  const units = ['B', 'KiB', 'MiB', 'GiB', 'TiB', 'PiB']
  const unit = value > 0 ? Math.min(units.length - 1, Math.floor(Math.log(value) / Math.log(1024))) : 0
  const amount = value / 1024 ** Math.max(0, unit)
  return `${amount.toFixed(unit <= 0 || amount >= 100 ? 0 : 1)} ${units[Math.max(0, unit)]}${rate ? '/s' : ''}`
}

export function percent(value: number | null | undefined) {
  return value == null ? '—' : `${value.toFixed(1)}%`
}

export function duration(value: number | null | undefined) {
  if (value == null) return '—'
  const minutes = Math.floor(value / 60)
  const days = Math.floor(minutes / 1440)
  const hours = Math.floor((minutes % 1440) / 60)
  if (days) return `${days}d ${hours}h`
  if (hours) return `${hours}h ${minutes % 60}m`
  return minutes ? `${minutes}m` : `${Math.floor(value)}s`
}

export function dateTime(epoch: number) {
  return new Date(epoch * 1000).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
}
