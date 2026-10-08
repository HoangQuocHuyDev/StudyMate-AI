import { useMemo, useState } from 'react'
import Icon from '../Icons'
import AdminModal from './AdminModal'

const roleLabels = { student: 'Sinh viên', admin: 'Quản trị viên' }

function AdminUsers({ users, onToggleStatus }) {
  const [query, setQuery] = useState('')
  const [roleFilter, setRoleFilter] = useState('all')
  const [statusFilter, setStatusFilter] = useState('all')
  const [detailUser, setDetailUser] = useState(null)
  const [confirmUser, setConfirmUser] = useState(null)

  const filteredUsers = useMemo(() => {
    const normalizedQuery = query.trim().toLocaleLowerCase('vi')
    return users.filter((user) => {
      const matchesQuery = `${user.name} ${user.username}`.toLocaleLowerCase('vi').includes(normalizedQuery)
      const matchesRole = roleFilter === 'all' || user.role === roleFilter
      const matchesStatus = statusFilter === 'all' || user.status === statusFilter
      return matchesQuery && matchesRole && matchesStatus
    })
  }, [query, roleFilter, statusFilter, users])

  const confirmToggle = () => {
    onToggleStatus(confirmUser.id)
    setConfirmUser(null)
  }

  return (
    <section className="admin-management" aria-labelledby="admin-users-title">
      <div className="admin-section-heading"><div><p>Quản lý tài khoản</p><h2 id="admin-users-title">Danh sách người dùng</h2><span>Tìm kiếm, xem thông tin và quản lý trạng thái tài khoản mẫu.</span></div><strong>{users.length} tài khoản</strong></div>
      <div className="admin-toolbar">
        <label className="admin-search"><Icon name="search" size={18} /><input type="search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Tìm theo họ tên hoặc tên đăng nhập..." aria-label="Tìm kiếm người dùng" />{query && <button type="button" onClick={() => setQuery('')} aria-label="Xóa tìm kiếm"><Icon name="close" size={15} /></button>}</label>
        <label className="admin-filter"><span>Vai trò</span><select value={roleFilter} onChange={(event) => setRoleFilter(event.target.value)}><option value="all">Tất cả</option><option value="student">Sinh viên</option><option value="admin">Quản trị viên</option></select><Icon name="chevronDown" size={15} /></label>
        <label className="admin-filter"><span>Trạng thái</span><select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}><option value="all">Tất cả</option><option value="active">Hoạt động</option><option value="locked">Đã khóa</option></select><Icon name="chevronDown" size={15} /></label>
      </div>

      {filteredUsers.length ? (
        <div className="admin-table-wrap">
          <table className="admin-table admin-users-table">
            <thead><tr><th>Người dùng</th><th>Vai trò</th><th>Trạng thái</th><th>Ngày tạo</th><th><span className="sr-only">Thao tác</span></th></tr></thead>
            <tbody>
              {filteredUsers.map((user) => (
                <tr key={user.id}>
                  <td data-label="Người dùng"><div className="admin-user-cell"><span>{user.initials}</span><div><strong>{user.name}</strong><small>@{user.username}</small></div></div></td>
                  <td data-label="Vai trò"><span className={`admin-role admin-role--${user.role}`}>{roleLabels[user.role]}</span></td>
                  <td data-label="Trạng thái"><span className={`admin-status admin-status--${user.status}`}><i />{user.status === 'active' ? 'Hoạt động' : 'Đã khóa'}</span></td>
                  <td data-label="Ngày tạo"><time>{user.createdAt}</time></td>
                  <td><div className="admin-row-actions"><button type="button" onClick={() => setDetailUser(user)}><Icon name="eye" size={16} />Xem</button><button className={user.status === 'locked' ? 'admin-action--unlock' : 'admin-action--lock'} type="button" onClick={() => setConfirmUser(user)}><Icon name={user.status === 'locked' ? 'unlock' : 'lock'} size={16} />{user.status === 'locked' ? 'Mở khóa' : 'Khóa'}</button></div></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="admin-empty"><div><Icon name="users" size={27} /></div><h3>Không tìm thấy người dùng</h3><p>Hãy thử thay đổi từ khóa hoặc bộ lọc hiện tại.</p><button type="button" onClick={() => { setQuery(''); setRoleFilter('all'); setStatusFilter('all') }}>Xóa bộ lọc</button></div>
      )}

      {detailUser && (
        <AdminModal title={detailUser.name} eyebrow="Chi tiết tài khoản mẫu" onClose={() => setDetailUser(null)}>
          <div className="admin-detail-profile"><span>{detailUser.initials}</span><div><strong>{detailUser.name}</strong><small>@{detailUser.username}</small></div></div>
          <dl className="admin-detail-list"><div><dt>Vai trò</dt><dd>{roleLabels[detailUser.role]}</dd></div><div><dt>Trạng thái</dt><dd>{detailUser.status === 'active' ? 'Hoạt động' : 'Đã khóa'}</dd></div><div><dt>Ngày tạo tài khoản</dt><dd>{detailUser.createdAt}</dd></div><div><dt>Tài liệu đã tải</dt><dd>{detailUser.documents} tài liệu</dd></div><div><dt>Phiên hỏi đáp</dt><dd>{detailUser.sessions} phiên</dd></div></dl>
          <p className="admin-detail-note">Thông tin trên là dữ liệu minh họa, không lấy từ tài khoản người dùng thật.</p>
        </AdminModal>
      )}

      {confirmUser && (
        <AdminModal confirm onClose={() => setConfirmUser(null)}>
          <div className={`admin-confirm__icon ${confirmUser.status === 'locked' ? 'admin-confirm__icon--unlock' : ''}`}><Icon name={confirmUser.status === 'locked' ? 'unlock' : 'lock'} size={23} /></div>
          <h2 id="admin-dialog-title">{confirmUser.status === 'locked' ? 'Mở khóa tài khoản?' : 'Khóa tài khoản?'}</h2>
          <p>Trạng thái của tài khoản <strong>@{confirmUser.username}</strong> sẽ được thay đổi trong danh sách dữ liệu mẫu.</p>
          <div className="admin-confirm__actions"><button type="button" onClick={() => setConfirmUser(null)}>Hủy</button><button className="admin-confirm__primary" type="button" onClick={confirmToggle}>{confirmUser.status === 'locked' ? 'Mở khóa' : 'Khóa tài khoản'}</button></div>
        </AdminModal>
      )}
    </section>
  )
}

export default AdminUsers
