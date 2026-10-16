import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

import { ApiHttpError, ApiNetworkError } from '../src/services/apiClient.js'
import {
  ADMIN_DOCUMENTS_PAGE_SIZE,
  adminDocumentsReducer,
  formatAdminDocumentDate,
  formatAdminDocumentSize,
  getAdminDocumentsAdjustedOffset,
  getAdminDocumentsErrorMessage,
  getAdminDocumentsPageInfo,
  getDocumentStatusPresentation,
  getRagStatusPresentation,
  initialAdminDocumentsState,
  validateAdminDocumentDetailResponse,
  validateAdminDocumentListResponse,
} from '../src/components/admin/adminDocumentsUi.js'


const documentItem = {
  id: 12,
  title: 'Giáo trình trí tuệ nhân tạo',
  original_filename: 'giao-trinh.pdf',
  file_type: 'PDF',
  file_size: 1536,
  status: 'READY',
  rag_status: 'READY',
  owner: { id: 4, username: 'student01', full_name: 'Nguyễn Văn A' },
  created_at: '2026-10-15T08:00:00Z',
  processed_at: '2026-10-15T08:01:00Z',
  indexed_at: '2026-10-15T08:02:00Z',
}
const detail = {
  ...documentItem,
  mime_type: 'application/pdf',
  page_count: 12,
  character_count: 18653,
  updated_at: '2026-10-15T08:02:00Z',
}
const page = { items: [documentItem], total: 41, limit: 20, offset: 20 }


test('Admin Documents validates and maps list, owner, and pagination', () => {
  const result = validateAdminDocumentListResponse(page)
  assert.deepEqual(result.items, [documentItem])
  assert.equal(ADMIN_DOCUMENTS_PAGE_SIZE, 20)
  assert.deepEqual(getAdminDocumentsPageInfo(result), {
    currentPage: 2,
    pageCount: 3,
    firstItem: 21,
    lastItem: 40,
    canGoBack: true,
    canGoForward: true,
  })
})

test('Admin Documents validates enum, date, owner, duplicate and pagination fields', () => {
  assert.throws(() => validateAdminDocumentListResponse({}), TypeError)
  assert.throws(() => validateAdminDocumentListResponse({ ...page, total: -1 }), TypeError)
  assert.throws(() => validateAdminDocumentListResponse({ ...page, items: [documentItem, documentItem] }), TypeError)
  assert.throws(() => validateAdminDocumentListResponse({ ...page, items: [{ ...documentItem, file_type: 'TXT' }] }), TypeError)
  assert.throws(() => validateAdminDocumentListResponse({ ...page, items: [{ ...documentItem, status: 'DELETED' }] }), TypeError)
  assert.throws(() => validateAdminDocumentListResponse({ ...page, items: [{ ...documentItem, owner: null }] }), TypeError)
  assert.throws(() => validateAdminDocumentListResponse({ ...page, items: [{ ...documentItem, created_at: 'invalid' }] }), TypeError)
})

test('detail response exposes expected metadata and handles nullable values', () => {
  assert.deepEqual(validateAdminDocumentDetailResponse(detail), detail)
  assert.doesNotThrow(() => validateAdminDocumentDetailResponse({
    ...detail,
    page_count: null,
    character_count: 0,
    processed_at: null,
    indexed_at: null,
  }))
  assert.throws(() => validateAdminDocumentDetailResponse({ ...detail, page_count: 0 }), TypeError)
  assert.throws(() => validateAdminDocumentDetailResponse({ ...detail, character_count: -1 }), TypeError)
})

test('sensitive document and owner fields are rejected instead of displayed', () => {
  for (const field of ['storage_key', 'file_path', 'content', 'chunks', 'summaries', 'embeddings']) {
    assert.throws(() => validateAdminDocumentDetailResponse({ ...detail, [field]: 'private' }), TypeError)
  }
  assert.throws(() => validateAdminDocumentDetailResponse({
    ...detail,
    owner: { ...detail.owner, password_hash: 'private' },
  }), TypeError)
  assert.equal(Object.hasOwn(validateAdminDocumentDetailResponse(detail), 'storage_key'), false)
})

test('formatters and Vietnamese status badges are stable', () => {
  assert.match(formatAdminDocumentSize(1536), /1,5 KB|1\.5 KB/)
  assert.equal(formatAdminDocumentDate(null), 'Chưa có')
  assert.match(formatAdminDocumentDate(documentItem.created_at), /15\/10\/2026/)
  assert.deepEqual(getDocumentStatusPresentation('PROCESSING'), { label: 'Đang xử lý', tone: 'processing' })
  assert.deepEqual(getRagStatusPresentation('PENDING'), { label: 'Chưa lập chỉ mục', tone: 'pending' })
})

test('list reducer covers loading, empty/error retry data, and stale responses', () => {
  let state = adminDocumentsReducer(initialAdminDocumentsState, { type: 'request-started', requestId: 2 })
  state = adminDocumentsReducer(state, { type: 'request-succeeded', requestId: 1, data: page })
  assert.equal(state.data, null)
  state = adminDocumentsReducer(state, { type: 'request-succeeded', requestId: 2, data: page })
  state = adminDocumentsReducer(state, { type: 'request-started', requestId: 3 })
  state = adminDocumentsReducer(state, { type: 'request-failed', requestId: 3, error: 'Mất kết nối' })
  assert.equal(state.data, page)
  assert.equal(state.status, 'error')
  assert.deepEqual(getAdminDocumentsPageInfo({ total: 0, offset: 0, limit: 20 }), {
    currentPage: 1,
    pageCount: 1,
    firstItem: 0,
    lastItem: 0,
    canGoBack: false,
    canGoForward: false,
  })
})

test('Admin Documents accepts an empty page beyond total and adjusts after data shrinks', () => {
  const overflow = validateAdminDocumentListResponse({
    items: [], total: 25, limit: 20, offset: 40,
  })
  assert.deepEqual(overflow.items, [])
  assert.equal(getAdminDocumentsAdjustedOffset(overflow), 20)

  const filtered = validateAdminDocumentListResponse({
    items: [], total: 9, limit: 20, offset: 60,
  })
  assert.equal(getAdminDocumentsAdjustedOffset(filtered), 0)
})

test('Admin Documents normalizes total zero to offset zero without repeated adjustment', () => {
  const empty = validateAdminDocumentListResponse({
    items: [], total: 0, limit: 20, offset: 20,
  })
  assert.equal(getAdminDocumentsAdjustedOffset(empty), 0)
  assert.equal(getAdminDocumentsAdjustedOffset({ ...empty, offset: 0 }), 0)
})

test('Admin Documents ignores an older response after newer filter results', () => {
  const newestPage = { ...page, items: [], total: 0, offset: 0 }
  let state = adminDocumentsReducer(initialAdminDocumentsState, {
    type: 'request-started', requestId: 7,
  })
  state = adminDocumentsReducer(state, {
    type: 'request-started', requestId: 8,
  })
  state = adminDocumentsReducer(state, {
    type: 'request-succeeded', requestId: 8, data: newestPage,
  })
  state = adminDocumentsReducer(state, {
    type: 'request-succeeded', requestId: 7, data: page,
  })
  assert.equal(state.data, newestPage)
})

for (const [status, pattern] of [
  [401, /hết hạn/],
  [403, /không có quyền/],
  [404, /không còn tồn tại/],
  [422, /không hợp lệ/],
  [500, /Máy chủ/],
]) {
  test(`HTTP ${status} has a safe Vietnamese Admin Documents message`, () => {
    const error = new ApiHttpError('raw private path', {
      status,
      statusText: 'Failure',
      data: { detail: 'raw private path' },
    })
    const message = getAdminDocumentsErrorMessage(error, 'detail')
    assert.match(message, pattern)
    assert.equal(message.includes('raw private path'), false)
  })
}

test('network error is safe and retryable', () => {
  assert.match(getAdminDocumentsErrorMessage(new ApiNetworkError('raw')), /kết nối/)
})

test('AdminDocuments source has debounce, modal, retry, stale guards and no destructive action', async () => {
  const source = await readFile(
    new URL('../src/components/admin/AdminDocuments.jsx', import.meta.url),
    'utf8',
  )
  assert.match(source, /maxLength=\{255\}/)
  assert.match(source, /\}, 350\)/)
  assert.match(source, /<AdminModal/)
  assert.match(source, /Chi tiết tài liệu/)
  assert.match(source, /Thử lại/)
  assert.match(source, /detailRequestRef\.current\.id !== requestId/)
  assert.equal(source.includes('Chưa triển khai'), false)
  assert.equal(source.includes('deleteDocument'), false)
  assert.equal(source.includes('apiClient.delete'), false)
  assert.equal(source.includes('Tải xuống'), false)
})
