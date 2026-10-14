import assert from 'node:assert/strict'
import test from 'node:test'

import { ApiHttpError } from '../src/services/apiClient.js'
import {
  buildChatStatusMessages,
  chooseChatDocumentId,
  classifyDocumentForChat,
  citationLabel,
  getChatDocumentStatusLabel,
  getChatErrorMessage,
  getPrependedScrollTop,
  getRagStatusFailureKind,
  getQuestionValidationMessage,
  isChatReadyDocument,
  isChatResponseCurrent,
  mapWithConcurrency,
  mergeChatMessages,
  mergeUniqueById,
  unavailableChatDocument,
  validateChatMessageCursorPage,
} from '../src/components/chatUi.js'

test('only processed and indexed documents are chat-ready', () => {
  assert.equal(isChatReadyDocument({ status: 'READY', rag_status: 'READY', chunk_count: 1 }), true)
  assert.equal(isChatReadyDocument({ status: 'READY', rag_status: 'READY', chunk_count: 0 }), false)
  assert.equal(isChatReadyDocument({ status: 'READY', rag_status: 'PENDING', chunk_count: 1 }), false)
  assert.equal(isChatReadyDocument({ status: 'UPLOADED', rag_status: 'READY', chunk_count: 1 }), false)
  assert.equal(isChatReadyDocument(null), false)
})

test('question validation rejects blank and overlong content', () => {
  assert.match(getQuestionValidationMessage('   '), /nhập câu hỏi/i)
  assert.match(getQuestionValidationMessage('x'.repeat(2001)), /2.000/)
  assert.equal(getQuestionValidationMessage('Câu hỏi hợp lệ'), null)
})

test('citation labels use only backend citation metadata', () => {
  assert.equal(citationLabel({ citation_order: 0, chunk_index: 2 }), 'Nguồn 1 — Đoạn 3')
})

test('pagination merge keeps one item per backend id', () => {
  assert.deepEqual(
    mergeUniqueById([{ id: 1, title: 'Cũ' }], [{ id: 1, title: 'Mới' }, { id: 2 }]),
    [{ id: 1, title: 'Mới' }, { id: 2 }],
  )
})

test('document pages keep unique ids and preserve a ready selection', () => {
  const current = [
    { id: 1, status: 'READY', rag_status: 'READY', chunk_count: 2 },
    { id: 2, status: 'READY', rag_status: 'PENDING', chunk_count: 2 },
  ]
  const merged = mergeUniqueById(current, [
    { ...current[1], title: 'Cập nhật' },
    { id: 3, status: 'READY', rag_status: 'READY', chunk_count: 1 },
  ])
  assert.deepEqual(merged.map((document) => document.id), [1, 2, 3])
  assert.equal(chooseChatDocumentId(merged, 1), 1)
  assert.equal(chooseChatDocumentId(merged, 2), 1)
})

test('RAG statuses remain visible and are classified distinctly', () => {
  const document = { id: 5, title: 'Tài liệu' }
  const statuses = [
    [{ document_id: 5, status: 'UPLOADED', rag_status: 'PENDING', chunk_count: 0 }, 'not_processed'],
    [{ document_id: 5, status: 'READY', rag_status: 'PENDING', chunk_count: 3 }, 'not_indexed'],
    [{ document_id: 5, status: 'READY', rag_status: 'INDEXING', chunk_count: 3 }, 'indexing'],
    [{ document_id: 5, status: 'READY', rag_status: 'FAILED', chunk_count: 3 }, 'index_failed'],
    [{ document_id: 5, status: 'READY', rag_status: 'READY', chunk_count: 3 }, 'ready'],
  ]
  for (const [status, expected] of statuses) {
    const classified = classifyDocumentForChat(document, status)
    assert.equal(classified.kind, expected)
    assert.ok(getChatDocumentStatusLabel(classified.document))
  }

  const unavailable = unavailableChatDocument(document)
  assert.equal(unavailable.chat_status, 'unavailable')
  assert.match(buildChatStatusMessages([unavailable]).join(' '), /lỗi mạng hoặc máy chủ/i)
  assert.equal(getRagStatusFailureKind(new ApiHttpError('hidden', {
    status: 404,
    statusText: 'Not Found',
    data: {},
  })), 'deleted')
})

test('rag-status mapping never exceeds four concurrent requests', async () => {
  let active = 0
  let maximum = 0
  const results = await mapWithConcurrency(
    Array.from({ length: 20 }, (_, index) => index),
    4,
    async (value) => {
      active += 1
      maximum = Math.max(maximum, active)
      await new Promise((resolve) => setTimeout(resolve, 1))
      active -= 1
      return value
    },
  )
  assert.equal(maximum, 4)
  assert.deepEqual(results, Array.from({ length: 20 }, (_, index) => index))
})

test('more than 50 messages merge in sequence order without losing citations', () => {
  const firstPage = Array.from({ length: 50 }, (_, index) => ({
    id: index + 1,
    sequence_no: index,
    citations: index % 2 ? [{ chunk_id: index }] : [],
  }))
  const secondPage = Array.from({ length: 26 }, (_, index) => ({
    id: index + 50,
    sequence_no: index + 49,
    citations: [{ chunk_id: index + 100 }],
  }))
  const merged = mergeChatMessages(firstPage, secondPage)
  assert.equal(merged.length, 75)
  assert.deepEqual(merged.map((message) => message.sequence_no),
    Array.from({ length: 75 }, (_, index) => index))
  assert.deepEqual(merged.at(-1).citations, [{ chunk_id: 125 }])
})

test('cursor page validation accepts latest and older history contracts', () => {
  const latest = validateChatMessageCursorPage({
    session_id: 8,
    items: Array.from({ length: 50 }, (_, index) => ({
      id: index + 71,
      sequence_no: index + 70,
      citations: [],
    })),
    total: 120,
    limit: 50,
    next_before_sequence_no: 70,
    has_more: true,
  }, 8, 50)
  const shortSession = validateChatMessageCursorPage({
    session_id: 9,
    items: [{ id: 1, sequence_no: 0, citations: [] }],
    total: 1,
    limit: 50,
    next_before_sequence_no: null,
    has_more: false,
  }, 9, 50)

  assert.deepEqual(latest.items.map((item) => item.sequence_no),
    Array.from({ length: 50 }, (_, index) => index + 70))
  assert.equal(shortSession.has_more, false)
  assert.throws(() => validateChatMessageCursorPage({
    ...shortSession,
    has_more: true,
  }, 9, 50), TypeError)
})

test('older cursor pages prepend without duplicate ids and retain citations', () => {
  const newest = Array.from({ length: 50 }, (_, index) => ({
    id: index + 71,
    sequence_no: index + 70,
    citations: [],
  }))
  const older = Array.from({ length: 50 }, (_, index) => ({
    id: index + 21,
    sequence_no: index + 20,
    citations: index === 0 ? [{ chunk_id: 101, citation_order: 0 }] : [],
  }))
  older.push({ id: 71, sequence_no: 70, citations: [] })

  const merged = mergeChatMessages(older, newest)

  assert.equal(merged.length, 100)
  assert.deepEqual(merged.map((message) => message.sequence_no),
    Array.from({ length: 100 }, (_, index) => index + 20))
  assert.deepEqual(merged[0].citations, [{ chunk_id: 101, citation_order: 0 }])
})

test('new messages append without discarding already loaded cursor history', () => {
  const history = Array.from({ length: 75 }, (_, index) => ({
    id: index + 1,
    sequence_no: index,
    citations: [],
  }))
  const updated = mergeChatMessages(history, [
    { id: 76, sequence_no: 75, citations: [] },
    { id: 77, sequence_no: 76, citations: [{ chunk_id: 202 }] },
  ])

  assert.equal(updated.length, 77)
  assert.deepEqual(updated.slice(0, 75), history)
  assert.deepEqual(updated.at(-1).citations, [{ chunk_id: 202 }])
})

test('prepending older messages preserves the visible scroll anchor', () => {
  assert.equal(getPrependedScrollTop({
    previousScrollTop: 240,
    previousScrollHeight: 1200,
    nextScrollHeight: 1850,
  }), 890)
  assert.equal(getPrependedScrollTop({
    previousScrollTop: 40,
    previousScrollHeight: 1000,
    nextScrollHeight: 1000,
  }), 40)
})

test('old document or session responses cannot replace current state', () => {
  assert.equal(isChatResponseCurrent({
    requestVersion: 3,
    currentRequestVersion: 3,
    documentId: 5,
    currentDocumentId: 5,
    sessionId: 8,
    currentSessionId: 8,
  }), true)
  assert.equal(isChatResponseCurrent({
    requestVersion: 2,
    currentRequestVersion: 3,
    sessionId: 8,
    currentSessionId: 8,
  }), false)
  assert.equal(isChatResponseCurrent({
    requestVersion: 3,
    currentRequestVersion: 3,
    sessionId: 7,
    currentSessionId: 8,
  }), false)
})

for (const [status, fragment] of [
  [401, 'đăng nhập'],
  [404, 'không tồn tại'],
  [409, 'chưa sẵn sàng'],
  [422, 'không hợp lệ'],
  [429, 'giới hạn'],
  [500, 'Hệ thống'],
  [503, 'tạm thời'],
  [504, 'thời gian chờ'],
]) {
  test(`HTTP ${status} uses a safe Vietnamese chat error`, () => {
    const secret = 'secret-key-internal-path'
    const error = new ApiHttpError(secret, {
      status,
      statusText: 'Failure',
      data: { detail: secret },
    })
    const message = getChatErrorMessage(error)
    assert.match(message, new RegExp(fragment, 'i'))
    assert.equal(message.includes(secret), false)
  })
}

test('HTTP 429 safely includes a numeric Retry-After value', () => {
  const error = new ApiHttpError('hidden', {
    status: 429,
    statusText: 'Too Many Requests',
    data: { detail: 'hidden' },
    retryAfter: '5',
  })
  assert.match(getChatErrorMessage(error), /5 giây/i)

  const unsafe = new ApiHttpError('hidden', {
    status: 429,
    statusText: 'Too Many Requests',
    data: { detail: 'hidden' },
    retryAfter: 'tomorrow',
  })
  assert.doesNotMatch(getChatErrorMessage(unsafe), /tomorrow/i)
})
