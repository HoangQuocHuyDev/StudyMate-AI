import {
  ApiConfigurationError,
  ApiHttpError,
  ApiNetworkError,
} from '../services/apiClient.js'

export const initialDocumentDeletionUiState = Object.freeze({
  document: null,
  state: 'idle',
  message: '',
})

export function documentDeletionUiReducer(current, action) {
  switch (action?.type) {
    case 'open':
      return { document: action.document, state: 'idle', message: '' }
    case 'start':
      return current.document
        ? { ...current, state: 'deleting', message: action.message ?? '' }
        : current
    case 'error':
      return current.document
        ? { ...current, state: 'error', message: action.message ?? '' }
        : current
    case 'close':
      return current.state === 'deleting' ? current : initialDocumentDeletionUiState
    case 'complete':
      return initialDocumentDeletionUiState
    default:
      return current
  }
}

export function getDocumentDeletionErrorMessage(error) {
  if (error instanceof ApiNetworkError) {
    return 'Không nhận được xác nhận từ Backend. Tài liệu có thể đang được hệ thống tiếp tục xóa; hãy làm mới danh sách trước khi thử lại.'
  }
  if (error instanceof ApiConfigurationError) {
    return 'Frontend chưa được cấu hình địa chỉ Backend hợp lệ.'
  }
  if (error instanceof ApiHttpError) {
    if (error.status === 401) {
      return 'Phiên đăng nhập đã hết hạn. Vui lòng đăng nhập lại.'
    }
    if (error.status === 404) {
      return 'Tài liệu không còn tồn tại hoặc bạn không có quyền truy cập.'
    }
    if (error.status === 409) {
      return 'Tài liệu đang được xử lý, lập chỉ mục hoặc có một yêu cầu xóa khác đang thực hiện.'
    }
    if (error.status >= 500) {
      return 'Backend chưa xác nhận hoàn tất. Tài liệu có thể đang được hệ thống tiếp tục xóa; hãy làm mới danh sách trước khi thử lại.'
    }
  }
  return 'Không thể xác nhận kết quả xóa tài liệu lúc này. Vui lòng làm mới danh sách trước khi thử lại.'
}

export function removeDocumentFromPage(documents, documentId) {
  if (!Array.isArray(documents)) throw new TypeError('Danh sách tài liệu không hợp lệ.')
  return documents.filter((document) => document?.id !== documentId)
}

export function decrementDocumentPagination(pagination) {
  const total = Math.max(0, (pagination?.total ?? 0) - 1)
  const pageSize = pagination?.pageSize ?? 10
  const totalPages = total === 0 ? 0 : Math.ceil(total / pageSize)
  return {
    ...pagination,
    total,
    totalPages,
  }
}

export function createDocumentDeletionGuard() {
  const activeDocumentIds = new Set()
  return {
    tryStart(documentId) {
      if (activeDocumentIds.has(documentId)) return false
      activeDocumentIds.add(documentId)
      return true
    },
    finish(documentId) {
      activeDocumentIds.delete(documentId)
    },
    isActive(documentId) {
      return activeDocumentIds.has(documentId)
    },
    clear() {
      activeDocumentIds.clear()
    },
  }
}
