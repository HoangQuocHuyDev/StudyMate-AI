import {
  ApiConfigurationError,
  ApiHttpError,
  ApiNetworkError,
} from '../services/apiClient.js'


export function validateDocxPreviewResponse(response, documentId) {
  if (
    !response
    || response.document_id !== documentId
    || typeof response.title !== 'string'
    || !response.title.trim()
    || typeof response.original_filename !== 'string'
    || !response.original_filename.trim()
    || response.file_type !== 'DOCX'
    || typeof response.content !== 'string'
    || !Number.isInteger(response.character_count)
    || response.character_count < 0
  ) {
    throw new TypeError('Phản hồi xem trước tài liệu không hợp lệ.')
  }

  return response
}

export function getDocxPreviewErrorMessage(error) {
  if (error instanceof ApiNetworkError) {
    return 'Không thể tải nội dung xem trước. Vui lòng kiểm tra mạng và thử lại.'
  }
  if (error instanceof ApiConfigurationError) {
    return 'Ứng dụng chưa được cấu hình đầy đủ. Vui lòng liên hệ quản trị viên.'
  }
  if (error instanceof ApiHttpError) {
    const messages = {
      400: 'Tài liệu này không hỗ trợ xem trước dưới dạng văn bản.',
      401: 'Phiên đăng nhập không hợp lệ hoặc đã hết hạn. Vui lòng đăng nhập lại.',
      404: 'Tài liệu không tồn tại hoặc bạn không có quyền truy cập.',
      409: 'Tài liệu chưa được xử lý xong để xem trước.',
      413: 'Nội dung tài liệu vượt quá giới hạn xem trước.',
      500: 'Không thể tạo bản xem trước tài liệu lúc này. Vui lòng thử lại sau.',
    }
    if (messages[error.status]) return messages[error.status]
    if (error.status >= 500) return messages[500]
  }
  return 'Không thể tải nội dung xem trước lúc này.'
}
