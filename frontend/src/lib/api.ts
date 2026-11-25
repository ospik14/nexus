import { useEffect, useState } from 'react'

export interface Session {
  username: string
  csrf: string
  expires: number
}

export class ApiError extends Error {
  status: number

  constructor(status: number, detail: string) {
    super(detail)
    this.status = status
  }
}

let csrf: string | undefined
export function setSession(session: Session | null) {
  csrf = session?.csrf
}

export async function api<T>(path: string, options: { method?: string; body?: unknown; signal?: AbortSignal } = {}): Promise<T> {
  const { method = 'GET', body, signal } = options
  const headers: Record<string, string> = { Accept: 'application/json' }
  if (method !== 'GET') {
    headers['Content-Type'] = 'application/json'
    if (csrf) headers['X-CSRF-Token'] = csrf
  }
  const result = await fetch(`/api${path}`, {
    method, headers, body: method === 'GET' ? undefined : JSON.stringify(body ?? {}), signal,
  })
  if (!result.ok) {
    const failure = await result.json().catch(() => null)
    if (result.status === 401 && path !== '/auth/login' && path !== '/auth/session') {
      window.dispatchEvent(new Event('nexus:expired'))
    }
    throw new ApiError(result.status, typeof failure?.detail === 'string' ? failure.detail : 'Request could not be completed')
  }
  return result.status === 204 ? undefined as T : result.json()
}

export function errorText(error: unknown): string {
  return error instanceof Error && !(error instanceof TypeError) ? error.message : 'Could not reach Nexus. Try again.'
}

export function useEndpoint<T>(path: string | null, refreshMs = 0) {
  const [state, setState] = useState<{ key: string | null; data?: T; error?: string }>({ key: null })
  const [revision, setRevision] = useState(0)
  useEffect(() => {
    if (!path) return
    const abort = new AbortController()
    let timer: ReturnType<typeof setTimeout>
    async function load() {
      try {
        const data = await api<T>(path!, { signal: abort.signal })
        if (!abort.signal.aborted) setState({ key: path, data })
      } catch (error) {
        if (!abort.signal.aborted) setState(previous => ({ key: path, error: errorText(error), data: previous.key === path ? previous.data : undefined }))
      } finally {
        if (!abort.signal.aborted && refreshMs) timer = setTimeout(load, refreshMs)
      }
    }
    void load()
    return () => { abort.abort(); clearTimeout(timer) }
  }, [path, refreshMs, revision])
  const data = state.key === path ? state.data : undefined
  const error = state.key === path ? state.error : undefined
  return { data, error, loading: path !== null && !data && !error, refresh: () => setRevision(value => value + 1) }
}
