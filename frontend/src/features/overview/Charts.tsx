import { Activity } from 'lucide-react'
import type { ReactNode } from 'react'
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { Empty } from '../../components/states'
import type { HistoryKey, Point, Range } from '../../lib/metrics'
import { bytes, percent } from '../../lib/format'

export interface Series { key: HistoryKey; label: string; color: string }

export const computeSeries: Series[] = [
  { key: 'cpu', label: 'CPU', color: '#a78bfa' },
  { key: 'ram', label: 'Memory', color: '#38c6db' },
]
export const networkSeries: Series[] = [
  { key: 'rx', label: 'Download', color: '#a78bfa' },
  { key: 'tx', label: 'Upload', color: '#38c6db' },
]
export const diskSeries: Series[] = [
  { key: 'read', label: 'Read', color: '#a78bfa' },
  { key: 'write', label: 'Write', color: '#3fb950' },
]

function timeLabel(timestamp: number, range: Range) {
  const date = new Date(timestamp * 1000)
  if (range === '7d') return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
  return date.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', hour12: false,
    ...(range === '15m' ? { second: '2-digit' } : {}) })
}

export function ChartPanel({ title, subtitle, points, series, range, percentage, compact, extra }: {
  title: string; subtitle: string; points: Point[]; series: Series[]; range: Range;
  percentage?: boolean; compact?: boolean; extra?: ReactNode;
}) {
  const chartPoints: { timestamp: number }[] = []
  const gap = { '15m': 90, '1h': 90, '6h': 180, '24h': 720, '7d': 5400 }[range]
  for (const point of points) {
    const last = chartPoints.at(-1)
    if (last && point.timestamp - last.timestamp > gap) chartPoints.push({ timestamp: last.timestamp + 1 })
    chartPoints.push(point)
  }
  const hasData = points.some(point => series.some(item => point[item.key] != null))
  const format = percentage ? percent : (value: number) => bytes(value, true)
  return <section className="panel chart-panel" aria-label={title}>
    <div className="panel-head">
      <div><h2>{title}</h2><p>{subtitle}</p></div>
      <div className="chart-legend">{series.map(item => <span key={item.key}><i style={{ background: item.color }}/>{item.label}</span>)}</div>
    </div>
    <div className={compact ? 'plot compact' : 'plot'}>
      {hasData ? <ResponsiveContainer width="100%" height="100%" minWidth={0} initialDimension={{ width: 300, height: compact ? 150 : 212 }}>
        <AreaChart data={chartPoints} margin={{ top: 8, right: 8, bottom: 0, left: 0 }} accessibilityLayer>
          <defs>{series.map(item => <linearGradient id={`area-${item.key}`} key={item.key} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={item.color} stopOpacity={0.18}/><stop offset="100%" stopColor={item.color} stopOpacity={0.015}/>
          </linearGradient>)}</defs>
          <CartesianGrid vertical={false} stroke="#2a313b" strokeDasharray="3 4"/>
          <XAxis dataKey="timestamp" type="number" scale="time" domain={[points[0].timestamp - (points.length === 1 ? 10 : 0), points.at(-1)!.timestamp + (points.length === 1 ? 10 : 0)]}
            minTickGap={22} tickCount={6} padding={{ left: 17, right: 22 }} tickLine={false} axisLine={false} tickMargin={10} tickFormatter={value => timeLabel(value, range)} tick={{ fill: '#8b949e', fontSize: 10 }}/>
          <YAxis domain={percentage ? [0, 100] : [0, (maximum: number) => Math.max(1024, maximum)]} tickCount={5} width={percentage ? 47 : 73}
            tickLine={false} axisLine={false} tickMargin={8} tickFormatter={value => percentage ? `${value}%` : bytes(value, true).replace(' ', '')} tick={{ fill: '#8b949e', fontSize: 10 }}/>
          <Tooltip labelFormatter={value => timeLabel(Number(value), range)} formatter={(value, name) => [format(Number(value)), name]}
            cursor={{ stroke: '#555c69', strokeDasharray: '3 3' }} contentStyle={{ background: '#1c2128', border: '1px solid #30363d', borderRadius: 8, fontSize: 12 }}/>
          {series.map(item => <Area key={item.key} type="monotone" name={item.label} dataKey={item.key} stroke={item.color} strokeWidth={1.8}
            fill={`url(#area-${item.key})`} isAnimationActive={false} dot={points.length <= 2} activeDot={{ r: 4, stroke: '#161b22' }}/>)}
        </AreaChart>
      </ResponsiveContainer> : <Empty title="Waiting for samples" detail="Measurements appear as the host reports them." icon={Activity}/>}
    </div>
    {extra}
  </section>
}
