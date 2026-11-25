import { useEffect, useState } from 'react'
import { api } from './api'

export type Scalar = number | null
export type HistoryKey = 'cpu' | 'ram' | 'swap' | 'disk' | 'read' | 'write' | 'rx' | 'tx' | 'load'
export type Point = { timestamp: number } & Record<HistoryKey, Scalar>
export interface Host {
  hostname: string
  os: string
  kernel: string
  architecture: string
  cpu_model: string | null
  logical_cores: Scalar
}
export interface Sample extends Point {
  local_time: string
  cores: Scalar[]
  ram_used: Scalar
  ram_available: Scalar
  ram_total: Scalar
  swap_used: Scalar
  swap_total: Scalar
  disk_used: Scalar
  disk_free: Scalar
  disk_total: Scalar
  rx_total: Scalar
  tx_total: Scalar
  interface_count: number
  loads: [number, number, number] | null
  process_count: Scalar
  uptime: Scalar
}
export interface OverviewData { host: Host; sample: Sample | null; disk_path: string }
export type Connection = 'connecting' | 'live' | 'reconnecting'

export const ranges = {
  '15m': { label: '15 min', seconds: 900, bucket: 5 },
  '1h': { label: '1 hour', seconds: 3600, bucket: 15 },
  '6h': { label: '6 hours', seconds: 21600, bucket: 60 },
  '24h': { label: '24 hours', seconds: 86400, bucket: 240 },
  '7d': { label: '7 days', seconds: 604800, bucket: 1800 },
} as const
export type Range = keyof typeof ranges

export function mergePoints(history: Point[], live: Point[], range: Range): Point[] {
  const last = live.at(-1)?.timestamp ?? history.at(-1)?.timestamp ?? 0
  const minimum = last - ranges[range].seconds
  const width = ranges[range].bucket
  const points = new Map<number, Point>()
  const persistedThrough = history.at(-1)?.timestamp ?? 0
  for (const point of history) if (point.timestamp >= minimum - width) points.set(point.timestamp, point)
  for (const point of live) {
    const stamp = Math.floor(point.timestamp / width) * width
    if (stamp >= minimum - width && stamp > persistedThrough) points.set(stamp, { ...point, timestamp: stamp })
  }
  return [...points.values()].sort((a, b) => a.timestamp - b.timestamp)
}

export function useLive() {
  const [connection, setConnection] = useState<Connection>('connecting')
  const [sample, setSample] = useState<Sample | null>(null)
  const [points, setPoints] = useState<Point[]>([])

  useEffect(() => {
    let socket: WebSocket
    let timer: ReturnType<typeof setTimeout>
    let heartbeat: ReturnType<typeof setTimeout>
    let attempts = 0
    let stopped = false

    function connect() {
      const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:'
      socket = new WebSocket(`${protocol}//${location.host}/api/live`)
      const resetHeartbeat = () => {
        clearTimeout(heartbeat)
        heartbeat = setTimeout(() => socket.close(), 16_000)
      }
      socket.onopen = resetHeartbeat
      socket.onmessage = (event: MessageEvent<string>) => {
        let incoming: Sample
        try { incoming = JSON.parse(event.data) as Sample } catch { return }
        if (!Number.isFinite(incoming.timestamp)) return
        resetHeartbeat()
        attempts = 0
        setConnection('live')
        setSample(incoming)
        const { timestamp, cpu, ram, swap, disk, read, write, rx, tx, load } = incoming
        setPoints(previous => [...previous.filter(point => point.timestamp < timestamp).slice(-299),
          { timestamp, cpu, ram, swap, disk, read, write, rx, tx, load }])
      }
      socket.onclose = async (event) => {
        clearTimeout(heartbeat)
        if (stopped) return
        if (event.code === 4401) {
          window.dispatchEvent(new Event('nexus:expired'))
          return
        }
        setConnection('reconnecting')
        try { await api('/auth/session', { signal: AbortSignal.timeout(4000) }) } catch (error) {
          if (error instanceof Error && 'status' in error && error.status === 401) {
            if (!stopped) window.dispatchEvent(new Event('nexus:expired'))
            return
          }
        }
        if (!stopped) {
          const delay = Math.min(15_000, 1000 * 2 ** attempts++)
          timer = setTimeout(connect, delay + Math.random() * 300)
        }
      }
    }

    connect()
    return () => {
      stopped = true
      clearTimeout(timer)
      clearTimeout(heartbeat)
      socket.onclose = null
      socket.close()
    }
  }, [])
  return { connection, sample, points }
}
