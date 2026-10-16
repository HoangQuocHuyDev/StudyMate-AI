import apiClient from './apiClient.js'


const FILE_TYPES = new Set(['PDF', 'DOCX'])
const DOCUMENT_STATUSES = new Set(['UPLOADED', 'PROCESSING', 'READY', 'FAILED'])
const RAG_STATUSES = new Set(['PENDING', 'INDEXING', 'READY', 'FAILED'])

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

export function getAdminDocuments({
  accessToken,
  limit = 20,
  offset = 0,
  search = '',
  fileType = null,
  status = null,
  ragStatus = null,
  signal,
} = {}) {
  if (!Number.isInteger(limit) || limit < 1 || limit > 100) {
    throw new TypeError('Giới hạn tài liệu phải là số nguyên từ 1 đến 100.')
  }
  if (!Number.isInteger(offset) || offset < 0) {
    throw new TypeError('Vị trí phân trang phải là số nguyên không âm.')
  }
  if (typeof search !== 'string' || search.length > 255) {
    throw new TypeError('Từ khóa phải là chuỗi không quá 255 ký tự.')
  }
  if (fileType !== null && !FILE_TYPES.has(fileType)) {
    throw new TypeError('Loại tài liệu không hợp lệ.')
  }
  if (status !== null && !DOCUMENT_STATUSES.has(status)) {
    throw new TypeError('Trạng thái xử lý không hợp lệ.')
  }
  if (ragStatus !== null && !RAG_STATUSES.has(ragStatus)) {
    throw new TypeError('Trạng thái RAG không hợp lệ.')
  }

  const params = new URLSearchParams({
    limit: String(limit),
    offset: String(offset),
  })
  const normalizedSearch = search.trim()
  if (normalizedSearch) params.set('search', normalizedSearch)
  if (fileType !== null) params.set('file_type', fileType)
  if (status !== null) params.set('status', status)
  if (ragStatus !== null) params.set('rag_status', ragStatus)

  return apiClient.get(`/admin/documents?${params.toString()}`, {
    ...getAuthOptions(accessToken, signal),
  })
}

export function getAdminDocumentDetail(documentId, {
  accessToken,
  signal,
} = {}) {
  if (!Number.isInteger(documentId) || documentId <= 0) {
    throw new TypeError('ID tài liệu phải là số nguyên dương.')
  }
  return apiClient.get(
    `/admin/documents/${documentId}`,
    getAuthOptions(accessToken, signal),
  )
}
