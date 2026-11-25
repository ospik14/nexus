import { ChevronDown, ChevronRight, FileCode2, Folder, FolderOpen, Search } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Empty, Failure, Skeleton } from '../../components/states'
import { useEndpoint } from '../../lib/api'
import { bytes, dateTime } from '../../lib/format'
import { fileApi, query } from './types'
import type { Entry, Listing } from './types'

interface BrowserProps {
  workspace: string
  path: string
  generation: number
  active: boolean
  chooseFolder: (path: string) => void
  openFile: (entry: Entry) => void
}

function Branch({ entry, props, depth, expanded, toggle }: {
  entry: Entry; props: BrowserProps; depth: number; expanded: Set<string>; toggle: (path: string) => void;
}) {
  const open = expanded.has(entry.path)
  const active = props.path === entry.path
  const Icon = open ? FolderOpen : Folder
  return <li>
    <div className={`tree-row ${active ? 'current' : ''}`} style={{ paddingInlineStart: `${Math.min(8, depth) * 10}px` }}>
      <button className="tree-toggle" aria-pressed={open} aria-label={`${open ? 'Collapse' : 'Expand'} ${entry.name}`} onClick={() => toggle(entry.path)}>
        {open ? <ChevronDown size={14}/> : <ChevronRight size={14}/>}
      </button>
      <button title={entry.path} className="tree-name" onClick={() => { props.chooseFolder(entry.path); if (!open) toggle(entry.path) }}>
        <Icon size={15}/><span>{entry.name}</span>
      </button>
    </div>
    {open && <BranchChildren path={entry.path} props={props} depth={depth + 1} expanded={expanded} toggle={toggle}/>}
  </li>
}

function BranchChildren({ path, props, depth, expanded, toggle }: {
  path: string; props: BrowserProps; depth: number; expanded: Set<string>; toggle: (path: string) => void;
}) {
  const { data, loading, error, refresh } = useEndpoint<Listing>(props.active
    ? `${fileApi(props.workspace)}/tree${query(path)}&v=${props.generation}` : null)
  if (loading) return <div className="tree-loading"><Skeleton height={19}/></div>
  if (error) return <button className="tree-warning" onClick={refresh}>Could not load folders · Retry</button>
  return <ul className="file-tree">{data?.entries.filter(item => item.directory).map(entry =>
    <Branch key={entry.path} entry={entry} props={props} depth={depth} expanded={expanded} toggle={toggle}/>)}</ul>
}

export function WorkspaceTree(props: BrowserProps) {
  const [expanded, setExpanded] = useState(() => new Set<string>())
  const rootName = props.workspace
  function toggle(path: string) {
    setExpanded(previous => {
      const next = new Set(previous)
      if (next.has(path)) {
        for (const item of next) if (item === path || item.startsWith(path + '/')) next.delete(item)
      } else if (next.size < 20) {
        next.add(path)
      }
      return next
    })
  }
  return <aside className="panel workspace-tree">
    <div className="tree-heading">Explorer</div>
    <button className={`tree-root ${props.path === '' ? 'current' : ''}`} onClick={() => props.chooseFolder('')}><FolderOpen size={17}/><span>{rootName}</span></button>
    <BranchChildren path="" props={props} depth={0} expanded={expanded} toggle={toggle}/>
  </aside>
}

export function DirectoryBrowser({ props, selected, setSelected }: {
  props: BrowserProps; selected: string | null; setSelected: (entry: Entry | null) => void;
}) {
  const [search, setSearch] = useState('')
  const [term, setTerm] = useState('')
  useEffect(() => {
    const timer = setTimeout(() => setTerm(search.trim()), 250)
    return () => clearTimeout(timer)
  }, [search])
  const endpoint = !props.active ? null : term ? `${fileApi(props.workspace)}/search?q=${encodeURIComponent(term)}&v=${props.generation}`
    : `${fileApi(props.workspace)}/tree${query(props.path)}&v=${props.generation}`
  const { data, error, loading, refresh } = useEndpoint<Listing>(endpoint)
  const segments = props.path ? props.path.split('/') : []

  function choose(path: string) {
    setSearch('')
    setTerm('')
    setSelected(null)
    props.chooseFolder(path)
  }

  return <section className="panel directory-browser" aria-label="Workspace files">
    <div className="browser-heading">
      <nav className="crumbs" aria-label="Workspace breadcrumbs">
        <button onClick={() => choose('')} title={props.workspace}><Folder size={15}/><span>{props.workspace}</span></button>
        {segments.map((segment, index) => <span key={index}><ChevronRight size={13}/>
          <button title={segment} onClick={() => choose(segments.slice(0, index + 1).join('/'))}>{segment}</button>
        </span>)}
      </nav>
      <label className="search-input"><Search size={16}/><input aria-label="Search by filename" placeholder="Find a file…" value={search} onChange={event => setSearch(event.target.value)} maxLength={100}/></label>
    </div>
    {error && <div className="inset"><Failure detail={error} retry={refresh}/></div>}
    {loading && <div className="inset"><Skeleton height={36} count={4}/></div>}
    {data?.limited && <p className="list-limit">Showing a limited set of entries. Narrow the search or browse a smaller directory.</p>}
    {data?.entries.length === 0 && <Empty title={term ? 'No matching entries' : 'This folder is empty'} detail={term ? 'Try a shorter or different search term.' : 'Create a file or folder from the workspace toolbar.'} icon={Folder}/>}
    {!!data?.entries.length && <div className="entry-list">
      <div className="entry-columns"><span>Name</span><span>Size</span><span>Modified</span><span>Actions</span></div>
      {data.entries.map(entry => {
        const Icon = entry.directory ? Folder : FileCode2
        return <div className={`entry-row ${selected === entry.path ? 'current' : ''}`} key={entry.path}>
          <button className="entry-name" title={entry.path} disabled={!entry.directory && !entry.editable}
            onClick={() => entry.directory ? choose(entry.path) : props.openFile(entry)}>
            <Icon size={17}/><span><strong>{entry.name}</strong>{term && entry.path !== entry.name && <small>{entry.path}</small>}</span>
          </button>
          <span className="entry-size mono">{entry.directory ? '—' : bytes(entry.size)}</span>
          <time className="entry-date" dateTime={new Date(entry.modified * 1000).toISOString()}>{dateTime(entry.modified)}</time>
          <button className="entry-options" aria-pressed={selected === entry.path} aria-label={`Actions for ${entry.name}`} onClick={() => setSelected(selected === entry.path ? null : entry)}>•••</button>
        </div>
      })}
    </div>}
  </section>
}
