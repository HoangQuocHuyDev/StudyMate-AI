import {
  ApiConfigurationError,
  ApiHttpError,
  ApiNetworkError,
} from '../services/apiClient.js'

export const ragStatuses = Object.freeze({
  PENDING: { label: 'Chưa lập chỉ mục', className: 'pending' },
  INDEXING: { label: 'Đang lập chỉ mục', className: 'indexing' },
  READY: { label: 'Sẵn sàng hỏi đáp', className: 'ready' },
  FAILED: { label: 'Lập chỉ mục thất bại', className: 'failed' },
})

export function getRagStatusPresentation(ragStatus) {
  return ragStatuses[ragStatus] ?? {
    label: 'Chưa rõ trạng thái AI',
    className: 'unknown',
  }
}

export function canIndexDocument(document) {
  return document?.status === 'READY'
    && Number.isInteger(document.chunk_count)
    && document.chunk_count > 0
    && ['PENDING', 'FAILED'].includes(document.rag_status)
    && document.can_index === true
}

export function getIndexingErrorMessage(error) {
  if (error instanceof ApiNetworkError) {
    return 'Không thể kết nối đến Backend để lập chỉ mục AI.'
  }
  if (error instanceof ApiConfigurationError) {
    return 'Frontend chưa được cấu hình địa chỉ Backend hợp lệ.'
  }
  if (error instanceof ApiHttpError) {
    const messages = {
      401: 'Phiên đăng nhập không hợp lệ hoặc đã hết hạn. Vui lòng đăng nhập lại.',
      404: 'Tài liệu không tồn tại hoặc bạn không có quyền truy cập.',
      409: 'Tài liệu đang được lập chỉ mục hoặc trạng thái hiện tại không cho phép thao tác này.',
      503: 'Dịch vụ AI hoặc cơ sở dữ liệu vector tạm thời không khả dụng.',
      500: 'Hệ thống đang gặp lỗi khi lập chỉ mục. Vui lòng thử lại sau.',
    }
    if (messages[error.status]) return messages[error.status]
    if (error.status >= 500) return messages[500]
  }
  return 'Không thể lập chỉ mục tài liệu lúc này.'
}
