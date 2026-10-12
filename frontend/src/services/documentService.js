import apiClient from './apiClient.js'

export function uploadDocument({ file, title, accessToken, signal } = {}) {
  if (typeof File === 'undefined' || !(file instanceof File)) {
    throw new TypeError('Tệp tải lên phải là một File hợp lệ.')
  }

  if (title !== undefined && typeof title !== 'string') {
    throw new TypeError('Tiêu đề tài liệu phải là một chuỗi.')
  }

  if (
    typeof accessToken !== 'string'
    || !accessToken
    || accessToken !== accessToken.trim()
  ) {
    throw new TypeError('Access token không hợp lệ.')
  }

  const formData = new FormData()
  formData.append('file', file)

  const normalizedTitle = title?.trim()
  if (normalizedTitle) {
    formData.append('title', normalizedTitle)
  }

  return apiClient.postForm('/documents/upload', formData, {
    headers: {
      Authorization: `Bearer ${accessToken}`,
    },
    signal,
  })
}
