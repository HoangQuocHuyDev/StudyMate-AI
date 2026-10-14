import assert from 'node:assert/strict'
import test from 'node:test'

import { ApiHttpError } from '../src/services/apiClient.js'
import {
  canIndexDocument,
  getIndexingErrorMessage,
  getRagStatusPresentation,
} from '../src/components/documentRagUi.js'


test('RAG status labels are displayed in Vietnamese', () => {
  assert.equal(getRagStatusPresentation('PENDING').label, 'Chưa lập chỉ mục')
  assert.equal(getRagStatusPresentation('INDEXING').label, 'Đang lập chỉ mục')
  assert.equal(getRagStatusPresentation('READY').label, 'Sẵn sàng hỏi đáp')
  assert.equal(getRagStatusPresentation('FAILED').label, 'Lập chỉ mục thất bại')
})

for (const ragStatus of ['PENDING', 'FAILED']) {
  test(`${ragStatus} document with chunks can be indexed`, () => {
    assert.equal(canIndexDocument({
      status: 'READY',
      rag_status: ragStatus,
      chunk_count: 2,
      can_index: true,
    }), true)
  })
}

test('INDEXING and indexed READY documents cannot be indexed again', () => {
  for (const ragStatus of ['INDEXING', 'READY']) {
    assert.equal(canIndexDocument({
      status: 'READY',
      rag_status: ragStatus,
      chunk_count: 2,
      can_index: false,
    }), false)
  }
})

test('documents without chunks or processing readiness cannot be indexed', () => {
  assert.equal(canIndexDocument({
    status: 'READY',
    rag_status: 'PENDING',
    chunk_count: 0,
    can_index: false,
  }), false)
  assert.equal(canIndexDocument({
    status: 'UPLOADED',
    rag_status: 'PENDING',
    chunk_count: 2,
    can_index: false,
  }), false)
})

test('server can_index remains authoritative for the index action', () => {
  assert.equal(canIndexDocument({
    status: 'READY',
    rag_status: 'PENDING',
    chunk_count: 2,
    can_index: false,
  }), false)
})

for (const [status, expectedMessage] of [
  [401, 'Phiên đăng nhập'],
  [404, 'không có quyền'],
  [409, 'không cho phép'],
  [500, 'Hệ thống'],
  [503, 'tạm thời không khả dụng'],
]) {
  test(`HTTP ${status} indexing errors use a safe message`, () => {
    const secret = 'secret-key-and-internal-path'
    const error = new ApiHttpError(secret, {
      status,
      statusText: 'Failure',
      data: { detail: secret },
    })

    const message = getIndexingErrorMessage(error)

    assert.match(message, new RegExp(expectedMessage, 'i'))
    assert.equal(message.includes(secret), false)
  })
}
