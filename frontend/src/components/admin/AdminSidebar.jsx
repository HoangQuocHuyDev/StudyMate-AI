import Icon from '../Icons'

const items = [
  { id: 'overview', label: 'Tổng quan', icon: 'overview' },
  { id: 'users', label: 'Quản lý người dùng', icon: 'users' },
  { id: 'documents', label: 'Quản lý tài liệu', icon: 'documents' },
]

function AdminSidebar({ activeView, isOpen, onChangeView, onClose }) {
  return (
    <aside className={`admin-sidebar ${isOpen ? 'admin-sidebar--open' : ''}`} aria-label="Điều hướng quản trị">
      <div className="admin-brand">
        <div className="admin-brand__mark"><Icon name="shield" size={21} /></div>
        <div><strong>StudyMate</strong><span>Quản trị viên</span></div>
        <button type="button" onClick={onClose} aria-label="Đóng thanh điều hướng"><Icon name="close" size={20} /></button>
      </div>

      <nav className="admin-nav">
        <p>Không gian quản trị</p>
        {items.map((item) => (
          <button className={activeView === item.id ? 'admin-nav__item admin-nav__item--active' : 'admin-nav__item'} type="button" key={item.id} onClick={() => { onChangeView(item.id); onClose() }} aria-current={activeView === item.id ? 'page' : undefined}>
            <Icon name={item.icon} size={19} /><span>{item.label}</span>
          </button>
        ))}
      </nav>

      <div className="admin-sidebar__notice"><Icon name="shield" size={17} /><p><strong>Chế độ phát triển</strong><span>Chưa áp dụng xác thực và phân quyền thực tế.</span></p></div>
      <a className="admin-back-link" href="/"><Icon name="arrow" size={17} />Về giao diện sinh viên</a>
    </aside>
  )
}

export default AdminSidebar
