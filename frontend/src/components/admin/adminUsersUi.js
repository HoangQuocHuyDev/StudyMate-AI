import {
  ApiConfigurationError,
  ApiHttpError,
  ApiNetworkError,
} from '../../services/apiClient.js'


const SAFE_USER_KEYS = [
  'id',
  'full_name',
  'username',
  'role',
  'is_active',
  'created_at',
]
const SENSITIVE_USER_KEYS = ['password_hash', 'token_version', 'password', 'access_token']

export const ADMIN_USERS_PAGE_SIZE = 20

export function getAdminRoleLabel(role) {
  return role === 'ADMIN' ? 'Quản trị viên' : 'Người dùng'
}

function isPositiveInteger(value) {
  return Number.isInteger(value) && value > 0
}

function validateUser(user) {
  if (!user || typeof user !== 'object') {
    throw new TypeError('Dữ liệu người dùng không hợp lệ.')
  }
  if (SENSITIVE_USER_KEYS.some((key) => Object.hasOwn(user, key))) {
    throw new TypeError('Phản hồi chứa trường người dùng không được phép.')
  }
  if (
    !isPositiveInteger(user.id)
    || typeof user.full_name !== 'string'
    || !user.full_name.trim()
    || typeof user.username !== 'string'
    || !user.username.trim()
    || !['USER', 'ADMIN'].includes(user.role)
    || typeof user.is_active !== 'boolean'
    || typeof user.created_at !== 'string'
    || Number.isNaN(Date.parse(user.created_at))
  ) {
    throw new TypeError('Dữ liệu người dùng không hợp lệ.')
  }

  return Object.fromEntries(SAFE_USER_KEYS.map((key) => [key, user[key]]))
}

export function validateAdminUserListResponse(response) {
  if (
    !response
    || typeof response !== 'object'
    || !Array.isArray(response.items)
    || !Number.isInteger(response.total)
    || response.total < 0
    || !Number.isInteger(response.limit)
    || response.limit < 1
    || response.limit > 100
    || !Number.isInteger(response.offset)
    || response.offset < 0
  ) {
    throw new TypeError('Phản hồi danh sách người dùng không hợp lệ.')
  }

  const items = response.items.map(validateUser)
  if (
    items.length > response.limit
    || (items.length > 0 && response.offset + items.length > response.total)
  ) {
    throw new TypeError('Thông tin phân trang người dùng không hợp lệ.')
  }
  if (new Set(items.map(({ id }) => id)).size !== items.length) {
    throw new TypeError('Danh sách người dùng chứa ID trùng lặp.')
  }
  return { ...response, items }
}

export function getAdminUsersAdjustedOffset({ total, offset, limit }) {
  if (total === 0) return 0
  return Math.min(offset, Math.floor((total - 1) / limit) * limit)
}

export function validateAdminUserResponse(response) {
  return validateUser(response)
}

export function parseActivityFilter(value) {
  if (value === 'active') return true
  if (value === 'inactive') return false
  return null
}

export function getAdminUsersPageInfo({ total, offset, limit }) {
  const pageCount = Math.max(1, Math.ceil(total / limit))
  const currentPage = Math.min(pageCount, Math.floor(offset / limit) + 1)
  return {
    currentPage,
    pageCount,
    firstItem: total === 0 ? 0 : offset + 1,
    lastItem: Math.min(total, offset + limit),
    canGoBack: offset > 0,
    canGoForward: offset + limit < total,
  }
}

export function replaceAdminUser(items, updatedUser) {
  return items.map((item) => (item.id === updatedUser.id ? updatedUser : item))
}

export function getAdminUserStatusAction(account, currentUserId) {
  if (!account || !isPositiveInteger(account.id)) return null
  const desiredStatus = !account.is_active
  if (!desiredStatus && account.id === currentUserId) return null
  return {
    account,
    desiredStatus,
    title: desiredStatus ? 'Mở khóa tài khoản?' : 'Khóa tài khoản?',
    confirmLabel: desiredStatus ? 'Mở khóa' : 'Khóa tài khoản',
  }
}

export function formatAdminUserDate(value) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return 'Không xác định'
  return new Intl.DateTimeFormat('vi-VN', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
  }).format(date)
}

export function getAdminUserInitials(fullName) {
  const words = fullName.trim().split(/\s+/).filter(Boolean)
  return words.slice(-2).map((word) => word[0]).join('').toUpperCase()
}

export function getAdminUsersErrorMessage(error) {
  if (error instanceof ApiHttpError) {
    if (error.status === 401) return 'Phiên đăng nhập đã hết hạn. Vui lòng đăng nhập lại.'
    if (error.status === 403) return 'Bạn không có quyền quản lý người dùng.'
    if (error.status === 404) return 'Tài khoản không còn tồn tại.'
    if (error.status === 409) {
      return 'Không thể thay đổi trạng thái tài khoản do quy tắc bảo vệ quản trị viên.'
    }
    if (error.status === 422) return 'Yêu cầu cập nhật trạng thái không hợp lệ.'
    if (error.status >= 500) return 'Hệ thống đang gặp sự cố. Vui lòng thử lại sau.'
  }
  if (error instanceof ApiNetworkError) {
    return 'Không thể kết nối đến hệ thống. Vui lòng kiểm tra mạng và thử lại.'
  }
  if (error instanceof ApiConfigurationError) {
    return 'Ứng dụng chưa được cấu hình đầy đủ. Vui lòng liên hệ quản trị viên.'
  }
  return 'Không thể hoàn tất thao tác quản lý người dùng lúc này.'
}

export const initialAdminUsersState = Object.freeze({
  data: null,
  status: 'idle',
  error: null,
  requestId: 0,
})

export function adminUsersReducer(state, action) {
  switch (action.type) {
    case 'request-started':
      return {
        ...state,
        status: 'loading',
        error: null,
        requestId: action.requestId,
      }
    case 'request-succeeded':
      if (state.requestId !== action.requestId) return state
      return {
        data: action.data,
        status: 'ready',
        error: null,
        requestId: action.requestId,
      }
    case 'request-failed':
      if (state.requestId !== action.requestId) return state
      return {
        ...state,
        status: 'error',
        error: action.error,
      }
    case 'user-updated':
      if (!state.data) return state
      return {
        ...state,
        data: {
          ...state.data,
          items: replaceAdminUser(state.data.items, action.user),
        },
      }
    default:
      return state
  }
}

export function createAdminUserStatusController(requestStatusUpdate) {
  let pending = null
  let controller = null

  return {
    run(input) {
      if (pending) return pending
      controller = new AbortController()
      pending = Promise.resolve(requestStatusUpdate({
        ...input,
        signal: controller.signal,
      })).finally(() => {
        pending = null
        controller = null
      })
      return pending
    },
    cancel() {
      controller?.abort()
    },
    isPending() {
      return pending !== null
    },
  }
}
