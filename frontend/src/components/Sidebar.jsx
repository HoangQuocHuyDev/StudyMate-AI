import Icon from './Icons'

const navigation = [
  { label: 'Tổng quan', icon: 'overview', href: '/' },
  { label: 'Tài liệu của tôi', icon: 'documents', href: '/documents' },
  { label: 'Tóm tắt tài liệu', icon: 'summary', href: '/summarize' },
  { label: 'Hỏi đáp AI', icon: 'chat', href: '/chat' },
  { label: 'Lịch sử trò chuyện', icon: 'history', href: '/history' },
]

function Sidebar({ isOpen, onClose }) {
  const currentPath = window.location.pathname.replace(/\/$/, '') || '/'
  const isSettingsActive = currentPath === '/settings'

  return (
    <aside className={`sidebar ${isOpen ? 'sidebar--open' : ''}`} aria-label="Điều hướng chính">
      <div className="sidebar__brand">
        <div className="brand-mark" aria-hidden="true"><span>S</span><i /></div>
        <div className="brand-name"><strong>StudyMate</strong><span>AI</span></div>
        <button className="icon-button sidebar__close" type="button" onClick={onClose} aria-label="Đóng thanh điều hướng"><Icon name="close" /></button>
      </div>

      <nav className="sidebar__nav">
        <p className="nav-label">Không gian học tập</p>
        {navigation.map((item) => {
          const isActive = item.href === currentPath
          const className = `nav-item ${isActive ? 'nav-item--active' : ''}`
          const content = <><Icon name={item.icon} /><span>{item.label}</span></>

          return item.href ? (
            <a className={className} href={item.href} key={item.label} onClick={onClose} aria-current={isActive ? 'page' : undefined}>{content}</a>
          ) : (
            <button className={className} type="button" key={item.label} onClick={onClose}>{content}</button>
          )
        })}
      </nav>

      <div className="sidebar__bottom">
        <a className={`nav-item ${isSettingsActive ? 'nav-item--active' : ''}`} href="/settings" onClick={onClose} aria-current={isSettingsActive ? 'page' : undefined}><Icon name="settings" /><span>Cài đặt</span></a>
      </div>
    </aside>
  )
}

export default Sidebar
