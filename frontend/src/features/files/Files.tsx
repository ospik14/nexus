import { ArrowLeft, ClipboardList, Download, FilePlus2, FolderCode, FolderPlus, History, Maximize, Minimize, Pencil, RotateCcw, Save, Trash2, X } from 'lucide-react'
import { lazy, Suspense, useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { Confirm } from '../../components/confirm'
import type { Confirmation } from '../../components/confirm'
import { Empty, Failure, Skeleton } from '../../components/states'
import { Button } from '../../components/ui/button'
import { api, ApiError, errorText, useEndpoint } from '../../lib/api'
import { bytes, dateTime } from '../../lib/format'
import { DirectoryBrowser, WorkspaceTree } from './Browser'
import { fileApi, fileKey, leaf, parentPath, query } from './types'
import type { AuditEvent, Entry, FileData, FileTab, Revision } from './types'

const CodeEditor = lazy(() => import('./CodeEditor'))
type EntryForm = { kind: 'file' | 'directory' | 'rename'; name: string }

function AuditList({ workspace }: { workspace: string }) {
  const [pages, setPages] = useState<number[]>([])
  const before = pages.at(-1)
  const audit = useEndpoint<{ events: AuditEvent[] }>(`${fileApi(workspace)}/audit${before ? `?before=${before}` : ''}`)
  return <>
    {audit.loading && <Skeleton height={110}/>}
    {audit.error && <Failure detail={audit.error} retry={audit.refresh}/>}
    {audit.data?.events.length === 0 && <Empty title="No changes recorded" detail="Workspace operations appear here." icon={ClipboardList}/>}
    {audit.data?.events.map(event => <div className="detail-list-row" key={event.id}>
      <div><strong>{event.action} <span className="mono">{event.path}{event.target ? ` → ${event.target}` : ''}</span></strong>
        <small>{dateTime(event.timestamp)} · {event.actor}</small></div>
      <span className={`status-tag ${event.result === 'applied' ? 'ok' : 'warn'}`}>{event.result}</span>
    </div>)}
    <div className="detail-actions">
      {!!pages.length && <Button variant="outline" size="small" onClick={() => setPages(previous => previous.slice(0, -1))}>Newer</Button>}
      {audit.data?.events.length === 50 && <Button variant="outline" size="small" onClick={() => setPages(previous => [...previous, audit.data!.events.at(-1)!.id])}>Older</Button>}
    </div>
  </>
}

function RevisionList({ workspace, path, generation, restore, disabled }: {
  workspace: string; path: string; generation: number; restore: (revision: Revision) => void; disabled: boolean;
}) {
  const revisions = useEndpoint<{ revisions: Revision[] }>(path ? `${fileApi(workspace)}/revisions${query(path)}&v=${generation}` : null)
  return <>
    {revisions.loading && <Skeleton height={90}/>}
    {revisions.error && <Failure detail={revisions.error} retry={revisions.refresh}/>}
    {revisions.data?.revisions.length === 0 && <Empty title="No retained revisions" detail="Nexus stores the preceding version when a file is changed or deleted." icon={History}/>}
    {revisions.data?.revisions.map(revision => <div className="detail-list-row" key={revision.id}>
      <div><strong>{dateTime(revision.timestamp)}</strong><small className="mono">{bytes(revision.size)} · {revision.digest.slice(0, 12)}</small></div>
      <Button variant="outline" size="small" disabled={disabled} onClick={() => restore(revision)}><RotateCcw size={14}/> Restore</Button>
    </div>)}
  </>
}

export default function Files({ active }: { active: boolean }) {
  const workspaces = useEndpoint<{ workspaces: string[]; max_file_bytes: number }>('/files/workspaces')
  const [chosen, setChosen] = useState('')
  const workspace = chosen || workspaces.data?.workspaces[0] || ''
  const [path, setPath] = useState('')
  const [selected, setSelected] = useState<Entry | null>(null)
  const [tabs, setTabs] = useState<FileTab[]>([])
  const [currentId, setCurrentId] = useState('')
  const [editor, setEditor] = useState(false)
  const [full, setFull] = useState(false)
  const [generation, setGeneration] = useState(0)
  const [form, setForm] = useState<EntryForm | null>(null)
  const [detail, setDetail] = useState<'audit' | 'revisions' | null>(null)
  const [revisionPath, setRevisionPath] = useState('')
  const [revisionQuery, setRevisionQuery] = useState('')
  const [busy, setBusy] = useState(false)
  const lock = useRef(false)
  const [notice, setNotice] = useState('')
  const [error, setError] = useState('')
  const [conflict, setConflict] = useState('')
  const [confirm, setConfirm] = useState<Confirmation | null>(null)
  const openTabs = tabs.filter(tab => tab.workspace === workspace)
  const current = openTabs.find(tab => tab.id === currentId)
  const dirty = tabs.some(tab => tab.draft !== tab.content)
  const showEditor = active && editor && !!current

  useEffect(() => {
    if (!dirty) return
    function prevent(event: BeforeUnloadEvent) {
      event.preventDefault()
      event.returnValue = ''
    }
    window.addEventListener('beforeunload', prevent)
    return () => window.removeEventListener('beforeunload', prevent)
  }, [dirty])

  useEffect(() => {
    if (!full || !showEditor) return
    const previous = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    const close = (event: KeyboardEvent) => { if (event.key === 'Escape') setFull(false) }
    window.addEventListener('keydown', close)
    return () => { document.body.style.overflow = previous; window.removeEventListener('keydown', close) }
  }, [full, showEditor])

  function changed(message: string) {
    setNotice(message)
    setGeneration(value => value + 1)
  }

  async function run(operation: () => Promise<void>, related = '') {
    if (lock.current) return
    lock.current = true
    setBusy(true)
    setNotice('')
    setError('')
    setConflict('')
    try {
      await operation()
    } catch (failure) {
      setError(errorText(failure))
      if (related && failure instanceof ApiError && (failure.status === 409 || failure.status === 404)) setConflict(related)
    } finally {
      lock.current = false
      setBusy(false)
    }
  }

  function selectTab(id: string) {
    setCurrentId(id)
    setEditor(true)
    setDetail(null)
  }

  function openFile(entry: Entry) {
    const id = fileKey(workspace, entry.path)
    if (tabs.some(tab => tab.id === id)) {
      selectTab(id)
      return
    }
    if (tabs.length >= 8) {
      setError('Close a file before opening another. Nexus keeps up to eight files open.')
      return
    }
    void run(async () => {
      const data = await api<FileData>(`${fileApi(workspace)}/file${query(entry.path)}`)
      setTabs(previous => [...previous, { ...data, id, workspace, draft: data.content, epoch: 0 }])
      selectTab(id)
    })
  }

  function closeTab(tab: FileTab) {
    const close = () => {
      setTabs(previous => previous.filter(item => item.id !== tab.id))
      if (tab.id === currentId) {
        const replacement = openTabs.find(item => item.id !== tab.id)
        setCurrentId(replacement?.id ?? '')
        if (!replacement) { setEditor(false); setFull(false) }
      }
    }
    if (tab.draft !== tab.content) {
      setConfirm({ title: 'Discard unsaved changes?', detail: `The local edits to ${leaf(tab.path)} will be lost.`, action: 'Discard and close', onConfirm: close })
    } else close()
  }

  function save(id: string) {
    const tab = tabs.find(item => item.id === id)
    if (!tab || tab.draft === tab.content) return
    void run(async () => {
      const saved = await api<{ digest: string; size: number }>(`${fileApi(tab.workspace)}/file`, {
        method: 'PUT', body: { path: tab.path, expected: tab.digest, content: tab.draft },
      })
      setTabs(previous => previous.map(item => item.id === id ? { ...item, ...saved, content: tab.draft } : item))
      changed(`Saved ${leaf(tab.path)}`)
    }, id)
  }

  function reload(tab: FileTab) {
    const load = () => void run(async () => {
      const data = await api<FileData>(`${fileApi(tab.workspace)}/file${query(tab.path)}`)
      setTabs(previous => previous.map(item => item.id === tab.id ? { ...item, ...data, draft: data.content, epoch: item.epoch + 1 } : item))
      setNotice(`Reloaded ${leaf(tab.path)}`)
    })
    if (tab.draft !== tab.content) {
      setConfirm({ title: 'Reload from disk?', detail: `This will discard your local edits to ${leaf(tab.path)}.`, action: 'Discard and reload', onConfirm: load })
    } else load()
  }

  function chooseFolder(next: string) {
    setPath(next)
    setSelected(null)
    setForm(null)
    setEditor(false)
    setFull(false)
    setDetail(null)
  }

  function switchWorkspace(next: string) {
    setChosen(next)
    chooseFolder('')
    setCurrentId('')
    setForm(null)
    setError('')
    setNotice('')
    setConflict('')
  }

  function inEntry(tab: FileTab, entry: Entry) {
    return tab.workspace === workspace && (tab.path === entry.path || (entry.directory && tab.path.startsWith(entry.path + '/')))
  }

  function submitEntry(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!form) return
    const name = form.name
    if (name !== name.trim() || name.includes('/') || name.includes('\\')) {
      setError('Enter a single file or folder name.')
      return
    }
    void run(async () => {
      if (form.kind === 'rename' && selected) {
        if (tabs.some(tab => inEntry(tab, selected) && tab.draft !== tab.content)) {
          throw new Error('Save or close the unsaved tabs before renaming this entry.')
        }
        await api(`${fileApi(workspace)}/entry`, { method: 'PATCH', body: { path: selected.path, name } })
        if (current && inEntry(current, selected)) { setEditor(false); setFull(false) }
        setTabs(previous => previous.filter(tab => !inEntry(tab, selected)))
        if (path === selected.path || path.startsWith(selected.path + '/')) chooseFolder(parentPath(selected.path))
        changed(`Renamed to ${name}`)
      } else {
        const newPath = path ? `${path}/${name}` : name
        await api(`${fileApi(workspace)}/entry`, { method: 'POST', body: { path: newPath, directory: form.kind === 'directory' } })
        changed(`Created ${name}`)
      }
      setForm(null)
      setSelected(null)
    })
  }

  function remove(entry: Entry) {
    if (tabs.some(tab => inEntry(tab, entry) && tab.draft !== tab.content)) {
      setError('Save or close the unsaved tabs before deleting this entry.')
      return
    }
    void run(async () => {
      const latest = entry.directory ? null : await api<FileData>(`${fileApi(workspace)}/file${query(entry.path)}`)
      setConfirm({
        title: `Delete ${entry.directory ? 'folder' : 'file'}?`,
        detail: entry.directory ? `${entry.path} will be removed if it is empty.` : `${entry.path} will be deleted. Its current contents will be kept as a revision.`,
        action: 'Delete',
        onConfirm: () => void run(async () => {
          await api(`${fileApi(workspace)}/entry`, { method: 'DELETE', body: { path: entry.path, expected: latest?.digest } })
          if (current && inEntry(current, entry)) { setEditor(false); setFull(false) }
          if (path === entry.path || path.startsWith(entry.path + '/')) chooseFolder(parentPath(entry.path))
          setTabs(previous => previous.filter(tab => !inEntry(tab, entry)))
          setSelected(null)
          changed(`Deleted ${entry.name}`)
        }),
      })
    })
  }

  function showHistory(target: string) {
    setRevisionPath(target)
    setRevisionQuery(target)
    setEditor(false)
    setFull(false)
    setDetail('revisions')
  }

  function restore(revision: Revision) {
    const target = revisionQuery
    setConfirm({
      title: 'Restore this revision?',
      detail: `Restore ${target} to its contents at ${dateTime(revision.timestamp)}. Any unsaved edits in its open tab will be discarded.`,
      action: 'Restore revision',
      onConfirm: () => void run(async () => {
        const id = fileKey(workspace, target)
        const tab = tabs.find(item => item.id === id)
        let previous: FileData | undefined
        try { previous = await api<FileData>(`${fileApi(workspace)}/file${query(target)}`) }
        catch (failure) { if (!(failure instanceof ApiError && failure.status === 404)) throw failure }
        await api(`${fileApi(workspace)}/rollback`, {
          method: 'POST', body: { path: target, revision: revision.id, expected: previous?.digest ?? null },
        })
        if (tab) {
          const data = await api<FileData>(`${fileApi(workspace)}/file${query(target)}`)
          setTabs(items => items.map(item => item.id === id ? { ...item, ...data, draft: data.content, epoch: item.epoch + 1 } : item))
        }
        changed(`Restored ${leaf(target)}`)
      }),
    })
  }

  const props = { workspace, path, generation, active: active && !!workspace, chooseFolder, openFile }

  return <div data-unsaved={dirty}>
    <header className="page-heading files-heading">
      <div><div className="page-kicker"><FolderCode size={14}/> Workspace</div><h1>Files</h1><p>Browse and edit files in your configured workspaces.</p></div>
      {workspace && <div className="heading-actions">
        <select aria-label="Workspace" value={workspace} onChange={event => switchWorkspace(event.target.value)} disabled={busy}>
          {workspaces.data?.workspaces.map(name => <option key={name}>{name}</option>)}
        </select>
        <Button variant="outline" onClick={() => { setDetail(detail === 'audit' ? null : 'audit'); setEditor(false); setFull(false) }}><ClipboardList size={16}/> Audit</Button>
      </div>}
    </header>
    {workspaces.error && <Failure detail={workspaces.error} retry={workspaces.refresh}/>}
    {workspaces.loading && !workspace && <Skeleton height={240}/>}
    {workspaces.data?.workspaces.length === 0 && <div className="panel"><Empty icon={FolderCode} title="No workspaces configured" detail="Add an authorized project directory to the Nexus workspace configuration." /></div>}
    {workspace && <>
      <div className="file-layout">
        <WorkspaceTree key={workspace} {...props}/>
        <div className="file-main">
          <div className="file-actions">
            <Button variant="outline" size="small" disabled={busy} onClick={() => { setForm({ kind: 'file', name: '' }); setEditor(false); setFull(false); setDetail(null) }}><FilePlus2 size={15}/> New file</Button>
            <Button variant="outline" size="small" disabled={busy} onClick={() => { setForm({ kind: 'directory', name: '' }); setEditor(false); setFull(false); setDetail(null) }}><FolderPlus size={15}/> New folder</Button>
            <Button variant="ghost" size="small" onClick={() => showHistory(current?.path ?? '')}><History size={15}/> Revisions</Button>
            {!!openTabs.length && !editor && <Button variant="ghost" size="small" onClick={() => selectTab(current?.id ?? openTabs[0].id)}>Open tabs ({openTabs.length})</Button>}
          </div>
          {!showEditor && error && <Failure detail={error}/>}
          {!showEditor && notice && <div className="file-notice" role="status">{notice}</div>}
          {!showEditor && form && <form className="entry-form panel" onSubmit={submitEntry}>
            <label>{form.kind === 'rename' ? 'New name' : form.kind === 'file' ? 'File name' : 'Folder name'}
              <input autoFocus required value={form.name} onChange={event => setForm({ ...form, name: event.target.value })}
                maxLength={255} placeholder={form.kind === 'file' ? 'notes.md' : 'Name'}/>
            </label>
            <Button type="submit" disabled={busy}>{form.kind === 'rename' ? 'Rename' : 'Create'}</Button>
            <Button type="button" variant="ghost" onClick={() => setForm(null)}>Cancel</Button>
          </form>}
          {!showEditor && detail && <section className="panel detail-panel">
            <div className="panel-head"><div><h2>{detail === 'audit' ? 'Modification audit' : 'Revision history'}</h2><p>{detail === 'audit' ? 'File and folder operations for this workspace' : 'Look up a current or deleted file by its workspace-relative path.'}</p></div>
              <Button variant="ghost" size="icon" aria-label="Close details" onClick={() => setDetail(null)}><X size={17}/></Button></div>
            <div className="inset">
              {detail === 'audit' ? <AuditList key={`${workspace}:${generation}`} workspace={workspace}/> : <>
                <form className="revision-form" onSubmit={event => { event.preventDefault(); setRevisionQuery(revisionPath) }}>
                  <input aria-label="Revision file path" placeholder="src/main.py" value={revisionPath} onChange={event => setRevisionPath(event.target.value)} required maxLength={2048}/>
                  <Button type="submit" variant="outline">Find revisions</Button>
                </form>
                <RevisionList workspace={workspace} path={revisionQuery} generation={generation} restore={restore} disabled={busy}/>
              </>}
            </div>
          </section>}
          {!showEditor && !detail && <>
            {selected && <div className="selection-actions panel">
              <strong title={selected.path}>{selected.name}</strong>
              <div>
                <Button variant="ghost" size="small" disabled={busy} onClick={() => setForm({ kind: 'rename', name: selected.name })}><Pencil size={14}/> Rename</Button>
                {selected.editable && <>
                  <Button variant="ghost" size="small" asChild><a href={`/api${fileApi(workspace)}/download${query(selected.path)}`} download><Download size={14}/> Download</a></Button>
                  <Button variant="ghost" size="small" onClick={() => showHistory(selected.path)}><History size={14}/> History</Button>
                </>}
                <Button variant="ghost" size="small" disabled={busy} onClick={() => remove(selected)}><Trash2 size={14}/> Delete</Button>
              </div>
            </div>}
            <DirectoryBrowser key={workspace} props={props} selected={selected?.path ?? null} setSelected={setSelected}/>
          </>}
          <section hidden={!showEditor} className={`panel editor-shell ${full ? 'fullscreen' : ''}`} aria-label="Code editor" aria-busy={busy}>
            {current && <>
            <div className="editor-header">
              <Button variant="ghost" size="icon" aria-label="Back to files" onClick={() => { setEditor(false); setFull(false) }}><ArrowLeft size={17}/></Button>
              <span className="editor-title mono" title={current.path}>{current.path}</span>
              <Button variant="ghost" size="icon" aria-label="File revisions" title="File revisions" onClick={() => showHistory(current.path)}><History size={17}/></Button>
              <Button variant="ghost" size="icon" aria-label={full ? 'Exit fullscreen' : 'Fullscreen'} onClick={() => setFull(value => !value)}>{full ? <Minimize size={17}/> : <Maximize size={17}/>}</Button>
            </div>
            <div className="file-tabs" role="group" aria-label="Open files">
              {openTabs.map(tab => <div className={`file-tab ${currentId === tab.id ? 'current' : ''}`} key={tab.id}>
                <button aria-pressed={currentId === tab.id} onClick={() => selectTab(tab.id)} title={tab.path}>{leaf(tab.path)}{tab.content !== tab.draft && <span className="unsaved-dot" aria-label="Unsaved changes"/>}</button>
                <button disabled={busy} aria-label={`Close ${leaf(tab.path)}`} onClick={() => closeTab(tab)}><X size={13}/></button>
              </div>)}
            </div>
            {error && <div className="editor-message"><Failure detail={error}/>{conflict === current.id && <Button variant="outline" size="small" disabled={busy} onClick={() => reload(current)}>Reload from disk</Button>}</div>}
            </>}
            <div className="live-editors">
            <Suspense fallback={<Skeleton height={300}/>}>
              {tabs.map(tab => <CodeEditor key={`${tab.id}:${tab.epoch}`} initial={tab.draft} name={leaf(tab.path)}
                language={tab.language} active={showEditor && tab.id === currentId}
                onSave={() => save(tab.id)} onEdit={draft => { setTabs(previous => previous.map(item => item.id === tab.id ? { ...item, draft } : item)); setNotice('') }}/>)}
            </Suspense>
            </div>
            {current && <div className="editor-footer"><span className="mono">{current.draft !== current.content ? 'Unsaved changes' : notice || `${current.language} · ${bytes(current.size)}`}</span>
              <Button disabled={busy || current.draft === current.content} onClick={() => save(current.id)}><Save size={16}/> Save file</Button>
            </div>}
          </section>
        </div>
      </div>
    </>}
    <Confirm confirm={confirm} dismiss={() => setConfirm(null)}/>
  </div>
}
