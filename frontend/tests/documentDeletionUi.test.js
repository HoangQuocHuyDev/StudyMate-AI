import assert from 'node:assert/strict'
import test from 'node:test'

import {
  ApiConfigurationError,
  ApiHttpError,
  ApiNetworkError,
} from '../src/services/apiClient.js'
import {
  createDocumentDeletionGuard,
  decrementDocumentPagination,
  documentDeletionUiReducer,
  getDocumentDeletionErrorMessage,
  initialDocumentDeletionUiState,
  removeDocumentFromPage,
} from '../src/components/documentDeletionUi.js'


for (const [status, expected] of [
  [401, 'đăng nhập'],
  [404, 'không còn tồn tại'],
  [409, 'yêu cầu xóa khác'],
  [500, 'có thể đang'],
  [503, 'có thể đang'],
]) {
  test(`HTTP ${status} deletion error is mapped to a safe Vietnamese message`, () => {
    const secret = 'private-storage-key-and-traceback'
    const message = getDocumentDeletionErrorMessage(new ApiHttpError(secret, {
      status,
      statusText: 'Failure',
      data: { detail: secret },
    }))
    assert.match(message, new RegExp(expected, 'i'))
    assert.equal(message.includes(secret), false)
  })
}

test('network uncertainty does not claim the document was not deleted', () => {
  const message = getDocumentDeletionErrorMessage(new ApiNetworkError('secret'))
  assert.match(message, /có thể đang/i)
  assert.doesNotMatch(message, /chưa bị xóa/i)
  assert.equal(
    getDocumentDeletionErrorMessage(new ApiConfigurationError('secret')),
    'Frontend chưa được cấu hình địa chỉ Backend hợp lệ.',
  )
})

test('successful or tombstoned deletion removes only the selected card and updates totals', () => {
  const documents = [{ id: 1 }, { id: 2 }, { id: 3 }]
  assert.deepEqual(removeDocumentFromPage(documents, 2), [{ id: 1 }, { id: 3 }])
  assert.deepEqual(decrementDocumentPagination({
    page: 2,
    pageSize: 10,
    total: 11,
    totalPages: 2,
  }), {
    page: 2,
    pageSize: 10,
    total: 10,
    totalPages: 1,
  })
})

test('deletion guard prevents duplicate requests for the same document', () => {
  const guard = createDocumentDeletionGuard()
  assert.equal(guard.tryStart(5), true)
  assert.equal(guard.tryStart(5), false)
  assert.equal(guard.isActive(5), true)
  guard.finish(5)
  assert.equal(guard.isActive(5), false)
  assert.equal(guard.tryStart(5), true)
  guard.clear()
  assert.equal(guard.isActive(5), false)
})

test('confirmation state opens, cancels, and enters a locked loading state', () => {
  const document = { id: 5, title: 'Bài giảng PDF' }
  const opened = documentDeletionUiReducer(initialDocumentDeletionUiState, {
    type: 'open',
    document,
  })
  assert.deepEqual(opened, { document, state: 'idle', message: '' })
  assert.equal(
    documentDeletionUiReducer(opened, { type: 'close' }),
    initialDocumentDeletionUiState,
  )

  const deleting = documentDeletionUiReducer(opened, {
    type: 'start',
    message: 'Đang xóa...',
  })
  assert.deepEqual(deleting, { document, state: 'deleting', message: 'Đang xóa...' })
  assert.equal(documentDeletionUiReducer(deleting, { type: 'close' }), deleting)
})

test('deletion state preserves a safe error for retry and clears after success', () => {
  const document = { id: 5, title: 'Bài giảng PDF' }
  const opened = documentDeletionUiReducer(initialDocumentDeletionUiState, {
    type: 'open',
    document,
  })
  const failed = documentDeletionUiReducer(opened, {
    type: 'error',
    message: 'Không thể xác nhận.',
  })
  assert.deepEqual(failed, {
    document,
    state: 'error',
    message: 'Không thể xác nhận.',
  })
  assert.equal(
    documentDeletionUiReducer(failed, { type: 'complete' }),
    initialDocumentDeletionUiState,
  )
})
