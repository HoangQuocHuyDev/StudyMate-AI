import {
  ApiConfigurationError,
  ApiHttpError,
  ApiNetworkError,
} from '../services/apiClient.js'
import { MAX_CHAT_QUESTION_LENGTH } from '../services/chatService.js'

export function isChatReadyDocument(document) {
  return Boolean(
    document
    && document.status === 'READY'
    && document.rag_status === 'READY'
    && Number.isInteger(document.chunk_count)
    && document.chunk_count > 0,
  )
}

export function classifyDocumentForChat(document, ragStatus) {
  if (!document || !Number.isInteger(document.id)) {
    throw new TypeError('Tài liệu không hợp lệ.')
  }
  if (!ragStatus || ragStatus.document_id !== document.id) {
    throw new TypeError('Phản hồi trạng thái RAG không hợp lệ.')
  }
  const enriched = { ...document, ...ragStatus }
  if (isChatReadyDocument(enriched) && enriched.chunk_count > 0) {
    return { kind: 'ready', document: { ...enriched, chat_status: 'ready' } }
  }
  if (enriched.status !== 'READY') {
    return { kind: 'not_processed', document: { ...enriched, chat_status: 'not_processed' } }
  }
  if (!Number.isInteger(enriched.chunk_count) || enriched.chunk_count < 1) {
    return { kind: 'no_chunks', document: { ...enriched, chat_status: 'no_chunks' } }
  }
  if (enriched.rag_status === 'INDEXING') {
    return { kind: 'indexing', document: { ...enriched, chat_status: 'indexing' } }
  }
  if (enriched.rag_status === 'FAILED') {
    return { kind: 'index_failed', document: { ...enriched, chat_status: 'index_failed' } }
  }
  return { kind: 'not_indexed', document: { ...enriched, chat_status: 'not_indexed' } }
}

export function getRagStatusFailureKind(error) {
  if (error instanceof ApiHttpError && error.status === 401) return 'unauthorized'
  if (error instanceof ApiHttpError && error.status === 404) return 'deleted'
  return 'unavailable'
}

export function unavailableChatDocument(document) {
  return {
    ...document,
    chat_status: 'unavailable',
    rag_status: null,
    chunk_count: null,
  }
}

export function getChatDocumentStatusLabel(document) {
  const labels = {
    ready: 'Sẵn sàng hỏi đáp',
    not_processed: 'Chưa xử lý',
    no_chunks: 'Chưa có nội dung',
    not_indexed: 'Chưa sẵn sàng cho AI',
    indexing: 'Đang chuẩn bị cho AI',
    index_failed: 'Chuẩn bị cho AI thất bại',
    unavailable: 'Không kiểm tra được trạng thái',
  }
  return labels[document?.chat_status] ?? 'Chưa sẵn sàng'
}

export function chooseChatDocumentId(documents, currentDocumentId) {
  const ready = documents.filter(isChatReadyDocument)
  return ready.some((document) => document.id === currentDocumentId)
    ? currentDocumentId
    : ready[0]?.id ?? null
}

export function buildChatStatusMessages(documents) {
  const counts = new Map()
  for (const document of documents) {
    if (document?.chat_status && document.chat_status !== 'ready') {
      counts.set(document.chat_status, (counts.get(document.chat_status) ?? 0) + 1)
    }
  }
  const messages = []
  const add = (kind, text) => {
    const count = counts.get(kind) ?? 0
    if (count > 0) messages.push(`${count} tài liệu ${text}`)
  }
  add('not_processed', 'chưa xử lý xong.')
  add('no_chunks', 'chưa có nội dung để tra cứu.')
  add('not_indexed', 'chưa được chuẩn bị cho AI.')
  add('indexing', 'đang được chuẩn bị cho AI.')
  add('index_failed', 'chuẩn bị cho AI thất bại.')
  add('unavailable', 'không thể kiểm tra trạng thái do lỗi kết nối hoặc hệ thống.')
  return messages
}

export function getRetryAfterSeconds(error) {
  if (!(error instanceof ApiHttpError) || error.status !== 429) return null
  const raw = typeof error.retryAfter === 'string' ? error.retryAfter.trim() : ''
  if (!/^\d+$/.test(raw)) return null
  const seconds = Number(raw)
  return Number.isSafeInteger(seconds) && seconds > 0 && seconds <= 86400
    ? seconds
    : null
}

export function getQuestionValidationMessage(question) {
  if (typeof question !== 'string' || !question.trim()) {
    return 'Vui lòng nhập câu hỏi trước khi gửi.'
  }
  if (question.trim().length > MAX_CHAT_QUESTION_LENGTH) {
    return `Câu hỏi không được vượt quá ${MAX_CHAT_QUESTION_LENGTH.toLocaleString('vi-VN')} ký tự.`
  }
  return null
}

export function getChatErrorMessage(error) {
  if (error instanceof ApiNetworkError) {
    return 'Không thể kết nối đến hệ thống. Vui lòng kiểm tra mạng và thử lại.'
  }
  if (error instanceof ApiConfigurationError) {
    return 'Ứng dụng chưa được cấu hình đầy đủ. Vui lòng liên hệ quản trị viên.'
  }
  if (error instanceof ApiHttpError) {
    if (error.status === 429) {
      const retryAfter = getRetryAfterSeconds(error)
      return retryAfter
        ? `Hệ thống hỏi đáp đang bận. Vui lòng thử lại sau ${retryAfter} giây.`
        : 'Hệ thống hỏi đáp đang bận hoặc đã đạt giới hạn sử dụng. Vui lòng thử lại sau.'
    }
    const messages = {
      401: 'Phiên đăng nhập không hợp lệ hoặc đã hết hạn.',
      404: 'Tài liệu hoặc cuộc trò chuyện không tồn tại, hoặc bạn không có quyền truy cập.',
      409: 'Tài liệu chưa sẵn sàng hoặc cuộc trò chuyện đang được cập nhật.',
      422: 'Câu hỏi hoặc thông tin cuộc trò chuyện không hợp lệ.',
      500: 'Hệ thống đang gặp lỗi. Vui lòng thử lại sau.',
      503: 'Dịch vụ AI hoặc tra cứu tài liệu tạm thời không khả dụng. Vui lòng thử lại sau.',
      504: 'Lượt hỏi đáp đã vượt quá thời gian chờ. Kết quả có thể chưa được lưu; vui lòng kiểm tra lịch sử trước khi gửi lại.',
    }
    if (messages[error.status]) return messages[error.status]
    if (error.status >= 500) return messages[500]
  }
  return 'Không thể hoàn tất yêu cầu lúc này. Vui lòng thử lại.'
}

export function mergeUniqueById(current, incoming) {
  const items = new Map()
  for (const item of [...current, ...incoming]) {
    if (item && Number.isInteger(item.id)) items.set(item.id, item)
  }
  return [...items.values()]
}

export function mergeChatMessages(current, incoming) {
  return mergeUniqueById(current, incoming).sort((left, right) => (
    (Number.isInteger(left.sequence_no) ? left.sequence_no : Number.MAX_SAFE_INTEGER)
    - (Number.isInteger(right.sequence_no) ? right.sequence_no : Number.MAX_SAFE_INTEGER)
  ))
}

export function validateChatMessageCursorPage(response, sessionId, limit) {
  const cursorIsValid = response?.next_before_sequence_no === null
    || (Number.isInteger(response?.next_before_sequence_no)
      && response.next_before_sequence_no >= 0)
  if (
    !response
    || response.session_id !== sessionId
    || !Array.isArray(response.items)
    || !Number.isInteger(response.total)
    || response.total < 0
    || response.limit !== limit
    || typeof response.has_more !== 'boolean'
    || !cursorIsValid
    || (response.has_more && response.next_before_sequence_no === null)
    || (!response.has_more && response.next_before_sequence_no !== null)
  ) {
    throw new TypeError('Phản hồi phân trang tin nhắn không hợp lệ.')
  }
  return response
}

export function getPrependedScrollTop({
  previousScrollTop,
  previousScrollHeight,
  nextScrollHeight,
}) {
  if (![previousScrollTop, previousScrollHeight, nextScrollHeight].every(
    (value) => Number.isFinite(value) && value >= 0,
  )) {
    throw new TypeError('Thông số vị trí cuộn không hợp lệ.')
  }
  return previousScrollTop + Math.max(0, nextScrollHeight - previousScrollHeight)
}

export function isChatResponseCurrent({
  requestVersion,
  currentRequestVersion,
  documentId,
  currentDocumentId,
  sessionId,
  currentSessionId,
}) {
  return requestVersion === currentRequestVersion
    && (documentId === undefined || documentId === currentDocumentId)
    && (sessionId === undefined || sessionId === currentSessionId)
}

export async function mapWithConcurrency(items, limit, mapper) {
  if (!Array.isArray(items) || !Number.isInteger(limit) || limit < 1) {
    throw new TypeError('Cấu hình xử lý đồng thời không hợp lệ.')
  }
  const results = new Array(items.length)
  let nextIndex = 0
  async function worker() {
    while (nextIndex < items.length) {
      const index = nextIndex
      nextIndex += 1
      results[index] = await mapper(items[index], index)
    }
  }
  await Promise.all(Array.from(
    { length: Math.min(limit, items.length) },
    () => worker(),
  ))
  return results
}

export function citationLabel(citation) {
  const sourceNumber = citation.citation_order + 1
  const chunkNumber = citation.chunk_index + 1
  return `Nguồn ${sourceNumber} — Đoạn ${chunkNumber}`
}
