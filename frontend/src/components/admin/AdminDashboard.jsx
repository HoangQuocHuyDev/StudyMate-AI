import { useEffect, useState } from 'react'
import Icon from '../Icons'
import AdminDocuments from './AdminDocuments'
import AdminOverview from './AdminOverview'
import AdminSidebar from './AdminSidebar'
import AdminUsers from './AdminUsers'
import './Admin.css'

const initialUsers = [
  { id: 1, name: 'Minh Nguyễn', username: 'minhnguyen', initials: 'MN', role: 'student', status: 'active', createdAt: '12/09/2026', documents: 14, sessions: 38 },
  { id: 2, name: 'Nguyễn Hoàng Anh', username: 'hoanganh_02', initials: 'HA', role: 'student', status: 'active', createdAt: '28/09/2026', documents: 8, sessions: 21 },
  { id: 3, name: 'Trần Thu Hà', username: 'thuhatran', initials: 'TH', role: 'student', status: 'locked', createdAt: '16/08/2026', documents: 6, sessions: 17 },
  { id: 4, name: 'Lê Quốc Bảo', username: 'bao_le', initials: 'QB', role: 'student', status: 'active', createdAt: '03/10/2026', documents: 3, sessions: 9 },
  { id: 5, name: 'Phạm Mai Linh', username: 'admin_linh', initials: 'ML', role: 'admin', status: 'active', createdAt: '01/07/2026', documents: 0, sessions: 2 },
  { id: 6, name: 'Võ Đức Thành', username: 'ducthanh99', initials: 'ĐT', role: 'student', status: 'active', createdAt: '21/09/2026', documents: 11, sessions: 30 },
]

const initialDocuments = [
  { id: 1, name: 'Giáo trình Trí tuệ nhân tạo', owner: 'Minh Nguyễn', type: 'PDF', size: '4,8 MB', uploadedAt: '08/10/2026', status: 'complete' },
  { id: 2, name: 'Bài giảng Kinh tế vi mô', owner: 'Nguyễn Hoàng Anh', type: 'DOCX', size: '1,2 MB', uploadedAt: '07/10/2026', status: 'complete' },
  { id: 3, name: 'Ghi chú Cấu trúc dữ liệu', owner: 'Võ Đức Thành', type: 'TXT', size: '18 KB', uploadedAt: '06/10/2026', status: 'processing' },
  { id: 4, name: 'Nhập môn Machine Learning', owner: 'Minh Nguyễn', type: 'PDF', size: '3,1 MB', uploadedAt: '05/10/2026', status: 'complete' },
  { id: 5, name: 'Tổng hợp câu hỏi Pháp luật', owner: 'Lê Quốc Bảo', type: 'DOCX', size: '840 KB', uploadedAt: '03/10/2026', status: 'error' },
  { id: 6, name: 'Từ vựng tiếng Anh chuyên ngành', owner: 'Trần Thu Hà', type: 'TXT', size: '26 KB', uploadedAt: '30/09/2026', status: 'complete' },
]

const viewTitles = {
  overview: { eyebrow: 'Trung tâm điều hành', title: 'Tổng quan quản trị' },
  users: { eyebrow: 'Tài khoản hệ thống', title: 'Quản lý người dùng' },
  documents: { eyebrow: 'Dữ liệu học tập', title: 'Quản lý tài liệu' },
}

function AdminDashboard() {
  const [activeView, setActiveView] = useState('overview')
  const [isSidebarOpen, setIsSidebarOpen] = useState(false)
  const [users, setUsers] = useState(initialUsers)
  const [documents, setDocuments] = useState(initialDocuments)
  const title = viewTitles[activeView]

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

  const toggleUserStatus = (id) => {
    setUsers((current) => current.map((user) => user.id === id ? { ...user, status: user.status === 'active' ? 'locked' : 'active' } : user))
  }

  const deleteDocument = (id) => {
    setDocuments((current) => current.filter((document) => document.id !== id))
  }

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
            <span className="admin-demo-badge"><i />Dữ liệu minh họa</span>
            <div className="admin-profile"><span>QT</span><div><strong>Quản trị viên</strong><small>Chế độ phát triển</small></div></div>
          </div>
        </header>

        <main className="admin-content">
          <div className="admin-warning"><Icon name="shield" size={17} /><p><strong>Giao diện quản trị đang ở chế độ minh họa.</strong> Chưa triển khai xác thực hoặc phân quyền thực tế; việc ẩn menu không phải là cơ chế bảo mật.</p></div>
          {activeView === 'overview' && <AdminOverview onNavigate={setActiveView} />}
          {activeView === 'users' && <AdminUsers users={users} onToggleStatus={toggleUserStatus} />}
          {activeView === 'documents' && <AdminDocuments documents={documents} onDelete={deleteDocument} />}
        </main>
      </div>
    </div>
  )
}

export default AdminDashboard
