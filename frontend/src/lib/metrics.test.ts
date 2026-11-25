import { describe, expect, it } from 'vitest'
import { bytes, duration, percent } from './format'
import { mergePoints } from './metrics'
import type { Point } from './metrics'

const point = (timestamp: number, cpu: number | null): Point => ({
  timestamp, cpu, ram: 20, disk: 5, swap: 0, read: 1000, write: 0, rx: null, tx: null, load: null,
})

describe('history and display', () => {
  it('preserves persisted buckets and bounds live points to the selected range', () => {
    const history = [point(1105, 5), point(1985, 12)]
    const incoming = [point(1987, 75), point(1991, 14), point(1999, 16), point(2007, null)]
    const result = mergePoints(history, incoming, '15m')
    expect(result.map(value => [value.timestamp, value.cpu])).toEqual([[1105, 5], [1985, 12], [1990, 14], [1995, 16], [2005, null]])
    expect(mergePoints([point(500, 1), ...history], incoming, '15m')).toEqual(result)
  })
  it('displays zero values and unavailable values distinctly', () => {
    expect(bytes(null)).toBe('—')
    expect(bytes(0, true)).toBe('0 B/s')
    expect(bytes(1024 ** 3)).toBe('1.0 GiB')
    expect(percent(0)).toBe('0.0%')
    expect(duration(90_000)).toBe('1d 1h')
  })
})
