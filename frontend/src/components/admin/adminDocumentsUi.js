import {
  ApiConfigurationError,
  ApiHttpError,
  ApiNetworkError,
} from '../../services/apiClient.js'


const FILE_TYPES = new Set(['PDF', 'DOCX'])
const DOCUMENT_STATUSES = new Set(['UPLOADED', 'PROCESSING', 'READY', 'FAILED'])
const RAG_STATUSES = new Set(['PENDING', 'INDEXING', 'READY', 'FAILED'])
const SENSITIVE_KEYS = new Set([
  'storage_key',
  'file_path',
  'path',
  'content',
  'chunks',
  'summaries',
  'chat_content',
  'embedding',
  'embeddings',
  'password_hash',
  'token_version',
  'access_token',
])
const ITEM_KEYS = [
  'id',
  'title',
  'original_filename',
  'file_type',
  'file_size',
  'status',
  'rag_status',
  'owner',
  'created_at',
  'processed_at',
  'indexed_at',
]
const DETAIL_KEYS = [
  ...ITEM_KEYS,
  'mime_type',
  'page_count',
  'character_count',
  'updated_at',
]

export const ADMIN_DOCUMENTS_PAGE_SIZE = 20

function isPositiveInteger(value) {
  return Number.isInteger(value) && value > 0
}

function isNullableDate(value) {
  return value === null
    || (typeof value === 'string' && !Number.isNaN(Date.parse(value)))
}

function assertNoSensitiveKeys(value) {
  if (!value || typeof value !== 'object') return
  for (const key of Object.keys(value)) {
    if (SENSITIVE_KEYS.has(key)) {
      throw new TypeError('Phản hồi tài liệu chứa trường không được phép.')
    }
  }
}

function validateOwner(owner) {
  assertNoSensitiveKeys(owner)
  if (
    !owner
    || typeof owner !== 'object'
    || !isPositiveInteger(owner.id)
    || typeof owner.username !== 'string'
    || !owner.username.trim()
    || typeof owner.full_name !== 'string'
    || !owner.full_name.trim()
  ) {
    throw new TypeError('Thông tin người tải lên không hợp lệ.')
  }
  return {
    id: owner.id,
    username: owner.username,
    full_name: owner.full_name,
  }
}

function validateDocument(document, detail = false) {
  assertNoSensitiveKeys(document)
  if (
    !document
    || typeof document !== 'object'
    || !isPositiveInteger(document.id)
    || typeof document.title !== 'string'
    || !document.title.trim()
    || typeof document.original_filename !== 'string'
    || !document.original_filename.trim()
    || !FILE_TYPES.has(document.file_type)
    || !isPositiveInteger(document.file_size)
    || !DOCUMENT_STATUSES.has(document.status)
    || !RAG_STATUSES.has(document.rag_status)
    || typeof document.created_at !== 'string'
    || Number.isNaN(Date.parse(document.created_at))
    || !isNullableDate(document.processed_at)
    || !isNullableDate(document.indexed_at)
  ) {
    throw new TypeError('Dữ liệu tài liệu không hợp lệ.')
  }

  if (detail && (
    typeof document.mime_type !== 'string'
    || !document.mime_type.trim()
    || (document.page_count !== null && !isPositiveInteger(document.page_count))
    || (
      document.character_count !== null
      && (!Number.isInteger(document.character_count) || document.character_count < 0)
    )
    || typeof document.updated_at !== 'string'
    || Number.isNaN(Date.parse(document.updated_at))
  )) {
    throw new TypeError('Chi tiết tài liệu không hợp lệ.')
  }

  const keys = detail ? DETAIL_KEYS : ITEM_KEYS
  return Object.fromEntries(keys.map((key) => [
    key,
    key === 'owner' ? validateOwner(document.owner) : document[key],
  ]))
}

export function validateAdminDocumentListResponse(response) {
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
    throw new TypeError('Phản hồi danh sách tài liệu không hợp lệ.')
  }
  const items = response.items.map((item) => validateDocument(item))
  if (
    items.length > response.limit
    || (items.length > 0 && response.offset + items.length > response.total)
  ) {
    throw new TypeError('Thông tin phân trang tài liệu không hợp lệ.')
  }
  if (new Set(items.map(({ id }) => id)).size !== items.length) {
    throw new TypeError('Danh sách tài liệu chứa ID trùng lặp.')
  }
  return { ...response, items }
}

export function getAdminDocumentsAdjustedOffset({ total, offset, limit }) {
  if (total === 0) return 0
  return Math.min(offset, Math.floor((total - 1) / limit) * limit)
}

export function validateAdminDocumentDetailResponse(response) {
  return validateDocument(response, true)
}

export function getAdminDocumentsPageInfo({ total, offset, limit }) {
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

export function formatAdminDocumentSize(bytes) {
  if (!Number.isFinite(bytes) || bytes < 0) return 'Không xác định'
  if (bytes < 1024) return `${bytes} B`
  const units = ['KB', 'MB', 'GB']
  let value = bytes / 1024
  let unitIndex = 0
  while (value >= 1024 && unitIndex < units.length - 1) {
    value /= 1024
    unitIndex += 1
  }
  return `${new Intl.NumberFormat('vi-VN', { maximumFractionDigits: 1 }).format(value)} ${units[unitIndex]}`
}

export function formatAdminDocumentDate(value, includeTime = false) {
  if (value === null) return 'Chưa có'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return 'Không xác định'
  return new Intl.DateTimeFormat('vi-VN', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    ...(includeTime ? { hour: '2-digit', minute: '2-digit' } : {}),
  }).format(date)
}

export function getDocumentStatusPresentation(status) {
  return {
    UPLOADED: { label: 'Chưa xử lý', tone: 'pending' },
    PROCESSING: { label: 'Đang xử lý', tone: 'processing' },
    READY: { label: 'Đã xử lý', tone: 'active' },
    FAILED: { label: 'Xử lý thất bại', tone: 'error' },
  }[status]
}

export function getRagStatusPresentation(status) {
  return {
    PENDING: { label: 'Chưa sẵn sàng', tone: 'pending' },
    INDEXING: { label: 'Đang chuẩn bị', tone: 'processing' },
    READY: { label: 'Sẵn sàng', tone: 'active' },
    FAILED: { label: 'Chuẩn bị thất bại', tone: 'error' },
  }[status]
}

export function getAdminDocumentsErrorMessage(error, context = 'list') {
  if (error instanceof ApiHttpError) {
    if (error.status === 401) return 'Phiên đăng nhập đã hết hạn. Vui lòng đăng nhập lại.'
    if (error.status === 403) return 'Bạn không có quyền xem dữ liệu tài liệu toàn hệ thống.'
    if (error.status === 404) return 'Tài liệu không còn tồn tại hoặc đang được xóa.'
    if (error.status === 422) return 'Điều kiện tìm kiếm hoặc lọc tài liệu không hợp lệ.'
    if (error.status >= 500) return 'Hệ thống đang gặp sự cố. Vui lòng thử lại sau.'
  }
  if (error instanceof ApiNetworkError) {
    return 'Không thể kết nối đến hệ thống. Vui lòng kiểm tra mạng và thử lại.'
  }
  if (error instanceof ApiConfigurationError) {
    return 'Ứng dụng chưa được cấu hình đầy đủ. Vui lòng liên hệ quản trị viên.'
  }
  return context === 'detail'
    ? 'Không thể tải chi tiết tài liệu lúc này.'
    : 'Không thể tải danh sách tài liệu lúc này.'
}

export const initialAdminDocumentsState = Object.freeze({
  data: null,
  status: 'idle',
  error: null,
  requestId: 0,
})

export function adminDocumentsReducer(state, action) {
  switch (action.type) {
    case 'request-started':
      return { ...state, status: 'loading', error: null, requestId: action.requestId }
    case 'request-succeeded':
      if (state.requestId !== action.requestId) return state
      return { data: action.data, status: 'ready', error: null, requestId: action.requestId }
    case 'request-failed':
      if (state.requestId !== action.requestId) return state
      return { ...state, status: 'error', error: action.error }
    default:
      return state
  }
}
