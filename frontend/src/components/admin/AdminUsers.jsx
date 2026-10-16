import {
  useCallback,
  useEffect,
  useReducer,
  useRef,
  useState,
} from 'react'
import { useAuth } from '../../contexts/AuthContext'
import { ApiHttpError } from '../../services/apiClient'
import {
  getAdminUsers,
  updateAdminUserStatus,
} from '../../services/adminUsersService'
import Icon from '../Icons'
import {
  ADMIN_USERS_PAGE_SIZE,
  adminUsersReducer,
  createAdminUserStatusController,
  formatAdminUserDate,
  getAdminUsersAdjustedOffset,
  getAdminUserInitials,
  getAdminUserStatusAction,
  getAdminUsersErrorMessage,
  getAdminUsersPageInfo,
  initialAdminUsersState,
  parseActivityFilter,
  validateAdminUserListResponse,
  validateAdminUserResponse,
} from './adminUsersUi'


function TableSkeleton() {
  return (
    <div className="admin-users-skeleton" aria-label="Đang tải danh sách người dùng" aria-busy="true">
      {Array.from({ length: 6 }, (_, index) => (
        <span key={index}><i /><i /><i /><i /></span>
      ))}
    </div>
  )
}

function AdminUsers() {
  const { accessToken, user: currentUser } = useAuth()
  const [state, dispatch] = useReducer(adminUsersReducer, initialAdminUsersState)
  const [searchInput, setSearchInput] = useState('')
  const [search, setSearch] = useState('')
  const [roleFilter, setRoleFilter] = useState('all')
  const [activityFilter, setActivityFilter] = useState('all')
  const [offset, setOffset] = useState(0)
  const [selectedAction, setSelectedAction] = useState(null)
  const [isActionPending, setIsActionPending] = useState(false)
  const [actionError, setActionError] = useState(null)
  const [successMessage, setSuccessMessage] = useState(null)
  const requestRef = useRef({ id: 0, controller: null })
  const searchRef = useRef('')
  const isMountedRef = useRef(true)
  const confirmButtonRef = useRef(null)
  const [statusController] = useState(() => createAdminUserStatusController(({
    userId,
    isActive,
    token,
    signal,
  }) => updateAdminUserStatus(userId, isActive, {
    accessToken: token,
    signal,
  })))

  const loadUsers = useCallback(async () => {
    const requestId = requestRef.current.id + 1
    const controller = new AbortController()
    requestRef.current.controller?.abort()
    requestRef.current = { id: requestId, controller }
    dispatch({ type: 'request-started', requestId })

    try {
      const response = await getAdminUsers({
        accessToken,
        limit: ADMIN_USERS_PAGE_SIZE,
        offset,
        search,
        role: roleFilter === 'all' ? null : roleFilter,
        isActive: parseActivityFilter(activityFilter),
        signal: controller.signal,
      })
      const data = validateAdminUserListResponse(response)
      if (!isMountedRef.current || requestRef.current.id !== requestId) return

      const adjustedOffset = getAdminUsersAdjustedOffset(data)
      if (adjustedOffset !== offset) {
        setOffset(adjustedOffset)
        return
      }
      dispatch({ type: 'request-succeeded', requestId, data })
    } catch (error) {
      if (
        error?.name === 'AbortError'
        || !isMountedRef.current
        || requestRef.current.id !== requestId
      ) return
      dispatch({
        type: 'request-failed',
        requestId,
        error: getAdminUsersErrorMessage(error),
      })
    } finally {
      if (requestRef.current.id === requestId) {
        requestRef.current.controller = null
      }
    }
  }, [accessToken, activityFilter, offset, roleFilter, search])

  useEffect(() => {
    const timer = window.setTimeout(() => {
      const normalized = searchInput.trim()
      if (searchRef.current !== normalized) {
        searchRef.current = normalized
        setOffset(0)
        setSearch(normalized)
      }
    }, 350)
    return () => window.clearTimeout(timer)
  }, [searchInput])

  useEffect(() => {
    const timer = window.setTimeout(loadUsers, 0)
    return () => {
      window.clearTimeout(timer)
      requestRef.current.controller?.abort()
    }
  }, [loadUsers])

  useEffect(() => {
    isMountedRef.current = true
    return () => {
      isMountedRef.current = false
      requestRef.current.id += 1
      requestRef.current.controller?.abort()
      statusController.cancel()
    }
  }, [statusController])

  useEffect(() => {
    if (!selectedAction) return undefined
    document.body.classList.add('admin-modal-visible')
    confirmButtonRef.current?.focus()
    const handleKeyDown = (event) => {
      if (event.key === 'Escape' && !statusController.isPending()) {
        setSelectedAction(null)
        setActionError(null)
      }
    }
    document.addEventListener('keydown', handleKeyDown)
    return () => {
      document.body.classList.remove('admin-modal-visible')
      document.removeEventListener('keydown', handleKeyDown)
    }
  }, [selectedAction, statusController])

  const openStatusConfirmation = (account) => {
    const action = getAdminUserStatusAction(account, currentUser?.id)
    if (!action) return
    setActionError(null)
    setSuccessMessage(null)
    setSelectedAction(action)
  }

  const closeConfirmation = () => {
    if (isActionPending) return
    setSelectedAction(null)
    setActionError(null)
  }

  const confirmStatusChange = async () => {
    if (!selectedAction || statusController.isPending()) return
    const { account, desiredStatus } = selectedAction
    setIsActionPending(true)
    setActionError(null)
    try {
      const response = await statusController.run({
        userId: account.id,
        isActive: desiredStatus,
        token: accessToken,
      })
      const updatedUser = validateAdminUserResponse(response)
      if (!isMountedRef.current) return
      dispatch({ type: 'user-updated', user: updatedUser })
      setSelectedAction(null)
      setSuccessMessage(
        desiredStatus
          ? `Đã mở khóa tài khoản ${account.username}.`
          : `Đã khóa tài khoản ${account.username}.`,
      )
      await loadUsers()
    } catch (error) {
      if (error?.name === 'AbortError' || !isMountedRef.current) return
      setActionError(getAdminUsersErrorMessage(error))
      if (error instanceof ApiHttpError && error.status === 404) loadUsers()
    } finally {
      if (isMountedRef.current) setIsActionPending(false)
    }
  }

  const data = state.data
  const users = data?.items ?? []
  const pageInfo = data ? getAdminUsersPageInfo(data) : null
  const hasFilters = Boolean(search || roleFilter !== 'all' || activityFilter !== 'all')

  return (
    <section className="admin-management" aria-labelledby="admin-users-title">
      <div className="admin-section-heading">
        <div>
          <p>Quản lý tài khoản</p>
          <h2 id="admin-users-title">Danh sách người dùng</h2>
          <span>Xem và kiểm soát trạng thái các tài khoản trong hệ thống.</span>
        </div>
        <strong>{data ? `${data.total} tài khoản` : 'Đang đồng bộ'}</strong>
      </div>

      <div className="admin-toolbar" aria-label="Bộ lọc người dùng">
        <label className="admin-search">
          <Icon name="search" size={18} />
          <span className="sr-only">Tìm theo username</span>
          <input
            type="search"
            value={searchInput}
            maxLength={255}
            placeholder="Tìm theo username..."
            onChange={(event) => setSearchInput(event.target.value)}
          />
          {searchInput && (
            <button type="button" onClick={() => setSearchInput('')} aria-label="Xóa từ khóa tìm kiếm">
              <Icon name="close" size={15} />
            </button>
          )}
        </label>
        <label className="admin-filter">
          <span>Vai trò</span>
          <select value={roleFilter} onChange={(event) => { setRoleFilter(event.target.value); setOffset(0) }}>
            <option value="all">Tất cả</option>
            <option value="USER">USER</option>
            <option value="ADMIN">ADMIN</option>
          </select>
          <Icon name="chevronDown" size={15} />
        </label>
        <label className="admin-filter">
          <span>Trạng thái</span>
          <select value={activityFilter} onChange={(event) => { setActivityFilter(event.target.value); setOffset(0) }}>
            <option value="all">Tất cả</option>
            <option value="active">Hoạt động</option>
            <option value="inactive">Đã khóa</option>
          </select>
          <Icon name="chevronDown" size={15} />
        </label>
      </div>

      {successMessage && <div className="admin-users-notice admin-users-notice--success" role="status"><Icon name="check" size={18} />{successMessage}</div>}
      {state.status === 'error' && data && (
        <div className="admin-refresh-error" role="alert">
          <span>{state.error} Dữ liệu trước đó vẫn được giữ nguyên.</span>
          <button type="button" onClick={loadUsers}>Thử lại</button>
        </div>
      )}

      {state.status === 'loading' && !data && <TableSkeleton />}
      {state.status === 'error' && !data && (
        <div className="admin-empty admin-empty--error" role="alert">
          <div><Icon name="refresh" size={27} /></div>
          <h3>Chưa thể tải danh sách người dùng</h3>
          <p>{state.error}</p>
          <button type="button" onClick={loadUsers}>Thử lại</button>
        </div>
      )}
      {data && users.length === 0 && (
        <div className="admin-empty" role="status">
          <div><Icon name="users" size={27} /></div>
          <h3>{hasFilters ? 'Không tìm thấy người dùng phù hợp' : 'Chưa có tài khoản nào'}</h3>
          <p>{hasFilters ? 'Hãy thử thay đổi từ khóa hoặc bộ lọc.' : 'Tài khoản mới sẽ xuất hiện tại đây.'}</p>
        </div>
      )}

      {data && users.length > 0 && (
        <>
          <div className="admin-table-wrap" aria-busy={state.status === 'loading'}>
            <table className="admin-table admin-users-table">
              <thead><tr><th>ID</th><th>Họ tên</th><th>Username</th><th>Vai trò</th><th>Trạng thái</th><th>Ngày đăng ký</th><th>Thao tác</th></tr></thead>
              <tbody>
                {users.map((account) => {
                  const isCurrentAdmin = account.id === currentUser?.id
                  return (
                    <tr key={account.id}>
                      <td data-label="ID"><span className="admin-user-id">#{account.id}</span></td>
                      <td data-label="Họ tên">
                        <div className="admin-user-cell"><span>{getAdminUserInitials(account.full_name)}</span><div><strong>{account.full_name}</strong>{isCurrentAdmin && <small>Tài khoản hiện tại</small>}</div></div>
                      </td>
                      <td data-label="Username"><span className="admin-username">@{account.username}</span></td>
                      <td data-label="Vai trò"><span className={`admin-role admin-role--${account.role === 'ADMIN' ? 'admin' : 'student'}`}>{account.role}</span></td>
                      <td data-label="Trạng thái"><span className={`admin-status admin-status--${account.is_active ? 'active' : 'locked'}`}><i />{account.is_active ? 'Đang hoạt động' : 'Đã khóa'}</span></td>
                      <td data-label="Ngày đăng ký"><time dateTime={account.created_at}>{formatAdminUserDate(account.created_at)}</time></td>
                      <td data-label="Thao tác">
                        <div className="admin-row-actions">
                          <button
                            className={account.is_active ? 'admin-action--lock' : 'admin-action--unlock'}
                            type="button"
                            disabled={isActionPending || (isCurrentAdmin && account.is_active)}
                            title={isCurrentAdmin && account.is_active ? 'Không thể tự khóa tài khoản đang đăng nhập' : undefined}
                            onClick={() => openStatusConfirmation(account)}
                          >
                            <Icon name={account.is_active ? 'lock' : 'unlock'} size={15} />
                            {account.is_active ? 'Khóa' : 'Mở khóa'}
                          </button>
                        </div>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>

          <div className="admin-pagination" aria-label="Phân trang người dùng">
            <span>Hiển thị {pageInfo.firstItem}–{pageInfo.lastItem} trong {data.total} tài khoản</span>
            <div>
              <button type="button" disabled={!pageInfo.canGoBack || state.status === 'loading'} onClick={() => setOffset(Math.max(0, offset - ADMIN_USERS_PAGE_SIZE))}>Trang trước</button>
              <strong>Trang {pageInfo.currentPage}/{pageInfo.pageCount}</strong>
              <button type="button" disabled={!pageInfo.canGoForward || state.status === 'loading'} onClick={() => setOffset(offset + ADMIN_USERS_PAGE_SIZE)}>Trang sau</button>
            </div>
          </div>
        </>
      )}

      {selectedAction && (
        <div className="admin-modal" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) closeConfirmation() }}>
          <div className="admin-dialog admin-dialog--confirm" role="dialog" aria-modal="true" aria-labelledby="admin-status-dialog-title" aria-describedby="admin-status-dialog-description">
            <span className={`admin-confirm__icon ${selectedAction.desiredStatus ? 'admin-confirm__icon--unlock' : ''}`}><Icon name={selectedAction.desiredStatus ? 'unlock' : 'lock'} size={24} /></span>
            <h2 id="admin-status-dialog-title">{selectedAction.title}</h2>
            <p id="admin-status-dialog-description">
              Bạn sắp {selectedAction.desiredStatus ? 'mở khóa' : 'khóa'} tài khoản <strong>@{selectedAction.account.username}</strong>.
              {!selectedAction.desiredStatus && ' Các phiên đăng nhập hiện tại của tài khoản sẽ mất hiệu lực.'}
            </p>
            {actionError && <p className="admin-confirm__error" role="alert">{actionError}</p>}
            <div className="admin-confirm__actions">
              <button type="button" disabled={isActionPending} onClick={closeConfirmation}>Hủy</button>
              <button
                ref={confirmButtonRef}
                className={`admin-confirm__primary ${selectedAction.desiredStatus ? '' : 'admin-confirm__primary--danger'}`}
                type="button"
                disabled={isActionPending}
                onClick={confirmStatusChange}
              >
                {isActionPending ? 'Đang cập nhật...' : selectedAction.confirmLabel}
              </button>
            </div>
          </div>
        </div>
      )}
    </section>
  )
}

export default AdminUsers
