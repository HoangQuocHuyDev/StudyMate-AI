import {
  ApiConfigurationError,
  ApiHttpError,
  ApiNetworkError,
} from '../services/apiClient.js'
import { SUMMARY_TYPES } from '../services/summaryService.js'

export const DEFAULT_SUMMARY_TYPE = 'STANDARD'

export const SUMMARY_TYPE_OPTIONS = Object.freeze([
  {
    id: 'SHORT',
    label: 'Ngắn gọn',
    description: 'Các ý chính quan trọng nhất',
    estimate: 'Khoảng 1–2 phút đọc',
  },
  {
    id: 'STANDARD',
    label: 'Tiêu chuẩn',
    description: 'Cân bằng giữa độ dài và chi tiết',
    estimate: 'Khoảng 3–5 phút đọc',
  },
  {
    id: 'DETAILED',
    label: 'Chi tiết',
    description: 'Đầy đủ luận điểm và giải thích',
    estimate: 'Khoảng 7–10 phút đọc',
  },
])

export function isSummaryReadyDocument(document) {
  return Boolean(
    document
    && document.status === 'READY'
    && Number.isInteger(document.chunk_count)
    && document.chunk_count > 0,
  )
}

export function mergeDocumentsById(currentDocuments, newDocuments) {
  const merged = new Map()
  for (const document of [...currentDocuments, ...newDocuments]) {
    if (document && Number.isInteger(document.id)) merged.set(document.id, document)
  }
  return [...merged.values()]
}

export function chooseSelectedDocumentId(documents, currentDocumentId) {
  return documents.some((document) => document.id === currentDocumentId)
    ? currentDocumentId
    : documents[0]?.id ?? null
}

export function removeDocumentAndChooseSelection(
  documents,
  removedDocumentId,
  currentDocumentId,
) {
  const remainingDocuments = documents.filter(
    (document) => document.id !== removedDocumentId,
  )
  return {
    documents: remainingDocuments,
    selectedDocumentId: currentDocumentId === removedDocumentId
      ? remainingDocuments[0]?.id ?? null
      : chooseSelectedDocumentId(remainingDocuments, currentDocumentId),
  }
}

export function getDocumentStatusFailureKind(error) {
  if (error instanceof ApiHttpError && error.status === 401) return 'unauthorized'
  if (error instanceof ApiHttpError && error.status === 404) return 'deleted'
  return 'unavailable'
}

export function classifyDocumentForSummary(document, status) {
  if (!status || status.document_id !== document.id) {
    throw new TypeError('Phản hồi trạng thái tài liệu không hợp lệ.')
  }
  const enriched = { ...document, ...status }
  if (isSummaryReadyDocument(enriched)) return { kind: 'ready', document: enriched }
  if (enriched.status !== 'READY') return { kind: 'not_ready', document: enriched }
  return { kind: 'no_chunks', document: enriched }
}

export function buildDocumentStatusMessages(counts = {}) {
  const messages = []
  if (counts.notReady > 0) {
    messages.push(`${counts.notReady} tài liệu chưa xử lý xong.`)
  }
  if (counts.noChunks > 0) {
    messages.push(`${counts.noChunks} tài liệu đã xử lý nhưng chưa có đoạn nội dung.`)
  }
  if (counts.unavailable > 0) {
    messages.push(`Không thể kiểm tra trạng thái của ${counts.unavailable} tài liệu do lỗi kết nối hoặc máy chủ.`)
  }
  if (counts.deleted > 0) {
    messages.push(`${counts.deleted} tài liệu không còn tồn tại hoặc quyền truy cập đã thay đổi.`)
  }
  return messages
}

export function getRetryAfterSeconds(error) {
  if (!(error instanceof ApiHttpError) || error.status !== 429) return null
  const value = typeof error.retryAfter === 'string' ? error.retryAfter.trim() : ''
  if (!/^\d+$/.test(value)) return null
  const seconds = Number(value)
  return Number.isSafeInteger(seconds) && seconds > 0 && seconds <= 86400
    ? seconds
    : null
}

export function canGenerateSummary({
  document,
  existingSummary,
  isLoading = false,
  requestActive = false,
}) {
  return isSummaryReadyDocument(document)
    && !existingSummary
    && !isLoading
    && !requestActive
}

export function isSummaryResponseCurrent({
  requestVersion,
  currentRequestVersion,
  documentId,
  currentDocumentId,
}) {
  return requestVersion === currentRequestVersion
    && documentId === currentDocumentId
}

export function indexDocumentSummaries(response, documentId) {
  if (
    !response
    || response.document_id !== documentId
    || !Array.isArray(response.items)
  ) {
    throw new TypeError('Phản hồi danh sách bản tóm tắt không hợp lệ.')
  }

  const indexed = {}
  for (const item of response.items) {
    if (
      !item
      || item.document_id !== documentId
      || !Number.isInteger(item.summary_id)
      || !SUMMARY_TYPES.includes(item.summary_type)
      || typeof item.content !== 'string'
      || !item.content.trim()
    ) {
      throw new TypeError('Phản hồi danh sách bản tóm tắt không hợp lệ.')
    }
    indexed[item.summary_type] = { ...item, from_cache: true }
  }
  return indexed
}

export function validateGeneratedSummary(response, documentId, summaryType) {
  if (
    !response
    || response.document_id !== documentId
    || response.summary_type !== summaryType
    || !Number.isInteger(response.summary_id)
    || typeof response.content !== 'string'
    || !response.content.trim()
    || typeof response.from_cache !== 'boolean'
  ) {
    throw new TypeError('Phản hồi tạo bản tóm tắt không hợp lệ.')
  }
  return response
}

export function getSummaryErrorMessage(error) {
  if (error instanceof ApiNetworkError) {
    return 'Không thể kết nối đến Backend. Vui lòng kiểm tra mạng và thử lại.'
  }
  if (error instanceof ApiConfigurationError) {
    return 'Frontend chưa được cấu hình địa chỉ Backend hợp lệ.'
  }
  if (error instanceof ApiHttpError) {
    if (error.status === 409) {
      const detail = typeof error.data?.detail === 'string' ? error.data.detail : ''
      if (detail.includes('đang được tạo bởi một yêu cầu khác')) {
        return 'Bản tóm tắt này đang được tạo bởi một yêu cầu khác. Vui lòng chờ rồi tải lại bản đã lưu.'
      }
      return 'Tài liệu chưa sẵn sàng, chưa có nội dung đã xử lý hoặc đang được cập nhật.'
    }
    if (error.status === 429) {
      const retryAfter = getRetryAfterSeconds(error)
      return retryAfter
        ? `Hệ thống đang bận. Vui lòng thử lại sau ${retryAfter} giây.`
        : 'Hệ thống tóm tắt đang bận hoặc đã đạt giới hạn sử dụng. Vui lòng thử lại sau.'
    }
    const messages = {
      401: 'Phiên đăng nhập không hợp lệ hoặc đã hết hạn.',
      404: 'Tài liệu không tồn tại hoặc bạn không có quyền truy cập.',
      413: 'Tài liệu vượt quá giới hạn mà dịch vụ tóm tắt có thể xử lý.',
      422: 'Tài liệu hoặc loại bản tóm tắt không hợp lệ.',
      500: 'Hệ thống đang gặp lỗi. Vui lòng thử lại sau.',
      503: 'Dịch vụ AI tạm thời không khả dụng. Vui lòng thử lại sau.',
      504: 'Quá trình tóm tắt đã vượt quá thời gian chờ. Kết quả có thể chưa được lưu; hãy tải lại bản đã lưu trước khi thử lại.',
    }
    if (messages[error.status]) return messages[error.status]
    if (error.status >= 500) return messages[500]
  }
  return 'Không thể hoàn tất yêu cầu tóm tắt lúc này. Vui lòng thử lại.'
}

export async function copySummaryContent(
  content,
  clipboard = globalThis.navigator?.clipboard,
) {
  if (typeof content !== 'string' || !content) {
    throw new TypeError('Không có nội dung để sao chép.')
  }
  if (!clipboard || typeof clipboard.writeText !== 'function') {
    throw new Error('Trình duyệt không hỗ trợ sao chép tự động.')
  }
  await clipboard.writeText(content)
}
