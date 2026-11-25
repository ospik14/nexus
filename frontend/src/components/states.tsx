import { CircleAlert, Inbox } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { Button } from './ui/button'

export function Empty({ title, detail, icon: Icon = Inbox }: { title: string; detail: string; icon?: LucideIcon }) {
  return <div className="empty"><span className="empty-icon"><Icon size={21}/></span><strong>{title}</strong><p>{detail}</p></div>
}

export function Failure({ detail, retry }: { detail: string; retry?: () => void }) {
  return <div className="failure" role="alert"><CircleAlert size={17}/><span>{detail}</span>
    {retry && <Button variant="outline" size="small" onClick={retry}>Retry</Button>}
  </div>
}

export function Skeleton({ height = 90, count = 1 }: { height?: number; count?: number }) {
  return <div className="skeleton-stack" role="status" aria-label="Loading">
    {Array.from({ length: count }, (_, index) => <span key={index} className="skeleton" style={{ height }}/>)}
  </div>
}
