import * as AlertDialog from '@radix-ui/react-alert-dialog'
import { Button } from './ui/button'

export interface Confirmation {
  title: string
  detail: string
  action: string
  onConfirm: () => void
}

export function Confirm({ confirm, dismiss }: { confirm: Confirmation | null; dismiss: () => void }) {
  return <AlertDialog.Root open={!!confirm} onOpenChange={open => { if (!open) dismiss() }}>
    <AlertDialog.Portal>
      <AlertDialog.Overlay className="dialog-overlay"/>
      {confirm && <AlertDialog.Content className="dialog">
        <AlertDialog.Title>{confirm.title}</AlertDialog.Title>
        <AlertDialog.Description>{confirm.detail}</AlertDialog.Description>
        <div className="dialog-actions">
          <AlertDialog.Cancel asChild><Button variant="outline">Cancel</Button></AlertDialog.Cancel>
          <AlertDialog.Action asChild><Button variant="destructive" onClick={confirm.onConfirm}>{confirm.action}</Button></AlertDialog.Action>
        </div>
      </AlertDialog.Content>}
    </AlertDialog.Portal>
  </AlertDialog.Root>
}
