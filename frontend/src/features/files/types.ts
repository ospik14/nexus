export interface Entry {
  name: string
  path: string
  directory: boolean
  size: number | null
  modified: number
  editable: boolean
}
export interface Listing { entries: Entry[]; limited: boolean }
export interface FileData {
  path: string
  content: string
  digest: string
  language: string
  size: number
  modified: number
}
export interface FileTab extends FileData {
  id: string
  workspace: string
  draft: string
  epoch: number
}
export interface Revision { id: number; timestamp: number; size: number; digest: string }
export interface AuditEvent {
  id: number; timestamp: number; actor: string; action: string; path: string; target: string | null; result: string
}
export const leaf = (path: string) => path.split('/').at(-1)!
export const parentPath = (path: string) => path.split('/').slice(0, -1).join('/')
export const fileKey = (workspace: string, path: string) => `${workspace}:${path}`
export const query = (path: string) => `?path=${encodeURIComponent(path)}`
export const fileApi = (workspace: string) => `/files/${encodeURIComponent(workspace)}`
