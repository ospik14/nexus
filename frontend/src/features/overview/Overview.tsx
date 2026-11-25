import { Activity, ArrowDown, ArrowUp, Clock3, Cpu, EthernetPort, HardDrive, MemoryStick, Radio, Server } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { useState } from 'react'
import type { ReactNode } from 'react'
import { Failure, Skeleton } from '../../components/states'
import { useEndpoint } from '../../lib/api'
import { bytes, duration, percent } from '../../lib/format'
import { mergePoints, ranges } from '../../lib/metrics'
import type { Connection, OverviewData, Point, Range, Sample } from '../../lib/metrics'
import { ChartPanel, computeSeries, diskSeries, networkSeries } from './Charts'

function MetricCard({ icon: Icon, label, value, detail, color, progress }: {
  icon: LucideIcon; label: string; value: string; detail: string; color: string; progress?: number | null;
}) {
  return <section className={`panel metric-card tone-${color}`}>
    <div className="metric-heading"><span className="metric-icon"><Icon size={17}/></span><h2>{label}</h2></div>
    <div className="metric-value">{value}</div>
    <div className="metric-detail">{detail}</div>
    {progress != null && <div className="mini-track" role="meter" aria-label={label} aria-valuemin={0} aria-valuemax={100} aria-valuenow={progress}><span style={{ width: `${Math.max(0, Math.min(100, progress))}%` }}/></div>}
  </section>
}

function Flow({ icon: Icon, label, value, total }: { icon: LucideIcon; label: string; value: number | null | undefined; total: number | null | undefined }) {
  return <div className="flow"><span className="flow-label"><Icon size={13}/>{label}</span><strong>{bytes(value, true)}</strong><small>{bytes(total)} total</small></div>
}

function Info({ label, children }: { label: string; children: ReactNode }) {
  return <div className="info-row"><dt>{label}</dt><dd>{children}</dd></div>
}

function localTime(value?: string) {
  if (!value) return '—'
  const time = value.match(/T(\d{2}:\d{2}:\d{2})([+-][\d:]+)$/)
  return time ? `${time[1]}  UTC${time[2]}` : value
}

export default function Overview({ overview, sample, connection, live }: {
  overview: ReturnType<typeof useEndpoint<OverviewData>>; sample: Sample | null; connection: Connection; live: Point[];
}) {
  const [range, setRange] = useState<Range>('15m')
  const history = useEndpoint<{ samples: Point[] }>(`/history?window=${range}`, 45_000)
  const points = mergePoints(history.data?.samples ?? [], live, range)
  const host = overview.data?.host
  const current = sample ?? overview.data?.sample

  return <>
    <header className="page-heading">
      <div><div className="page-kicker"><Activity size={14}/> System monitor</div><h1>Overview</h1><p>Real-time performance and resource usage for your host.</p></div>
      <div className="host-chip"><span className="host-icon"><Server size={17}/></span><div><strong>{host?.hostname ?? 'Host'}</strong><small>{host?.architecture ?? '—'} · {host?.logical_cores ?? '—'} vCPU</small></div><span className={`dot ${connection === 'live' ? 'green' : 'amber'}`} aria-hidden="true"/></div>
    </header>
    {overview.error && <Failure detail={overview.error} retry={overview.refresh}/>}
    {connection === 'reconnecting' && <div className="connection-notice" role="status"><Radio size={15}/> Live updates disconnected. Reconnecting automatically.</div>}
    {overview.loading && !current ? <div className="metrics-grid">{Array.from({ length: 4 }, (_, index) => <Skeleton key={index} height={130}/>)}</div> :
      <div className="metrics-grid">
        <MetricCard icon={Cpu} label="CPU usage" value={percent(current?.cpu)} detail={`${current?.loads?.[0].toFixed(2) ?? '—'} load average · 1 min`} color="violet" progress={current?.cpu}/>
        <MetricCard icon={MemoryStick} label="Memory" value={percent(current?.ram)} detail={`${bytes(current?.ram_used)} of ${bytes(current?.ram_total)} used`} color="cyan" progress={current?.ram}/>
        <MetricCard icon={HardDrive} label="Disk usage" value={percent(current?.disk)} detail={`${bytes(current?.disk_free)} free · ${overview.data?.disk_path ?? '/'}`} color="amber" progress={current?.disk}/>
        <MetricCard icon={Clock3} label="Uptime" value={duration(current?.uptime)} detail={`${current?.process_count ?? '—'} processes`} color="green"/>
      </div>}
    <div className="section-heading"><div><h2>Performance</h2><p>Historical resource usage and traffic</p></div>
      <div className="range-buttons" role="group" aria-label="Historical time range">
        {(Object.keys(ranges) as Range[]).map(key => <button key={key} type="button" aria-pressed={key === range} onClick={() => setRange(key)}>{ranges[key].label}</button>)}
      </div>
    </div>
    {history.error && <Failure detail={history.error} retry={history.refresh}/>}
    <div className="charts-grid">
      {history.loading && !points.length ? <><Skeleton height={304}/><Skeleton height={304}/></> : <>
        <ChartPanel title="Compute utilization" subtitle="CPU and memory usage" points={points} series={computeSeries} range={range} percentage extra={
          <div className="panel-footer core-footer">
            <span className="footer-label"><Cpu size={14}/> Per-core CPU</span>
            <div className="cores" tabIndex={(current?.cores.length ?? 0) > 6 ? 0 : undefined} aria-label="Individual CPU cores">{current?.cores.map((core, index) => <span key={index}>Core {index} <strong>{percent(core)}</strong></span>) ?? '—'}</div>
          </div>}/>
        <ChartPanel title="Network throughput" subtitle={current?.interface_count ? `Across ${current.interface_count} network interface${current.interface_count === 1 ? '' : 's'}` : 'Host network traffic'} points={points} series={networkSeries} range={range} extra={
          <div className="panel-footer flow-footer">
            <Flow icon={ArrowDown} label="Download" value={current?.rx} total={current?.rx_total}/>
            <Flow icon={ArrowUp} label="Upload" value={current?.tx} total={current?.tx_total}/>
          </div>}/>
      </>}
    </div>
    <div className="charts-grid lower-grid">
      <section className="panel system-panel">
        <div className="panel-head"><div><h2>Host details</h2><p>Hardware and operating system</p></div><span className="metric-icon plain"><Server size={17}/></span></div>
        <dl className="info-list">
          <Info label="Operating system">{host?.os ?? '—'}</Info>
          <Info label="Kernel">{host?.kernel ?? '—'}</Info>
          <Info label="Architecture">{host?.architecture ?? '—'}</Info>
          <Info label="CPU model">{host?.cpu_model ?? '—'}</Info>
          <Info label="Load averages (1 / 5 / 15 min)">{current?.loads?.map(value => value.toFixed(2)).join(' / ') ?? '—'}</Info>
          <Info label="Available memory">{bytes(current?.ram_available)}</Info>
          <Info label="Swap usage">{current?.swap_total === 0 ? 'Not configured' : `${bytes(current?.swap_used)} / ${bytes(current?.swap_total)}`}</Info>
          <Info label="Disk used / capacity">{bytes(current?.disk_used)} / {bytes(current?.disk_total)}</Info>
          <Info label="Server local time">{localTime(current?.local_time)}</Info>
        </dl>
      </section>
      <div className="disk-panel">
        <ChartPanel title="Disk throughput" subtitle="Host block device activity" points={points} series={diskSeries} range={range} compact extra={
          <div className="panel-footer disk-footer"><span><HardDrive size={14}/> Read <strong>{bytes(current?.read, true)}</strong></span><span><EthernetPort size={14}/> Write <strong>{bytes(current?.write, true)}</strong></span></div>}/>
      </div>
    </div>
  </>
}
