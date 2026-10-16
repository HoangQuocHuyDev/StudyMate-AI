import { useEffect, useState } from 'react'
import { useAuth } from '../../contexts/AuthContext'
import { getDisplayName, getRoleLabel, getUserInitials } from '../../utils/userDisplay'
import Icon from '../Icons'
import AdminDocuments from './AdminDocuments'
import AdminOverview from './AdminOverview'
import AdminSidebar from './AdminSidebar'
import AdminUsers from './AdminUsers'
import './Admin.css'


const viewTitles = {
  overview: { eyebrow: 'Trung tâm điều hành', title: 'Tổng quan quản trị' },
  users: { eyebrow: 'Tài khoản hệ thống', title: 'Quản lý người dùng' },
  documents: { eyebrow: 'Dữ liệu học tập', title: 'Quản lý tài liệu' },
}

function AdminDashboard() {
  const { user, isAuthenticated } = useAuth()
  const [activeView, setActiveView] = useState('overview')
  const [isSidebarOpen, setIsSidebarOpen] = useState(false)
  const title = viewTitles[activeView]
  const currentUser = isAuthenticated ? user : null
  const displayName = getDisplayName(currentUser)
  const roleLabel = getRoleLabel(currentUser)
  const userInitials = getUserInitials(currentUser)

  useEffect(() => {
    if (!isSidebarOpen) return undefined
    const handleKeyDown = (event) => event.key === 'Escape' && setIsSidebarOpen(false)
    document.addEventListener('keydown', handleKeyDown)
    document.body.classList.add('admin-sidebar-visible')
    return () => {
      document.removeEventListener('keydown', handleKeyDown)
      document.body.classList.remove('admin-sidebar-visible')
    }
  }, [isSidebarOpen])

  return (
    <div className="admin-shell">
      <AdminSidebar activeView={activeView} isOpen={isSidebarOpen} onChangeView={setActiveView} onClose={() => setIsSidebarOpen(false)} />
      <button className={`admin-overlay ${isSidebarOpen ? 'admin-overlay--visible' : ''}`} type="button" onClick={() => setIsSidebarOpen(false)} aria-label="Đóng thanh điều hướng quản trị" tabIndex={isSidebarOpen ? 0 : -1} />

      <div className="admin-main">
        <header className="admin-header">
          <div className="admin-header__title">
            <button type="button" onClick={() => setIsSidebarOpen(true)} aria-label="Mở thanh điều hướng quản trị"><Icon name="menu" size={21} /></button>
            <div><p>{title.eyebrow}</p><h1>{title.title}</h1></div>
          </div>
          <div className="admin-header__right">
            <span className="admin-role-badge"><Icon name="shield" size={15} />ADMIN</span>
            <div className="admin-profile"><span>{userInitials}</span><div><strong>{displayName}</strong><small>{roleLabel}</small></div></div>
          </div>
        </header>

        <main className="admin-content">
          {activeView === 'overview' && <AdminOverview displayName={displayName} onNavigate={setActiveView} />}
          {activeView === 'users' && <AdminUsers />}
          {activeView === 'documents' && <AdminDocuments />}
        </main>
      </div>
    </div>
  )
}

export default AdminDashboard
