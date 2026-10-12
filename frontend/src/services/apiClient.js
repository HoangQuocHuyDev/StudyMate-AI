const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? '')
  .trim()
  .replace(/\/+$/, '')

export class ApiConfigurationError extends Error {
  constructor(message) {
    super(message)
    this.name = 'ApiConfigurationError'
  }
}

export class ApiHttpError extends Error {
  constructor(message, { status, statusText, data }) {
    super(message)
    this.name = 'ApiHttpError'
    this.status = status
    this.statusText = statusText
    this.data = data
  }
}

export class ApiNetworkError extends Error {
  constructor(message, options) {
    super(message, options)
    this.name = 'ApiNetworkError'
  }
}

function buildUrl(path) {
  if (!API_BASE_URL) {
    throw new ApiConfigurationError(
      'VITE_API_BASE_URL chưa được cấu hình cho Frontend.',
    )
  }

  if (typeof path !== 'string' || !path.trim()) {
    throw new TypeError('Đường dẫn API phải là một chuỗi không rỗng.')
  }

  if (/^https?:\/\//i.test(path)) {
    throw new TypeError('Đường dẫn API phải là đường dẫn tương đối.')
  }

  const normalizedPath = path.startsWith('/') ? path : `/${path}`
  return `${API_BASE_URL}${normalizedPath}`
}

async function parseResponse(response) {
  if (response.status === 204 || response.status === 205) return null

  const text = await response.text()
  if (!text) return null

  const contentType = response.headers.get('content-type') ?? ''
  if (!contentType.includes('application/json')) return text

  try {
    return JSON.parse(text)
  } catch {
    return text
  }
}

function formatValidationError(error) {
  if (!error || typeof error !== 'object') return null

  const location = Array.isArray(error.loc)
    ? error.loc.filter((part) => part !== 'body').join('.')
    : ''
  const message = typeof error.msg === 'string' ? error.msg : null

  if (!message) return null
  return location ? `${location}: ${message}` : message
}

function getErrorMessage(data, response) {
  const detail = data?.detail

  if (typeof detail === 'string' && detail.trim()) return detail

  if (Array.isArray(detail)) {
    const messages = detail.map(formatValidationError).filter(Boolean)
    if (messages.length) return messages.join('\n')
  }

  if (typeof data?.message === 'string' && data.message.trim()) {
    return data.message
  }

  if (typeof data === 'string' && data.trim()) return data

  return `Yêu cầu thất bại (${response.status} ${response.statusText})`.trim()
}

export async function request(path, options = {}) {
  const {
    json,
    headers: customHeaders,
    ...fetchOptions
  } = options
  const headers = new Headers(customHeaders)

  if (json !== undefined) {
    if (fetchOptions.body !== undefined) {
      throw new TypeError('Chỉ được truyền một trong hai tùy chọn json hoặc body.')
    }
    headers.set('Content-Type', 'application/json')
    fetchOptions.body = JSON.stringify(json)
  }

  let response
  try {
    response = await fetch(buildUrl(path), {
      ...fetchOptions,
      headers,
    })
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error

    throw new ApiNetworkError(
      'Không thể kết nối đến máy chủ. Vui lòng kiểm tra kết nối mạng.',
      { cause: error },
    )
  }

  const data = await parseResponse(response)
  if (!response.ok) {
    throw new ApiHttpError(getErrorMessage(data, response), {
      status: response.status,
      statusText: response.statusText,
      data,
    })
  }

  return data
}

export const apiClient = {
  request,
  get: (path, options) => request(path, { ...options, method: 'GET' }),
  post: (path, json, options) => request(path, { ...options, method: 'POST', json }),
  put: (path, json, options) => request(path, { ...options, method: 'PUT', json }),
  patch: (path, json, options) => request(path, { ...options, method: 'PATCH', json }),
  delete: (path, options) => request(path, { ...options, method: 'DELETE' }),
}

export default apiClient
