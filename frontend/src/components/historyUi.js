import {
  ApiConfigurationError,
  ApiHttpError,
  ApiNetworkError,
} from '../services/apiClient.js'

export const HISTORY_PAGE_SIZE = 20
export const HISTORY_SEARCH_MAX_LENGTH = 255

const supportedFileTypes = new Set(['PDF', 'DOCX'])

function isValidDateTime(value) {
  return typeof value === 'string' && !Number.isNaN(new Date(value).getTime())
}

export function validateHistoryResponse(response, expectedLimit, expectedOffset) {
  if (
    !response
    || typeof response !== 'object'
    || !Array.isArray(response.items)
    || !Number.isInteger(response.total)
    || response.total < 0
    || response.limit !== expectedLimit
    || response.offset !== expectedOffset
  ) {
    throw new TypeError('Phản hồi lịch sử trò chuyện không hợp lệ.')
  }

  for (const item of response.items) {
    if (
      !item
      || !Number.isInteger(item.session_id)
      || item.session_id < 1
      || !Number.isInteger(item.document_id)
      || item.document_id < 1
      || typeof item.title !== 'string'
      || !item.title.trim()
      || typeof item.document_title !== 'string'
      || !item.document_title.trim()
      || !supportedFileTypes.has(item.file_type)
      || !isValidDateTime(item.created_at)
      || !isValidDateTime(item.updated_at)
      || (item.last_message_preview !== null
        && typeof item.last_message_preview !== 'string')
    ) {
      throw new TypeError('Phản hồi lịch sử trò chuyện không hợp lệ.')
    }
  }

  return response
}

export function mergeHistorySessions(currentItems, incomingItems) {
  const merged = currentItems.slice()
  const positions = new Map(
    merged.map((item, index) => [item.session_id, index]),
  )

  for (const item of incomingItems) {
    const existingIndex = positions.get(item.session_id)
    if (existingIndex === undefined) {
      positions.set(item.session_id, merged.length)
      merged.push(item)
    } else {
      merged[existingIndex] = item
    }
  }
  return merged
}

export function isHistoryResponseCurrent(
  requestId,
  activeRequestId,
  requestCriteria,
  activeCriteria,
) {
  return requestId === activeRequestId && requestCriteria === activeCriteria
}

export function getHistoryViewState({ itemCount, loading, error, hasFilters }) {
  if (loading && itemCount === 0) return 'loading'
  if (error && itemCount === 0) return 'error'
  if (itemCount === 0) return hasFilters ? 'filtered-empty' : 'empty'
  return 'ready'
}

export function getHistoryPreview(preview) {
  return typeof preview === 'string' && preview.trim()
    ? preview
    : 'Chưa có nội dung xem trước.'
}

export function formatHistoryDateTime(value) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return 'Không rõ thời gian'
  return new Intl.DateTimeFormat('vi-VN', {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(date)
}

export function getHistoryErrorMessage(error) {
  if (error instanceof ApiNetworkError) {
    return 'Không thể kết nối đến máy chủ để tải lịch sử trò chuyện.'
  }
  if (error instanceof ApiConfigurationError) {
    return 'Frontend chưa được cấu hình địa chỉ Backend hợp lệ.'
  }
  if (error instanceof ApiHttpError) {
    if (error.status === 401) {
      return 'Phiên đăng nhập đã hết hạn. Vui lòng đăng nhập lại.'
    }
    if (error.status === 422) {
      return 'Từ khóa hoặc bộ lọc thời gian không hợp lệ.'
    }
    if (error.status >= 500) {
      return 'Hệ thống đang gặp lỗi khi tải lịch sử. Vui lòng thử lại sau.'
    }
  }
  return 'Không thể tải lịch sử trò chuyện lúc này.'
}
