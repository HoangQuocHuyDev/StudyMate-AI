import {
  ApiConfigurationError,
  ApiHttpError,
  ApiNetworkError,
} from '../services/apiClient.js'

export const DASHBOARD_DOCUMENT_LIMIT = 5

export const DASHBOARD_STATISTICS = Object.freeze([
  {
    field: 'document_count',
    label: 'Tổng tài liệu',
    description: 'Tài liệu hiện có',
    icon: 'documents',
    tone: 'blue',
  },
  {
    field: 'ready_document_count',
    label: 'Tài liệu sẵn sàng',
    description: 'Đã xử lý nội dung',
    icon: 'check',
    tone: 'green',
  },
  {
    field: 'summary_count',
    label: 'Bản tóm tắt đã tạo',
    description: 'Tổng số bản tóm tắt đã lưu',
    icon: 'summary',
    tone: 'violet',
  },
  {
    field: 'chat_session_count',
    label: 'Phiên hội thoại AI',
    description: 'Tổng số phiên trò chuyện',
    icon: 'chat',
    tone: 'cyan',
  },
])

export const DASHBOARD_FEATURES = Object.freeze([
  {
    icon: 'upload',
    title: 'Tải lên tài liệu',
    description: 'Lưu trữ và quản lý tài liệu học tập của bạn ở một nơi.',
    link: 'Thêm tài liệu',
    tone: 'blue',
    path: '/documents',
  },
  {
    icon: 'sparkle',
    title: 'Tóm tắt thông minh',
    description: 'Nắm bắt nội dung chính từ tài liệu dài chỉ trong vài phút.',
    link: 'Bắt đầu tóm tắt',
    tone: 'violet',
    path: '/summarize',
  },
  {
    icon: 'chat',
    title: 'Hỏi đáp cùng AI',
    description: 'Đặt câu hỏi và nhận câu trả lời dựa trên chính tài liệu của bạn.',
    link: 'Đặt câu hỏi',
    tone: 'cyan',
    path: '/chat',
  },
])

const documentStatuses = Object.freeze({
  UPLOADED: { label: 'Chưa xử lý', className: 'uploaded' },
  PROCESSING: { label: 'Đang xử lý', className: 'processing' },
  READY: { label: 'Đã xử lý', className: 'complete' },
  FAILED: { label: 'Xử lý thất bại', className: 'failed' },
})

export const initialDashboardDocumentsState = Object.freeze({
  activeRequestId: 0,
  data: null,
  error: '',
  status: 'idle',
})

export const initialDashboardOverviewState = Object.freeze({
  activeRequestId: 0,
  data: null,
  error: '',
  status: 'idle',
})

export function validateDashboardOverviewResponse(response) {
  if (!response || typeof response !== 'object') {
    throw new TypeError('Phản hồi thống kê Dashboard không hợp lệ.')
  }

  const normalized = {}
  for (const { field } of DASHBOARD_STATISTICS) {
    const value = response[field]
    if (!Number.isInteger(value) || value < 0) {
      throw new TypeError('Phản hồi thống kê Dashboard không hợp lệ.')
    }
    normalized[field] = value
  }
  return normalized
}

export function getDashboardStatisticCards(overview) {
  const validated = validateDashboardOverviewResponse(overview)
  return DASHBOARD_STATISTICS.map((statistic) => ({
    ...statistic,
    value: validated[statistic.field],
  }))
}

export function isDashboardOverviewEmpty(overview) {
  return getDashboardStatisticCards(overview).every(({ value }) => value === 0)
}

export function dashboardOverviewReducer(state, action) {
  if (action.type === 'request-started') {
    return {
      ...state,
      activeRequestId: action.requestId,
      error: '',
      status: 'loading',
    }
  }

  if (action.requestId !== state.activeRequestId) return state

  if (action.type === 'request-succeeded') {
    return {
      ...state,
      data: action.data,
      error: '',
      status: 'success',
    }
  }

  if (action.type === 'request-failed') {
    return {
      ...state,
      error: action.error,
      status: 'error',
    }
  }

  return state
}

export function getDashboardOverviewErrorMessage(error) {
  if (error instanceof ApiNetworkError) {
    return 'Không thể kết nối để tải số liệu tổng quan. Vui lòng kiểm tra mạng và thử lại.'
  }
  if (error instanceof ApiConfigurationError) {
    return 'Ứng dụng chưa được cấu hình đầy đủ. Vui lòng liên hệ quản trị viên.'
  }
  if (error instanceof ApiHttpError) {
    if (error.status === 401) {
      return 'Phiên đăng nhập không hợp lệ hoặc đã hết hạn. Vui lòng đăng nhập lại.'
    }
    if (error.status >= 500) {
      return 'Hệ thống đang gặp lỗi khi tải số liệu tổng quan. Vui lòng thử lại sau.'
    }
  }
  return 'Không thể tải số liệu tổng quan lúc này.'
}

export function validateDashboardDocumentsResponse(response) {
  if (
    !response
    || !Array.isArray(response.items)
    || !Number.isInteger(response.total)
    || response.total < 0
  ) {
    throw new TypeError('Phản hồi danh sách tài liệu không hợp lệ.')
  }

  for (const document of response.items) {
    if (
      !document
      || !Number.isInteger(document.id)
      || document.id < 1
      || typeof document.title !== 'string'
      || !document.title.trim()
      || !['PDF', 'DOCX'].includes(document.file_type)
      || typeof document.created_at !== 'string'
      || typeof document.status !== 'string'
    ) {
      throw new TypeError('Phản hồi danh sách tài liệu không hợp lệ.')
    }
  }

  return {
    items: response.items.slice(0, DASHBOARD_DOCUMENT_LIMIT),
    total: response.total,
  }
}

export function dashboardDocumentsReducer(state, action) {
  if (action.type === 'request-started') {
    return {
      ...state,
      activeRequestId: action.requestId,
      error: '',
      status: 'loading',
    }
  }

  if (action.requestId !== state.activeRequestId) return state

  if (action.type === 'request-succeeded') {
    return {
      ...state,
      data: action.data,
      error: '',
      status: 'success',
    }
  }

  if (action.type === 'request-failed') {
    return {
      ...state,
      error: action.error,
      status: 'error',
    }
  }

  return state
}

export function getDashboardDocumentsErrorMessage(error) {
  if (error instanceof ApiNetworkError) {
    return 'Không thể kết nối để tải tài liệu gần đây. Vui lòng kiểm tra mạng và thử lại.'
  }
  if (error instanceof ApiConfigurationError) {
    return 'Ứng dụng chưa được cấu hình đầy đủ. Vui lòng liên hệ quản trị viên.'
  }
  if (error instanceof ApiHttpError) {
    if (error.status === 401) {
      return 'Phiên đăng nhập không hợp lệ hoặc đã hết hạn. Vui lòng đăng nhập lại.'
    }
    if (error.status >= 500) {
      return 'Hệ thống đang gặp lỗi khi tải tài liệu gần đây. Vui lòng thử lại sau.'
    }
  }
  return 'Không thể tải tài liệu gần đây lúc này.'
}

export function getDashboardDocumentStatus(status) {
  return documentStatuses[status] ?? {
    label: 'Không xác định',
    className: 'waiting',
  }
}

export function formatDashboardDocumentDate(value) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return 'Không rõ thời gian'
  return new Intl.DateTimeFormat('vi-VN', { dateStyle: 'medium' }).format(date)
}
