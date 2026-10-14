import apiClient from './apiClient.js'

const DOCUMENT_FILE_TYPES = new Set(['PDF', 'DOCX'])
const UPLOAD_FILE_EXTENSIONS = new Set(['pdf', 'docx'])
const MAX_DOCUMENT_SEARCH_LENGTH = 255

function validateAuthenticatedDocumentRequest(documentId, accessToken) {
  if (!Number.isInteger(documentId) || documentId < 1) {
    throw new TypeError('Mã tài liệu phải là một số nguyên lớn hơn hoặc bằng 1.')
  }

  if (
    typeof accessToken !== 'string'
    || !accessToken
    || accessToken !== accessToken.trim()
  ) {
    throw new TypeError('Access token không hợp lệ.')
  }
}

export function getDocuments({
  accessToken,
  page = 1,
  pageSize = 10,
  search = '',
  fileType = '',
  signal,
} = {}) {
  if (
    typeof accessToken !== 'string'
    || !accessToken
    || accessToken !== accessToken.trim()
  ) {
    throw new TypeError('Access token không hợp lệ.')
  }

  if (!Number.isInteger(page) || page < 1) {
    throw new TypeError('Trang phải là một số nguyên lớn hơn hoặc bằng 1.')
  }

  if (!Number.isInteger(pageSize) || pageSize < 1 || pageSize > 100) {
    throw new TypeError('Kích thước trang phải là số nguyên từ 1 đến 100.')
  }

  if (typeof search !== 'string') {
    throw new TypeError('Từ khóa tìm kiếm phải là một chuỗi.')
  }

  const normalizedSearch = search.trim()
  if (normalizedSearch.length > MAX_DOCUMENT_SEARCH_LENGTH) {
    throw new TypeError(
      `Từ khóa tìm kiếm không được vượt quá ${MAX_DOCUMENT_SEARCH_LENGTH} ký tự.`,
    )
  }

  if (typeof fileType !== 'string') {
    throw new TypeError('Định dạng tài liệu không hợp lệ.')
  }

  const normalizedFileType = fileType.toUpperCase()
  if (normalizedFileType && !DOCUMENT_FILE_TYPES.has(normalizedFileType)) {
    throw new TypeError('Định dạng tài liệu phải là PDF hoặc DOCX.')
  }

  const query = new URLSearchParams({
    page: String(page),
    page_size: String(pageSize),
  })
  if (normalizedSearch) query.set('search', normalizedSearch)
  if (normalizedFileType) query.set('file_type', normalizedFileType)

  return apiClient.get(`/documents?${query.toString()}`, {
    headers: {
      Authorization: `Bearer ${accessToken}`,
    },
    signal,
  })
}

export function getDocumentDetail(documentId, { accessToken, signal } = {}) {
  validateAuthenticatedDocumentRequest(documentId, accessToken)

  return apiClient.get(`/documents/${documentId}`, {
    headers: {
      Authorization: `Bearer ${accessToken}`,
    },
    signal,
  })
}

export function viewDocumentPdf(documentId, { accessToken, signal } = {}) {
  validateAuthenticatedDocumentRequest(documentId, accessToken)

  return apiClient.getBlob(`/documents/${documentId}/view`, {
    headers: {
      Authorization: `Bearer ${accessToken}`,
    },
    signal,
  })
}

export function downloadDocument(documentId, { accessToken, signal } = {}) {
  validateAuthenticatedDocumentRequest(documentId, accessToken)

  return apiClient.getBlob(`/documents/${documentId}/download`, {
    headers: {
      Authorization: `Bearer ${accessToken}`,
    },
    signal,
  })
}

export function deleteDocument(documentId, { accessToken, signal } = {}) {
  validateAuthenticatedDocumentRequest(documentId, accessToken)

  return apiClient.delete(`/documents/${documentId}`, {
    headers: {
      Authorization: `Bearer ${accessToken}`,
    },
    signal,
  })
}

export function uploadDocument({ file, title, accessToken, signal } = {}) {
  if (typeof File === 'undefined' || !(file instanceof File)) {
    throw new TypeError('Tệp tải lên phải là một File hợp lệ.')
  }

  if (title !== undefined && typeof title !== 'string') {
    throw new TypeError('Tiêu đề tài liệu phải là một chuỗi.')
  }

  const extension = file.name.split('.').pop()?.toLowerCase()
  if (!extension || !UPLOAD_FILE_EXTENSIONS.has(extension)) {
    throw new TypeError('Chỉ hỗ trợ tải lên file PDF hoặc DOCX.')
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

export function processDocument(documentId, { accessToken, signal } = {}) {
  validateAuthenticatedDocumentRequest(documentId, accessToken)

  return apiClient.post(`/documents/${documentId}/process`, undefined, {
    headers: {
      Authorization: `Bearer ${accessToken}`,
    },
    signal,
  })
}

export function getDocumentStatus(documentId, { accessToken, signal } = {}) {
  validateAuthenticatedDocumentRequest(documentId, accessToken)

  return apiClient.get(`/documents/${documentId}/status`, {
    headers: {
      Authorization: `Bearer ${accessToken}`,
    },
    signal,
  })
}

export function indexDocument(documentId, { accessToken, signal } = {}) {
  validateAuthenticatedDocumentRequest(documentId, accessToken)

  return apiClient.post(`/documents/${documentId}/index`, undefined, {
    headers: {
      Authorization: `Bearer ${accessToken}`,
    },
    signal,
  })
}

export function getDocumentRagStatus(documentId, { accessToken, signal } = {}) {
  validateAuthenticatedDocumentRequest(documentId, accessToken)

  return apiClient.get(`/documents/${documentId}/rag-status`, {
    headers: {
      Authorization: `Bearer ${accessToken}`,
    },
    signal,
  })
}
