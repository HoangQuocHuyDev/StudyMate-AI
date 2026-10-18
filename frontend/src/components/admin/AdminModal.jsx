import { useEffect, useRef } from 'react'
import Icon from '../Icons'

function AdminModal({ title, eyebrow, children, onClose, confirm }) {
  const dialogRef = useRef(null)
  const onCloseRef = useRef(onClose)

  useEffect(() => {
    onCloseRef.current = onClose
  }, [onClose])

  useEffect(() => {
    const previouslyFocused = document.activeElement
    const dialog = dialogRef.current
    const focusableSelector = 'button:not(:disabled), [href], input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex]:not([tabindex="-1"])'
    const initialTarget = dialog?.querySelector(focusableSelector) ?? dialog
    initialTarget?.focus()

    const handleKeyDown = (event) => {
      if (event.key === 'Escape') {
        onCloseRef.current()
        return
      }
      if (event.key !== 'Tab' || !dialog) return

      const focusable = Array.from(dialog.querySelectorAll(focusableSelector))
      if (focusable.length === 0) {
        event.preventDefault()
        dialog.focus()
        return
      }
      const first = focusable[0]
      const last = focusable.at(-1)
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault()
        first.focus()
      }
    }
    document.addEventListener('keydown', handleKeyDown)
    document.body.classList.add('admin-modal-visible')
    return () => {
      document.removeEventListener('keydown', handleKeyDown)
      document.body.classList.remove('admin-modal-visible')
      if (previouslyFocused instanceof HTMLElement && previouslyFocused.isConnected) {
        previouslyFocused.focus()
      }
    }
  }, [])

  return (
    <div className="admin-modal" role="presentation" onMouseDown={onClose}>
      <section className={`admin-dialog ${confirm ? 'admin-dialog--confirm' : ''}`} ref={dialogRef} tabIndex="-1" role={confirm ? 'alertdialog' : 'dialog'} aria-modal="true" aria-labelledby="admin-dialog-title" onMouseDown={(event) => event.stopPropagation()}>
        {confirm ? (
          children
        ) : (
          <>
            <header className="admin-dialog__header">
              <div><p>{eyebrow}</p><h2 id="admin-dialog-title">{title}</h2></div>
              <button type="button" onClick={onClose} aria-label="Đóng hộp thoại"><Icon name="close" size={20} /></button>
            </header>
            <div className="admin-dialog__body">{children}</div>
          </>
        )}
      </section>
    </div>
  )
}

export default AdminModal
