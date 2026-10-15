import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

import {
  ApiHttpError,
  ApiNetworkError,
} from '../src/services/apiClient.js'
import {
  formatHistoryDateTime,
  getHistoryErrorMessage,
  getHistoryPreview,
  getHistoryViewState,
  isHistoryResponseCurrent,
  mergeHistorySessions,
  validateHistoryResponse,
} from '../src/components/historyUi.js'

function historyItem(overrides = {}) {
  return {
    session_id: 45,
    document_id: 12,
    title: 'Ôn tập chương 2',
    document_title: 'Giáo trình trí tuệ nhân tạo',
    file_type: 'PDF',
    created_at: '2026-10-14T08:00:00Z',
    updated_at: '2026-10-14T09:15:00Z',
    last_message_preview: 'Nội dung xem trước...',
    ...overrides,
  }
}

test('history response maps the real backend contract including a null preview', () => {
  const response = {
    items: [historyItem({ last_message_preview: null })],
    total: 1,
    limit: 20,
    offset: 0,
  }

  assert.equal(validateHistoryResponse(response, 20, 0), response)
  assert.equal(getHistoryPreview(null), 'Chưa có nội dung xem trước.')
  assert.equal(getHistoryPreview('  '), 'Chưa có nội dung xem trước.')
  assert.equal(getHistoryPreview('Nội dung thật'), 'Nội dung thật')
})

test('history response rejects malformed sessions and pagination metadata', () => {
  const valid = {
    items: [historyItem()], total: 1, limit: 20, offset: 0,
  }
  const invalidResponses = [
    null,
    { ...valid, items: {} },
    { ...valid, total: -1 },
    { ...valid, limit: 10 },
    { ...valid, items: [historyItem({ session_id: 0 })] },
    { ...valid, items: [historyItem({ file_type: 'TXT' })] },
    { ...valid, items: [historyItem({ updated_at: 'invalid' })] },
    { ...valid, items: [historyItem({ last_message_preview: 42 })] },
  ]

  for (const response of invalidResponses) {
    assert.throws(() => validateHistoryResponse(response, 20, 0), TypeError)
  }
})

test('pagination appends in backend order and deduplicates shifted sessions', () => {
  const first = [
    historyItem({ session_id: 9, title: 'Mới nhất' }),
    historyItem({ session_id: 8, title: 'Phiên thứ hai' }),
  ]
  const second = [
    historyItem({ session_id: 8, title: 'Phiên thứ hai đã cập nhật' }),
    historyItem({ session_id: 7, title: 'Phiên cũ hơn' }),
  ]

  const merged = mergeHistorySessions(first, second)
  assert.deepEqual(merged.map(({ session_id }) => session_id), [9, 8, 7])
  assert.equal(merged[1].title, 'Phiên thứ hai đã cập nhật')
})

test('stale or aborted-equivalent request identities cannot replace current data', () => {
  assert.equal(isHistoryResponseCurrent(4, 4, 'AI\0week', 'AI\0week'), true)
  assert.equal(isHistoryResponseCurrent(3, 4, 'AI\0week', 'AI\0week'), false)
  assert.equal(isHistoryResponseCurrent(4, 4, 'AI\0week', 'PDF\0week'), false)
})

test('history UI distinguishes loading, empty, filtered empty, error, and ready', () => {
  assert.equal(getHistoryViewState({ itemCount: 0, loading: true, error: '', hasFilters: false }), 'loading')
  assert.equal(getHistoryViewState({ itemCount: 0, loading: false, error: 'Lỗi', hasFilters: false }), 'error')
  assert.equal(getHistoryViewState({ itemCount: 0, loading: false, error: '', hasFilters: false }), 'empty')
  assert.equal(getHistoryViewState({ itemCount: 0, loading: false, error: '', hasFilters: true }), 'filtered-empty')
  assert.equal(getHistoryViewState({ itemCount: 2, loading: true, error: '', hasFilters: false }), 'ready')
  assert.equal(getHistoryViewState({ itemCount: 2, loading: false, error: 'Lỗi làm mới', hasFilters: false }), 'ready')
})

test('history errors are mapped to safe Vietnamese messages', () => {
  const unauthorized = new ApiHttpError('raw secret', {
    status: 401, statusText: 'Unauthorized', data: { detail: 'raw secret' },
  })
  const invalid = new ApiHttpError('raw secret', {
    status: 422, statusText: 'Invalid', data: { detail: 'raw secret' },
  })
  const server = new ApiHttpError('raw secret', {
    status: 503, statusText: 'Failure', data: { detail: 'raw secret' },
  })

  assert.match(getHistoryErrorMessage(new ApiNetworkError('raw secret')), /kết nối/)
  assert.match(getHistoryErrorMessage(unauthorized), /đăng nhập/)
  assert.match(getHistoryErrorMessage(invalid), /không hợp lệ/)
  assert.match(getHistoryErrorMessage(server), /Hệ thống/)
  assert.equal(getHistoryErrorMessage(server).includes('raw secret'), false)
})

test('history date formatter returns readable Vietnamese-safe output', () => {
  assert.notEqual(formatHistoryDateTime('2026-10-14T09:15:00Z'), 'Không rõ thời gian')
  assert.equal(formatHistoryDateTime('invalid'), 'Không rõ thời gian')
})

test('History source has a real deep-link action without mock modal or delete action', async () => {
  const source = await readFile(
    new URL('../src/components/History.jsx', import.meta.url),
    'utf8',
  )
  assert.equal(source.includes('initialConversations'), false)
  assert.equal(source.includes('ConversationDialog'), false)
  assert.equal(source.includes('DeleteDialog'), false)
  assert.equal(source.includes('history-delete'), false)
  assert.equal(source.includes('getChatHistory'), true)
  assert.equal(source.includes('buildChatDeepLinkUrl'), true)
  assert.equal(source.includes('Mở cuộc hội thoại'), true)
})
