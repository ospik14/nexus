import { Activity, ArrowDown, ArrowUp, Box, ChevronLeft, ChevronRight, Cog, FileText, RefreshCw, Search, X } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Empty, Failure, Skeleton } from '../../components/states'
import { Button } from '../../components/ui/button'
import { useEndpoint } from '../../lib/api'
import { bytes, duration, percent } from '../../lib/format'

type Page = 'processes' | 'services' | 'docker'
type Sort = 'cpu' | 'memory'
type Direction = 'asc' | 'desc'

interface ProcessInfo { pid: number; name: string; cpu: number | null; memory: number; user: string; status: string }
interface Service { name: string; description: string; status: string; substate: string; load: string }
interface Container {
  id: string; name: string; image: string; status: string; detail: string; ports: string[];
  uptime: number | null; cpu: number | null; memory: number | null; memory_limit: number | null;
}
interface LogResponse { available: boolean; text: string; detail: string | null }

function Status({ value }: { value: string }) {
  const tone = ['active', 'running'].includes(value) ? 'ok' : ['failed', 'dead', 'zombie'].includes(value) ? 'failed' :
    ['activating', 'deactivating', 'reloading', 'restarting', 'paused', 'not-found'].includes(value) ? 'warn' : ''
  return <span className={`status-tag ${tone}`}><i className="dot"/>{value}</span>
}

function Readonly() {
  return <span className="readonly-tag">Read only</span>
}

function Processes() {
  const [input, setInput] = useState('')
  const [term, setTerm] = useState('')
  const [sort, setSort] = useState<Sort>('cpu')
  const [direction, setDirection] = useState<Direction>('desc')
  const [offset, setOffset] = useState(0)
  const limit = 30
  useEffect(() => {
    const timer = setTimeout(() => { setTerm(input.trim()); setOffset(0) }, 250)
    return () => clearTimeout(timer)
  }, [input])

  const endpoint = `/processes?sort=${sort}&direction=${direction}&offset=${offset}&limit=${limit}&q=${encodeURIComponent(term)}`
  const status = useEndpoint<{ processes: ProcessInfo[]; limited: boolean; total: number }>(endpoint, 5000)
  const items = status.data?.processes
  const total = status.data?.total ?? 0

  function applySort(next: Sort) {
    setDirection(sort === next && direction === 'desc' ? 'asc' : 'desc')
    setSort(next)
    setOffset(0)
  }

  function sortHeader(key: Sort, label: string) {
    const Icon = direction === 'asc' ? ArrowUp : ArrowDown
    return <th aria-sort={sort !== key ? 'none' : direction === 'asc' ? 'ascending' : 'descending'} scope="col">
      <button onClick={() => applySort(key)}>{label}{sort === key && <Icon size={13}/>}</button>
    </th>
  }

  return <>
    <header className="page-heading"><div><div className="page-kicker"><Activity size={14}/> Compute</div><h1>Processes</h1><p>Inspect active processes and their resource usage.</p></div><Readonly/></header>
    <section className="panel monitoring-panel" aria-label="Host processes">
      <div className="monitor-toolbar">
        <label className="search-input"><Search size={16}/><input aria-label="Search processes" placeholder="Search processes…" value={input} onChange={event => setInput(event.target.value)} maxLength={100}/></label>
        <Button variant="outline" size="small" onClick={status.refresh}><RefreshCw size={14}/> Refresh</Button>
      </div>
      {status.error && <div className="inset"><Failure detail={status.error} retry={status.refresh}/></div>}
      {status.loading && <div className="inset"><Skeleton height={40} count={6}/></div>}
      {status.data?.limited && <p className="list-limit">This host has more processes than the monitor can sample in a single pass.</p>}
      <div className="table-scroll" tabIndex={0} aria-label="Scrollable process table">
        <table className="data-table"><thead><tr><th scope="col">Process</th>{sortHeader('cpu', 'CPU')}{sortHeader('memory', 'Memory')}<th scope="col">User</th><th scope="col">Status</th></tr></thead>
          <tbody>{items?.map(item => <tr key={item.pid}>
            <th scope="row"><strong>{item.name}</strong><small className="mono">PID {item.pid}</small></th>
            <td className="mono">{percent(item.cpu)}</td><td className="mono">{bytes(item.memory)}</td><td className="mono">{item.user}</td><td><Status value={item.status}/></td>
          </tr>)}</tbody>
        </table>
      </div>
      {items?.length === 0 && <Empty title={term ? 'No matching processes' : 'No processes on this page'} detail={term ? 'Search by name, PID, user, or status.' : 'Return to the previous page or refresh the list.'} icon={Activity}/>}
      {status.data && <div className="monitor-pagination"><span>{total ? `${Math.min(offset + 1, total)}–${Math.min(offset + limit, total)} of ${total}` : '0 processes'}</span>
        <Button variant="ghost" size="icon" aria-label="Previous page" disabled={!offset} onClick={() => setOffset(previous => Math.max(0, previous - limit))}><ChevronLeft size={17}/></Button>
        <Button variant="ghost" size="icon" aria-label="Next page" disabled={offset + limit >= total} onClick={() => setOffset(previous => previous + limit)}><ChevronRight size={17}/></Button>
      </div>}
    </section>
  </>
}

function Logs({ name, endpoint, close }: { name: string; endpoint: string; close: () => void }) {
  const data = useEndpoint<LogResponse>(endpoint)
  return <section className="panel log-panel" aria-label={`Logs for ${name}`}>
    <div className="panel-head"><div><h2>Recent logs</h2><p className="mono">{name}</p></div>
      <div className="heading-actions">
        <Button size="icon" variant="ghost" aria-label="Refresh logs" onClick={data.refresh}><RefreshCw size={15}/></Button>
        <Button size="icon" variant="ghost" aria-label="Close logs" onClick={close}><X size={17}/></Button>
      </div>
    </div>
    {data.error && <div className="inset"><Failure detail={data.error} retry={data.refresh}/></div>}
    {data.loading && <div className="inset"><Skeleton height={110}/></div>}
    {data.data && (!data.data.available || !data.data.text) && <Empty title={data.data.available ? 'No recent log entries' : 'Logs unavailable'} detail={data.data.detail ?? 'The selected source returned no recent entries.'} icon={FileText}/>}
    {!!data.data?.text && <><pre className="log-output" tabIndex={0}>{data.data.text}</pre>{data.data.detail && <p className="list-limit">{data.data.detail}</p>}</>}
  </section>
}

function Services() {
  const services = useEndpoint<{ services: Service[]; available: boolean; detail: string | null }>('/services', 15_000)
  const [unit, setUnit] = useState<string>()
  return <>
    <header className="page-heading"><div><div className="page-kicker"><Cog size={14}/> systemd</div><h1>Services</h1><p>Check the status and recent logs of monitored services.</p></div><Readonly/></header>
    {services.error && <Failure detail={services.error} retry={services.refresh}/>}
    {services.loading && <Skeleton height={75} count={3}/>}
    {services.data?.services.length === 0 && <div className="panel"><Empty title={services.data.available ? 'No monitored services' : 'systemd unavailable'} detail={services.data.detail ?? 'No units were returned.'} icon={Cog}/></div>}
    {!!services.data?.services.length && <div className="monitor-list">
      {services.data.services.map(item => <section className="panel monitor-row" key={item.name}>
        <span className="metric-icon"><Cog size={17}/></span>
        <div className="monitor-identity"><strong className="mono">{item.name}</strong><small>{item.description}</small></div>
        <div className="monitor-status"><Status value={item.status}/>{item.substate && <small>{item.substate}</small>}</div>
        <Button variant="outline" size="small" aria-pressed={unit === item.name} onClick={() => setUnit(unit === item.name ? undefined : item.name)}><FileText size={14}/> Logs</Button>
        {unit === item.name && <div className="row-logs"><Logs name={unit} endpoint={`/services/logs?unit=${encodeURIComponent(unit)}`} close={() => setUnit(undefined)}/></div>}
      </section>)}
    </div>}
  </>
}

function Docker() {
  const docker = useEndpoint<{ containers: Container[]; enabled: boolean; available: boolean; detail: string | null }>('/docker', 12_000)
  const [id, setId] = useState<string>()
  return <>
    <header className="page-heading"><div><div className="page-kicker"><Box size={14}/> Docker</div><h1>Containers</h1><p>Inspect container health, resource usage, and published ports.</p></div><Readonly/></header>
    {docker.error && <Failure detail={docker.error} retry={docker.refresh}/>}
    {docker.loading && <Skeleton height={100} count={3}/>}
    {docker.data?.containers.length === 0 && <div className="panel"><Empty icon={Box} title={!docker.data.enabled ? 'Docker monitoring is off' : docker.data.available ? 'No containers found' : 'Docker collector unavailable'} detail={docker.data.detail ?? 'The Docker daemon returned an empty container list.'}/></div>}
    {!!docker.data?.containers.length && <div className="monitor-list">
      {docker.data.detail && <div className="connection-notice">{docker.data.detail}</div>}
      {docker.data.containers.map(item => <section className="panel monitor-row container-row" key={item.id}>
        <span className="metric-icon"><Box size={17}/></span>
        <div className="monitor-identity"><strong className="mono">{item.name}</strong><small className="mono">{item.image}</small></div>
        <div className="monitor-status" title={item.detail}><Status value={item.status}/></div>
        <Button variant="outline" size="small" aria-pressed={id === item.id} onClick={() => setId(id === item.id ? undefined : item.id)}><FileText size={14}/> Logs</Button>
        <dl className="container-details">
          <div><dt>Uptime</dt><dd>{duration(item.uptime)}</dd></div>
          <div><dt>CPU</dt><dd>{percent(item.cpu)}</dd></div>
          <div><dt>Memory</dt><dd>{bytes(item.memory)}{item.memory_limit == null ? '' : ` / ${bytes(item.memory_limit)}`}</dd></div>
          <div><dt>Published ports</dt><dd>{item.ports.length ? item.ports.join(' · ') : '—'}</dd></div>
        </dl>
        {id === item.id && <div className="row-logs"><Logs name={item.name} endpoint={`/docker/logs?container=${item.id}`} close={() => setId(undefined)}/></div>}
      </section>)}
    </div>}
  </>
}

export default function Monitoring({ page }: { page: Page }) {
  if (page === 'processes') return <Processes/>
  if (page === 'services') return <Services/>
  return <Docker/>
}
