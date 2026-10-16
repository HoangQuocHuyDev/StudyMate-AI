import apiClient from './apiClient.js'


const ADMIN_USER_ROLES = new Set(['USER', 'ADMIN'])

function getAuthOptions(accessToken, signal) {
  if (
    typeof accessToken !== 'string'
    || !accessToken
    || accessToken !== accessToken.trim()
  ) {
    throw new TypeError('Access token không hợp lệ.')
  }
  return {
    headers: { Authorization: `Bearer ${accessToken}` },
    signal,
  }
}

export function getAdminUsers({
  accessToken,
  limit = 20,
  offset = 0,
  search = '',
  role = null,
  isActive = null,
  signal,
} = {}) {
  if (!Number.isInteger(limit) || limit < 1 || limit > 100) {
    throw new TypeError('Giới hạn người dùng phải là số nguyên từ 1 đến 100.')
  }
  if (!Number.isInteger(offset) || offset < 0) {
    throw new TypeError('Vị trí phân trang phải là số nguyên không âm.')
  }
  if (typeof search !== 'string' || search.length > 255) {
    throw new TypeError('Từ khóa phải là chuỗi không quá 255 ký tự.')
  }
  if (role !== null && !ADMIN_USER_ROLES.has(role)) {
    throw new TypeError('Vai trò người dùng không hợp lệ.')
  }
  if (isActive !== null && typeof isActive !== 'boolean') {
    throw new TypeError('Trạng thái người dùng không hợp lệ.')
  }

  const params = new URLSearchParams({
    limit: String(limit),
    offset: String(offset),
  })
  const normalizedSearch = search.trim()
  if (normalizedSearch) params.set('search', normalizedSearch)
  if (role !== null) params.set('role', role)
  if (isActive !== null) params.set('is_active', String(isActive))

  return apiClient.get(`/admin/users?${params.toString()}`, {
    ...getAuthOptions(accessToken, signal),
  })
}

export function updateAdminUserStatus(userId, isActive, {
  accessToken,
  signal,
} = {}) {
  if (!Number.isInteger(userId) || userId <= 0) {
    throw new TypeError('ID người dùng phải là số nguyên dương.')
  }
  if (typeof isActive !== 'boolean') {
    throw new TypeError('Trạng thái người dùng phải là boolean.')
  }

  return apiClient.patch(
    `/admin/users/${userId}/status`,
    { is_active: isActive },
    getAuthOptions(accessToken, signal),
  )
}
