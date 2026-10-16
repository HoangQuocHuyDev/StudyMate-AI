import apiClient from './apiClient.js'


function authenticatedGet(path, { accessToken, signal } = {}) {
  if (
    typeof accessToken !== 'string'
    || !accessToken
    || accessToken !== accessToken.trim()
  ) {
    throw new TypeError('Access token không hợp lệ.')
  }

  return apiClient.get(path, {
    headers: { Authorization: `Bearer ${accessToken}` },
    signal,
  })
}

export function getAdminDashboardOverview(options = {}) {
  return authenticatedGet('/admin/dashboard/overview', options)
}

export function getAdminDashboardActivity(options = {}) {
  return authenticatedGet('/admin/dashboard/activity', options)
}

export function getAdminRecentActivities({ limit = 10, ...options } = {}) {
  if (!Number.isInteger(limit) || limit < 1 || limit > 50) {
    throw new TypeError('Giới hạn hoạt động phải là số nguyên từ 1 đến 50.')
  }
  const params = new URLSearchParams({ limit: String(limit) })
  return authenticatedGet(
    `/admin/dashboard/recent-activities?${params.toString()}`,
    options,
  )
}

