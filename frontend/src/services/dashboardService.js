import apiClient from './apiClient.js'


export function getDashboardOverview({ accessToken, signal } = {}) {
  if (
    typeof accessToken !== 'string'
    || !accessToken
    || accessToken !== accessToken.trim()
  ) {
    throw new TypeError('Access token không hợp lệ.')
  }

  return apiClient.get('/dashboard/overview', {
    headers: {
      Authorization: `Bearer ${accessToken}`,
    },
    signal,
  })
}
