import { Activity, Box, ChevronRight, Cog, FolderCode, Gauge, LogOut, Server, ShieldCheck } from 'lucide-react'
import { lazy, Suspense, useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { Button } from './components/ui/button'
import { Failure, Skeleton } from './components/states'
import { api, ApiError, errorText, setSession, useEndpoint } from './lib/api'
import type { Session } from './lib/api'
import { useLive } from './lib/metrics'
import type { OverviewData } from './lib/metrics'

const Overview = lazy(() => import('./features/overview/Overview'))
const Files = lazy(() => import('./features/files/Files'))
const Monitoring = lazy(() => import('./features/monitoring/Monitoring'))

const pages = {
  overview: { label: 'Overview', icon: Gauge },
  processes: { label: 'Processes', icon: Activity },
  services: { label: 'Services', icon: Cog },
  docker: { label: 'Containers', icon: Box },
  files: { label: 'Files', icon: FolderCode },
}
type Page = keyof typeof pages

function pageFromLocation(): Page {
  const name = location.hash.slice(1)
  return Object.hasOwn(pages, name) ? name as Page : 'overview'
}

function Brand() {
  return <div className="brand"><img src="/favicon.svg" width="36" height="36" alt=""/><div><strong>Nexus</strong><span>VPS CONTROL PANEL</span></div></div>
}

function Login({ onLogin, notice }: { onLogin: (session: Session) => void; notice?: string }) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [pending, setPending] = useState(false)
  const [error, setError] = useState('')

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setPending(true)
    setError('')
    try {
      onLogin(await api<Session>('/auth/login', { method: 'POST', body: { username, password } }))
    } catch (failure) {
      setError(errorText(failure))
    } finally {
      setPending(false)
    }
  }

  return <main className="login-screen">
    <div className="login-card panel">
      <Brand/>
      <h1>Sign in</h1>
      <p>Access your private infrastructure panel.</p>
      {(error || notice) && <Failure detail={error || notice!}/>}
      <form onSubmit={submit}>
        <label>Username<input name="username" autoComplete="username" value={username} onChange={event => setUsername(event.target.value)} maxLength={64} required /></label>
        <label>Password<input type="password" name="password" autoComplete="current-password" value={password} onChange={event => setPassword(event.target.value)} required /></label>
        <Button disabled={pending} type="submit">{pending ? 'Signing in…' : 'Sign in'}</Button>
      </form>
    </div>
    <span className="login-footer"><ShieldCheck size={15}/> Private administrator access</span>
  </main>
}

function PanelApp({ session, onLogout }: { session: Session; onLogout: () => void }) {
  const [page, setPage] = useState(pageFromLocation)
  const [visitedFiles, setVisitedFiles] = useState(page === 'files')
  const [error, setError] = useState('')
  const live = useLive()
  const overview = useEndpoint<OverviewData>('/overview', 120_000)
  const [logoutPending, setLogoutPending] = useState(false)
  const host = overview.data?.host

  useEffect(() => {
    const onHash = () => {
      const next = pageFromLocation()
      setPage(next)
      if (next === 'files') setVisitedFiles(true)
      window.scrollTo(0, 0)
    }
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])

  async function logout() {
    if (document.querySelector('[data-unsaved="true"]') && !window.confirm('Sign out and discard your unsaved edits?')) return
    setLogoutPending(true)
    try {
      await api('/auth/logout', { method: 'POST' })
      onLogout()
    } catch (failure) {
      setError(errorText(failure))
    } finally {
      setLogoutPending(false)
    }
  }

  return <div className="app-shell">
    <aside className="sidebar">
      <Brand/>
      <nav className="nav" aria-label="Control panel">
        <div className="nav-caption">WORKSPACE</div>
        {(Object.keys(pages) as Page[]).map(key => {
          const { label, icon: Icon } = pages[key]
          return <a key={key} href={`#${key}`} aria-current={page === key ? 'page' : undefined} className={`nav-item ${page === key ? 'selected' : ''}`}>
            <Icon size={18} strokeWidth={1.8}/><span>{key === 'docker' ? <><span className="desktop-label">{label}</span><span className="mobile-label">Docker</span></> : label}</span>
          </a>
        })}
      </nav>
      <div className="sidebar-footer"><span className="sidebar-host"><Server size={16}/></span><div><strong>{host?.hostname ?? 'Local host'}</strong><small>Private instance</small></div><ShieldCheck size={15} className="sidebar-shield"/></div>
    </aside>
    <div className="main-shell">
      <header className="topbar">
        <div className="top-crumb"><span className="desktop-label">Control panel</span><ChevronRight className="desktop-label" size={14}/><span className="mobile-logo"><img src="/favicon.svg" alt="Nexus" width="26" height="26"/></span><strong>{pages[page].label}</strong></div>
        <div className="top-right">
          <span className={`live-badge ${live.connection}`} role="status"><span className="dot"/>{live.connection === 'live' ? 'Live' : live.connection === 'connecting' ? 'Connecting' : 'Reconnecting'}</span>
          <span className="account-divider"/>
          <Button variant="ghost" size="icon" className="signout" aria-label={`Sign out ${session.username}`} title={`Sign out ${session.username}`} disabled={logoutPending} onClick={() => void logout()}><span className="avatar">{session.username.slice(0, 1).toUpperCase()}</span><LogOut size={16}/></Button>
        </div>
      </header>
      <main className="content" id="main-content">
        {error && <Failure detail={error}/>}
        <Suspense fallback={<Skeleton count={3} height={108}/>}>
          {page === 'overview' && <Overview overview={overview} sample={live.sample} connection={live.connection} live={live.points}/>}
          {page !== 'overview' && page !== 'files' && <Monitoring key={page} page={page}/>}
          {visitedFiles && <div hidden={page !== 'files'}><Files active={page === 'files'}/></div>}
        </Suspense>
      </main>
    </div>
  </div>
}

export default function App() {
  const [session, updateSession] = useState<Session | null>(null)
  const [checking, setChecking] = useState(true)
  const [error, setError] = useState('')
  const [retry, setRetry] = useState(0)
  const [notice, setNotice] = useState<string>()

  function changeSession(next: Session | null) {
    setSession(next)
    updateSession(next)
  }

  useEffect(() => {
    const abort = new AbortController()
    void api<Session>('/auth/session', { signal: abort.signal }).then(changeSession).catch(failure => {
      if (!abort.signal.aborted && !(failure instanceof ApiError && failure.status === 401)) setError(errorText(failure))
    }).finally(() => { if (!abort.signal.aborted) setChecking(false) })
    return () => abort.abort()
  }, [retry])

  useEffect(() => {
    function expire() {
      changeSession(null)
      setNotice('Your session expired. Sign in again to continue.')
    }
    window.addEventListener('nexus:expired', expire)
    return () => window.removeEventListener('nexus:expired', expire)
  }, [])

  if (checking) return <main className="login-screen"><div className="login-card"><Brand/><Skeleton height={200}/></div></main>
  if (error) return <main className="login-screen"><div className="login-card"><Brand/><Failure detail={error} retry={() => { setError(''); setChecking(true); setRetry(value => value + 1) }}/></div></main>
  if (!session) return <Login notice={notice} onLogin={next => { changeSession(next); setNotice(undefined) }}/>
  return <PanelApp session={session} onLogout={() => { changeSession(null); setNotice(undefined) }}/>
}
