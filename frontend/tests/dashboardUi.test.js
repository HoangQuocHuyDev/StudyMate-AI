import assert from 'node:assert/strict'
import test from 'node:test'

import { ApiHttpError, ApiNetworkError } from '../src/services/apiClient.js'
import {
  DASHBOARD_DOCUMENT_LIMIT,
  DASHBOARD_FEATURES,
  DASHBOARD_STATISTICS,
  dashboardDocumentsReducer,
  dashboardOverviewReducer,
  formatDashboardDocumentDate,
  getDashboardDocumentsErrorMessage,
  getDashboardDocumentStatus,
  getDashboardOverviewErrorMessage,
  getDashboardStatisticCards,
  initialDashboardDocumentsState,
  initialDashboardOverviewState,
  isDashboardOverviewEmpty,
  validateDashboardDocumentsResponse,
  validateDashboardOverviewResponse,
} from '../src/components/dashboardUi.js'

function document(id, overrides = {}) {
  return {
    id,
    title: `Tài liệu ${id}`,
    file_type: id % 2 ? 'PDF' : 'DOCX',
    created_at: '2026-10-14T08:30:00Z',
    status: 'READY',
    ...overrides,
  }
}

test('three dashboard actions use the existing internal routes', () => {
  assert.deepEqual(
    DASHBOARD_FEATURES.map(({ path }) => path),
    ['/documents', '/summarize', '/chat'],
  )
  assert.deepEqual(
    DASHBOARD_FEATURES.map(({ link }) => link),
    ['Thêm tài liệu', 'Bắt đầu tóm tắt', 'Đặt câu hỏi'],
  )
})

test('dashboard maps all four backend counts without changing their meaning', () => {
  const response = {
    document_count: 12,
    ready_document_count: 7,
    summary_count: 18,
    chat_session_count: 9,
  }
  const cards = getDashboardStatisticCards(response)

  assert.deepEqual(cards.map(({ field, value }) => ({ field, value })), [
    { field: 'document_count', value: 12 },
    { field: 'ready_document_count', value: 7 },
    { field: 'summary_count', value: 18 },
    { field: 'chat_session_count', value: 9 },
  ])
  assert.match(cards[2].description, /bản tóm tắt/i)
  assert.match(cards[3].description, /phiên trò chuyện/i)
  assert.equal(cards.length, DASHBOARD_STATISTICS.length)
})

test('all-zero overview is an explicit valid empty state', () => {
  const empty = {
    document_count: 0,
    ready_document_count: 0,
    summary_count: 0,
    chat_session_count: 0,
  }
  assert.equal(isDashboardOverviewEmpty(empty), true)
  assert.equal(isDashboardOverviewEmpty({ ...empty, summary_count: 1 }), false)
  assert.deepEqual(validateDashboardOverviewResponse(empty), empty)
})

test('missing, negative, or non-integer counts are rejected instead of shown as zero', () => {
  const valid = {
    document_count: 1,
    ready_document_count: 1,
    summary_count: 1,
    chat_session_count: 1,
  }
  assert.throws(
    () => validateDashboardOverviewResponse({ ...valid, summary_count: -1 }),
    TypeError,
  )
  assert.throws(
    () => validateDashboardOverviewResponse({ ...valid, chat_session_count: 1.5 }),
    TypeError,
  )
  const { document_count: omitted, ...missing } = valid
  assert.equal(omitted, 1)
  assert.throws(() => validateDashboardOverviewResponse(missing), TypeError)
})

test('overview loading, error, retry, and stale responses preserve trusted data', () => {
  const oldData = {
    document_count: 3,
    ready_document_count: 2,
    summary_count: 1,
    chat_session_count: 4,
  }
  let state = { ...initialDashboardOverviewState, data: oldData, status: 'success' }
  state = dashboardOverviewReducer(state, { type: 'request-started', requestId: 1 })
  state = dashboardOverviewReducer(state, {
    type: 'request-failed',
    requestId: 1,
    error: 'Không thể tải.',
  })
  assert.equal(state.data, oldData)
  assert.equal(state.status, 'error')

  state = dashboardOverviewReducer(state, { type: 'request-started', requestId: 2 })
  const newData = { ...oldData, document_count: 5 }
  state = dashboardOverviewReducer(state, {
    type: 'request-succeeded',
    requestId: 2,
    data: newData,
  })
  const staleState = dashboardOverviewReducer(state, {
    type: 'request-succeeded',
    requestId: 1,
    data: { ...oldData, document_count: 99 },
  })
  assert.equal(staleState, state)
  assert.equal(staleState.data.document_count, 5)
})

test('overview API errors use safe Vietnamese messages', () => {
  const unauthorized = new ApiHttpError('RAW_SECRET', {
    status: 401,
    statusText: 'Unauthorized',
    data: { detail: 'RAW_SECRET' },
  })
  assert.match(getDashboardOverviewErrorMessage(unauthorized), /Phiên đăng nhập/i)
  assert.match(
    getDashboardOverviewErrorMessage(new ApiNetworkError('RAW_NETWORK')),
    /kết nối/i,
  )
  assert.doesNotMatch(getDashboardOverviewErrorMessage(unauthorized), /RAW_SECRET/)
})

test('dashboard response exposes the real total and at most five recent documents', () => {
  const result = validateDashboardDocumentsResponse({
    items: Array.from({ length: 7 }, (_, index) => document(index + 1)),
    total: 23,
  })

  assert.equal(result.total, 23)
  assert.equal(result.items.length, DASHBOARD_DOCUMENT_LIMIT)
  assert.deepEqual(result.items.map(({ id }) => id), [1, 2, 3, 4, 5])
})

test('dashboard response preserves a valid empty state', () => {
  assert.deepEqual(
    validateDashboardDocumentsResponse({ items: [], total: 0 }),
    { items: [], total: 0 },
  )
})

test('dashboard rejects malformed document list data', () => {
  assert.throws(
    () => validateDashboardDocumentsResponse({ items: [document(1, { file_type: 'TXT' })], total: 1 }),
    TypeError,
  )
  assert.throws(
    () => validateDashboardDocumentsResponse({ items: [], total: -1 }),
    TypeError,
  )
})

test('loading, failure, retry, and success preserve previously displayed data', () => {
  const oldData = { items: [document(1)], total: 1 }
  let state = { ...initialDashboardDocumentsState, data: oldData, status: 'success' }
  state = dashboardDocumentsReducer(state, { type: 'request-started', requestId: 1 })
  assert.equal(state.status, 'loading')
  assert.equal(state.data, oldData)

  state = dashboardDocumentsReducer(state, {
    type: 'request-failed',
    requestId: 1,
    error: 'Không thể tải.',
  })
  assert.equal(state.status, 'error')
  assert.equal(state.data, oldData)

  state = dashboardDocumentsReducer(state, { type: 'request-started', requestId: 2 })
  assert.equal(state.error, '')
  assert.equal(state.data, oldData)

  const newData = { items: [document(2)], total: 2 }
  state = dashboardDocumentsReducer(state, {
    type: 'request-succeeded',
    requestId: 2,
    data: newData,
  })
  assert.equal(state.status, 'success')
  assert.equal(state.data, newData)
})

test('an old response cannot overwrite the newest dashboard request', () => {
  let state = dashboardDocumentsReducer(initialDashboardDocumentsState, {
    type: 'request-started',
    requestId: 1,
  })
  state = dashboardDocumentsReducer(state, { type: 'request-started', requestId: 2 })
  const newestData = { items: [document(2)], total: 1 }
  state = dashboardDocumentsReducer(state, {
    type: 'request-succeeded',
    requestId: 2,
    data: newestData,
  })
  const afterOldResponse = dashboardDocumentsReducer(state, {
    type: 'request-succeeded',
    requestId: 1,
    data: { items: [document(1)], total: 99 },
  })

  assert.equal(afterOldResponse, state)
  assert.equal(afterOldResponse.data, newestData)
})

test('dashboard errors are safe and keep the existing 401 behavior', () => {
  const unauthorized = new ApiHttpError('SECRET_RAW_RESPONSE', {
    status: 401,
    statusText: 'Unauthorized',
    data: { detail: 'SECRET_RAW_RESPONSE' },
  })
  const network = new ApiNetworkError('SECRET_NETWORK_DETAIL')

  assert.match(getDashboardDocumentsErrorMessage(unauthorized), /Phiên đăng nhập/i)
  assert.match(getDashboardDocumentsErrorMessage(network), /kết nối/i)
  assert.doesNotMatch(getDashboardDocumentsErrorMessage(unauthorized), /SECRET/)
})

test('document date and processing states have Vietnamese presentations', () => {
  assert.notEqual(formatDashboardDocumentDate('2026-10-14T08:30:00Z'), 'Không rõ thời gian')
  assert.equal(formatDashboardDocumentDate('invalid'), 'Không rõ thời gian')
  assert.equal(getDashboardDocumentStatus('UPLOADED').label, 'Chưa xử lý')
  assert.equal(getDashboardDocumentStatus('PROCESSING').label, 'Đang xử lý')
  assert.equal(getDashboardDocumentStatus('READY').label, 'Đã xử lý')
  assert.equal(getDashboardDocumentStatus('FAILED').label, 'Xử lý thất bại')
})
