import apiClient from './apiClient.js'

export const MAX_CHAT_QUESTION_LENGTH = 2000
export const MAX_CHAT_HISTORY_SEARCH_LENGTH = 255
const MAX_PAGE_SIZE = 100
const CHAT_HISTORY_PERIODS = new Set(['', 'today', 'week', 'month'])

function validateAccessToken(accessToken) {
  if (
    typeof accessToken !== 'string'
    || !accessToken
    || accessToken !== accessToken.trim()
  ) {
    throw new TypeError('Access token không hợp lệ.')
  }
}

function validatePositiveId(value, name) {
  if (!Number.isInteger(value) || value < 1) {
    throw new TypeError(`${name} phải là số nguyên lớn hơn hoặc bằng 1.`)
  }
}

function validatePagination(limit, offset) {
  if (!Number.isInteger(limit) || limit < 1 || limit > MAX_PAGE_SIZE) {
    throw new TypeError('Giới hạn phải là số nguyên từ 1 đến 100.')
  }
  if (!Number.isInteger(offset) || offset < 0) {
    throw new TypeError('Vị trí bắt đầu phải là số nguyên không âm.')
  }
}

function authenticatedOptions(accessToken, signal) {
  validateAccessToken(accessToken)
  return {
    headers: { Authorization: `Bearer ${accessToken}` },
    signal,
  }
}

export function askDocument(
  documentId,
  question,
  sessionId = null,
  { accessToken, signal } = {},
) {
  validatePositiveId(documentId, 'Mã tài liệu')
  if (typeof question !== 'string') {
    throw new TypeError('Câu hỏi phải là một chuỗi.')
  }
  const normalizedQuestion = question.trim()
  if (!normalizedQuestion) {
    throw new TypeError('Câu hỏi không được để trống.')
  }
  if (normalizedQuestion.length > MAX_CHAT_QUESTION_LENGTH) {
    throw new TypeError(
      `Câu hỏi không được vượt quá ${MAX_CHAT_QUESTION_LENGTH} ký tự.`,
    )
  }
  if (sessionId !== null && sessionId !== undefined) {
    validatePositiveId(sessionId, 'Mã cuộc trò chuyện')
  }

  return apiClient.post('/chat/ask', {
    document_id: documentId,
    question: normalizedQuestion,
    session_id: sessionId ?? null,
  }, authenticatedOptions(accessToken, signal))
}

export function getChatSessions(
  documentId,
  limit = 20,
  offset = 0,
  { accessToken, signal } = {},
) {
  validatePositiveId(documentId, 'Mã tài liệu')
  validatePagination(limit, offset)
  const query = new URLSearchParams({
    document_id: String(documentId),
    limit: String(limit),
    offset: String(offset),
  })
  return apiClient.get(
    `/chat/sessions?${query.toString()}`,
    authenticatedOptions(accessToken, signal),
  )
}

export function getChatMessages(
  sessionId,
  limit = 50,
  offset = 0,
  { accessToken, signal } = {},
) {
  validatePositiveId(sessionId, 'Mã cuộc trò chuyện')
  validatePagination(limit, offset)
  return apiClient.get(
    `/chat/sessions/${sessionId}/messages?limit=${limit}&offset=${offset}`,
    authenticatedOptions(accessToken, signal),
  )
}

export function getChatMessagesCursor(
  sessionId,
  beforeSequenceNo = null,
  limit = 50,
  { accessToken, signal } = {},
) {
  validatePositiveId(sessionId, 'Mã cuộc trò chuyện')
  if (!Number.isInteger(limit) || limit < 1 || limit > 50) {
    throw new TypeError('Giới hạn tin nhắn phải là số nguyên từ 1 đến 50.')
  }
  if (
    beforeSequenceNo !== null
    && beforeSequenceNo !== undefined
    && (!Number.isInteger(beforeSequenceNo) || beforeSequenceNo < 0)
  ) {
    throw new TypeError('Cursor tin nhắn phải là số nguyên không âm.')
  }
  const query = new URLSearchParams({ limit: String(limit) })
  if (beforeSequenceNo !== null && beforeSequenceNo !== undefined) {
    query.set('before_sequence_no', String(beforeSequenceNo))
  }
  return apiClient.get(
    `/chat/sessions/${sessionId}/messages/cursor?${query.toString()}`,
    authenticatedOptions(accessToken, signal),
  )
}

export function getChatHistory(
  {
    limit = 20,
    offset = 0,
    search = '',
    period = '',
  } = {},
  { accessToken, signal } = {},
) {
  validatePagination(limit, offset)
  if (typeof search !== 'string') {
    throw new TypeError('Từ khóa tìm kiếm phải là một chuỗi.')
  }
  const normalizedSearch = search.trim()
  if (normalizedSearch.length > MAX_CHAT_HISTORY_SEARCH_LENGTH) {
    throw new TypeError(
      `Từ khóa tìm kiếm không được vượt quá ${MAX_CHAT_HISTORY_SEARCH_LENGTH} ký tự.`,
    )
  }
  if (typeof period !== 'string' || !CHAT_HISTORY_PERIODS.has(period)) {
    throw new TypeError('Khoảng thời gian lọc không hợp lệ.')
  }

  const query = new URLSearchParams({
    limit: String(limit),
    offset: String(offset),
  })
  if (normalizedSearch) query.set('search', normalizedSearch)
  if (period) query.set('period', period)

  return apiClient.get(
    `/chat/history?${query.toString()}`,
    authenticatedOptions(accessToken, signal),
  )
}

export function getChatCitation(
  chunkId,
  sessionId,
  messageId,
  { accessToken, signal } = {},
) {
  validatePositiveId(chunkId, 'Mã đoạn trích dẫn')
  validatePositiveId(sessionId, 'Mã cuộc trò chuyện')
  validatePositiveId(messageId, 'Mã tin nhắn')
  const query = new URLSearchParams({
    session_id: String(sessionId),
    message_id: String(messageId),
  })
  return apiClient.get(
    `/chat/citations/${chunkId}?${query.toString()}`,
    authenticatedOptions(accessToken, signal),
  )
}
