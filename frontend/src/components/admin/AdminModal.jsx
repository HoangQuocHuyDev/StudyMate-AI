import { useEffect } from 'react'
import Icon from '../Icons'

function AdminModal({ title, eyebrow, children, onClose, confirm }) {
  useEffect(() => {
    const handleKeyDown = (event) => event.key === 'Escape' && onClose()
    document.addEventListener('keydown', handleKeyDown)
    document.body.classList.add('admin-modal-visible')
    return () => {
      document.removeEventListener('keydown', handleKeyDown)
      document.body.classList.remove('admin-modal-visible')
    }
  }, [onClose])

  return (
    <div className="admin-modal" role="presentation" onMouseDown={onClose}>
      <section className={`admin-dialog ${confirm ? 'admin-dialog--confirm' : ''}`} role={confirm ? 'alertdialog' : 'dialog'} aria-modal="true" aria-labelledby="admin-dialog-title" onMouseDown={(event) => event.stopPropagation()}>
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
