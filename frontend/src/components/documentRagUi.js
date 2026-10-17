import {
  ApiConfigurationError,
  ApiHttpError,
  ApiNetworkError,
} from '../services/apiClient.js'

export const ragStatuses = Object.freeze({
  PENDING: { label: 'Chưa sẵn sàng cho AI', className: 'pending' },
  INDEXING: { label: 'Đang chuẩn bị cho AI', className: 'indexing' },
  READY: { label: 'Sẵn sàng hỏi đáp', className: 'ready' },
  FAILED: { label: 'Chuẩn bị cho AI thất bại', className: 'failed' },
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
    return 'Không thể chuẩn bị tài liệu cho AI. Vui lòng kiểm tra mạng và thử lại.'
  }
  if (error instanceof ApiConfigurationError) {
    return 'Ứng dụng chưa được cấu hình đầy đủ. Vui lòng liên hệ quản trị viên.'
  }
  if (error instanceof ApiHttpError) {
    const messages = {
      401: 'Phiên đăng nhập không hợp lệ hoặc đã hết hạn. Vui lòng đăng nhập lại.',
      404: 'Tài liệu không tồn tại hoặc bạn không có quyền truy cập.',
      409: 'Tài liệu đang được chuẩn bị cho AI hoặc trạng thái hiện tại không cho phép thao tác này.',
      429: 'Hệ thống đang chuẩn bị nhiều tài liệu. Vui lòng chờ một lát rồi thử lại.',
      503: 'Dịch vụ AI hoặc tìm kiếm tài liệu tạm thời không khả dụng.',
      500: 'Hệ thống đang gặp lỗi khi chuẩn bị tài liệu cho AI. Vui lòng thử lại sau.',
    }
    if (messages[error.status]) return messages[error.status]
    if (error.status >= 500) return messages[500]
  }
  return 'Không thể chuẩn bị tài liệu cho AI lúc này.'
}
