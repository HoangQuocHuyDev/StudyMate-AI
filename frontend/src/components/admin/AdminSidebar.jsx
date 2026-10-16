import Icon from '../Icons'
import { useAuth } from '../../contexts/AuthContext'
import { useNavigation } from '../../navigation/NavigationContext'
import { ADMIN_NAVIGATION } from './adminDashboardUi'

function AdminSidebar({ activeView, isOpen, onChangeView, onClose }) {
  const { isLoggingOut, logoutWithRevocation } = useAuth()
  const { navigate } = useNavigation()

  const handleLogout = async () => {
    if (isLoggingOut) return
    onClose()
    const sessionWasCleared = await logoutWithRevocation()
    if (sessionWasCleared) navigate('/login', { replace: true })
  }

  return (
    <aside className={`admin-sidebar ${isOpen ? 'admin-sidebar--open' : ''}`} aria-label="Điều hướng quản trị">
      <div className="admin-brand">
        <div className="admin-brand__mark"><Icon name="shield" size={21} /></div>
        <div className="admin-brand__copy">
          <div className="admin-brand__name"><strong>StudyMate</strong><span>AI</span></div>
          <small>Quản trị hệ thống</small>
        </div>
        <button type="button" onClick={onClose} aria-label="Đóng thanh điều hướng"><Icon name="close" size={20} /></button>
      </div>

      <nav className="admin-nav">
        <p>Không gian quản trị</p>
        {ADMIN_NAVIGATION.map((item) => (
          <button className={activeView === item.id ? 'admin-nav__item admin-nav__item--active' : 'admin-nav__item'} type="button" key={item.id} onClick={() => { onChangeView(item.id); onClose() }} aria-current={activeView === item.id ? 'page' : undefined}>
            <Icon name={item.icon} size={19} /><span>{item.label}</span>
          </button>
        ))}
      </nav>

      <div className="admin-sidebar__notice"><Icon name="shield" size={17} /><p><strong>Dữ liệu hệ thống</strong><span>Quyền quản trị được xác minh qua tài khoản hiện tại.</span></p></div>
      <button className="admin-back-link admin-user-view-link" type="button" onClick={() => { onClose(); navigate('/') }}><Icon name="arrow" size={17} />Về giao diện người dùng</button>
      <button className="admin-back-link admin-logout-button" type="button" onClick={handleLogout} disabled={isLoggingOut}><Icon name="logout" size={17} />{isLoggingOut ? 'Đang đăng xuất...' : 'Đăng xuất'}</button>
    </aside>
  )
}

export default AdminSidebar
