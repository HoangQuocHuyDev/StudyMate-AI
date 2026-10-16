import { createUnauthorizedResponseController } from './unauthorizedResponse.js'

const API_BASE_URL = (import.meta.env?.VITE_API_BASE_URL ?? '')
  .trim()
  .replace(/\/+$/, '')

const unauthorizedResponses = createUnauthorizedResponseController()

export function registerUnauthorizedHandler(handler) {
  return unauthorizedResponses.register(handler)
}

export class ApiConfigurationError extends Error {
  constructor(message) {
    super(message)
    this.name = 'ApiConfigurationError'
  }
}

export class ApiHttpError extends Error {
  constructor(message, { status, statusText, data, retryAfter = null }) {
    super(message)
    this.name = 'ApiHttpError'
    this.status = status
    this.statusText = statusText
    this.data = data
    this.retryAfter = retryAfter
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

async function parseResponse(response, responseType = 'auto') {
  if (response.status === 204 || response.status === 205) return null

  if (responseType === 'blob') return response.blob()

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
    responseType = 'auto',
    ...fetchOptions
  } = options
  if (!['auto', 'blob'].includes(responseType)) {
    throw new TypeError('Kiểu dữ liệu phản hồi không được hỗ trợ.')
  }
  const headers = new Headers(customHeaders)
  const unauthorizedSnapshot = unauthorizedResponses.capture(headers)

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
    if (error?.name === 'AbortError') throw error

    throw new ApiNetworkError(
      'Không thể kết nối đến máy chủ. Vui lòng kiểm tra kết nối mạng.',
      { cause: error },
    )
  }

  const data = await parseResponse(response, response.ok ? responseType : 'auto')
  if (!response.ok) {
    unauthorizedResponses.handle(unauthorizedSnapshot, response.status)
    throw new ApiHttpError(getErrorMessage(data, response), {
      status: response.status,
      statusText: response.statusText,
      data,
      retryAfter: response.headers.get('retry-after'),
    })
  }

  return data
}

export const apiClient = {
  request,
  get: (path, options) => request(path, { ...options, method: 'GET' }),
  getBlob: (path, options) => request(path, {
    ...options,
    method: 'GET',
    responseType: 'blob',
  }),
  post: (path, json, options) => request(path, { ...options, method: 'POST', json }),
  postForm: (path, formData, options) => {
    if (!(formData instanceof FormData)) {
      throw new TypeError('Dữ liệu multipart phải là một FormData hợp lệ.')
    }
    return request(path, { ...options, method: 'POST', body: formData })
  },
  put: (path, json, options) => request(path, { ...options, method: 'PUT', json }),
  patch: (path, json, options) => request(path, { ...options, method: 'PATCH', json }),
  delete: (path, options) => request(path, { ...options, method: 'DELETE' }),
}

export default apiClient
