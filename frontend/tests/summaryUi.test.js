import assert from 'node:assert/strict'
import test from 'node:test'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'

import { ApiHttpError } from '../src/services/apiClient.js'
import { AssistantMarkdown } from '../src/components/chatMarkdown.js'
import {
  canGenerateSummary,
  buildDocumentStatusMessages,
  chooseSelectedDocumentId,
  classifyDocumentForSummary,
  copySummaryContent,
  DEFAULT_SUMMARY_TYPE,
  getSummaryErrorMessage,
  getDocumentStatusFailureKind,
  indexDocumentSummaries,
  isSummaryReadyDocument,
  isSummaryResponseCurrent,
  mergeDocumentsById,
  removeDocumentAndChooseSelection,
  validateGeneratedSummary,
} from '../src/components/summaryUi.js'

const readyDocument = {
  id: 1,
  status: 'READY',
  rag_status: 'PENDING',
  chunk_count: 3,
}

test('only READY documents with chunks are eligible without requiring RAG READY', () => {
  assert.equal(isSummaryReadyDocument(readyDocument), true)
  assert.equal(isSummaryReadyDocument({ ...readyDocument, rag_status: 'FAILED' }), true)
  assert.equal(isSummaryReadyDocument({ ...readyDocument, status: 'UPLOADED' }), false)
  assert.equal(isSummaryReadyDocument({ ...readyDocument, chunk_count: 0 }), false)
})

test('STANDARD is the default summary mode', () => {
  assert.equal(DEFAULT_SUMMARY_TYPE, 'STANDARD')
})

test('paginated document results are merged without duplicates and keep selection', () => {
  const firstPage = [{ id: 1, title: 'Một' }, { id: 2, title: 'Hai cũ' }]
  const secondPage = [{ id: 2, title: 'Hai mới' }, { id: 3, title: 'Ba' }]
  const merged = mergeDocumentsById(firstPage, secondPage)

  assert.deepEqual(merged.map((document) => document.id), [1, 2, 3])
  assert.equal(merged[1].title, 'Hai mới')
  assert.equal(chooseSelectedDocumentId(merged, 2), 2)
  assert.equal(chooseSelectedDocumentId(merged, 99), 1)
  assert.equal(chooseSelectedDocumentId([], 2), null)
})

test('document statuses distinguish unprocessed, missing chunks, unavailable, and deleted', () => {
  const document = { id: 4, title: 'Tài liệu' }
  assert.equal(classifyDocumentForSummary(document, {
    document_id: 4,
    status: 'UPLOADED',
    chunk_count: 0,
  }).kind, 'not_ready')
  assert.equal(classifyDocumentForSummary(document, {
    document_id: 4,
    status: 'READY',
    chunk_count: 0,
  }).kind, 'no_chunks')
  assert.equal(getDocumentStatusFailureKind(new ApiHttpError('hidden', {
    status: 404,
    statusText: 'Not Found',
    data: {},
  })), 'deleted')
  assert.equal(getDocumentStatusFailureKind(new Error('network details')), 'unavailable')

  const messages = buildDocumentStatusMessages({
    notReady: 1,
    noChunks: 2,
    unavailable: 3,
    deleted: 1,
  }).join(' ')
  assert.match(messages, /chưa xử lý xong/i)
  assert.match(messages, /chưa có nội dung để tóm tắt/i)
  assert.match(messages, /lỗi kết nối hoặc hệ thống/i)
  assert.match(messages, /không còn tồn tại/i)
})

test('a deleted selected document is removed and selection moves safely', () => {
  const documents = [{ id: 5 }, { id: 7 }, { id: 9 }]
  const selectedDeleted = removeDocumentAndChooseSelection(documents, 7, 7)
  assert.deepEqual(selectedDeleted.documents.map((document) => document.id), [5, 9])
  assert.equal(selectedDeleted.selectedDocumentId, 5)

  const unrelatedDeleted = removeDocumentAndChooseSelection(documents, 9, 7)
  assert.deepEqual(unrelatedDeleted.documents.map((document) => document.id), [5, 7])
  assert.equal(unrelatedDeleted.selectedDocumentId, 7)
})

test('saved summaries are indexed by type and marked as cached', () => {
  const summaries = indexDocumentSummaries({
    document_id: 1,
    items: [
      { summary_id: 1, document_id: 1, summary_type: 'SHORT', content: 'Ngắn' },
      { summary_id: 2, document_id: 1, summary_type: 'DETAILED', content: 'Chi tiết' },
    ],
  }, 1)

  assert.equal(summaries.SHORT.content, 'Ngắn')
  assert.equal(summaries.SHORT.from_cache, true)
  assert.equal(summaries.DETAILED.from_cache, true)
  assert.equal(summaries.STANDARD, undefined)
})

test('cached mode cannot generate again and active request prevents double submit', () => {
  assert.equal(canGenerateSummary({ document: readyDocument }), true)
  assert.equal(canGenerateSummary({ document: readyDocument, existingSummary: { content: 'Có sẵn' } }), false)
  assert.equal(canGenerateSummary({ document: readyDocument, requestActive: true }), false)
  assert.equal(canGenerateSummary({ document: readyDocument, isLoading: true }), false)
})

test('generated responses preserve cache hit and cache miss state', () => {
  const base = {
    summary_id: 3,
    document_id: 1,
    summary_type: 'STANDARD',
    content: 'Nội dung',
  }
  assert.equal(validateGeneratedSummary({ ...base, from_cache: true }, 1, 'STANDARD').from_cache, true)
  assert.equal(validateGeneratedSummary({ ...base, from_cache: false }, 1, 'STANDARD').from_cache, false)
})

test('responses from an old document or request version are rejected', () => {
  assert.equal(isSummaryResponseCurrent({ requestVersion: 2, currentRequestVersion: 2, documentId: 5, currentDocumentId: 5 }), true)
  assert.equal(isSummaryResponseCurrent({ requestVersion: 1, currentRequestVersion: 2, documentId: 5, currentDocumentId: 5 }), false)
  assert.equal(isSummaryResponseCurrent({ requestVersion: 2, currentRequestVersion: 2, documentId: 4, currentDocumentId: 5 }), false)
  assert.throws(() => indexDocumentSummaries({
    document_id: 2,
    items: [{ summary_id: 1, document_id: 2, summary_type: 'SHORT', content: 'Sai tài liệu' }],
  }, 1), TypeError)
})

for (const [status, expected] of [
  [401, 'Phiên đăng nhập'],
  [404, 'không tồn tại'],
  [409, 'chưa sẵn sàng'],
  [413, 'vượt quá giới hạn'],
  [422, 'không hợp lệ'],
  [429, 'đang bận'],
  [500, 'Hệ thống'],
  [503, 'tạm thời không khả dụng'],
  [504, 'vượt quá thời gian'],
]) {
  test(`HTTP ${status} is mapped to a safe Vietnamese message`, () => {
    const error = new ApiHttpError('SDK_SECRET_STACK', {
      status,
      statusText: 'Failure',
      data: { detail: 'SDK_SECRET_STACK' },
    })
    const message = getSummaryErrorMessage(error)
    assert.match(message, new RegExp(expected, 'i'))
    assert.doesNotMatch(message, /SDK_SECRET_STACK/)
  })
}

test('HTTP 409 distinguishes a concurrent summary from an unready document', () => {
  const concurrent = new ApiHttpError('hidden', {
    status: 409,
    statusText: 'Conflict',
    data: { detail: 'Bản tóm tắt này đang được tạo bởi một yêu cầu khác.' },
  })
  const unready = new ApiHttpError('hidden', {
    status: 409,
    statusText: 'Conflict',
    data: { detail: 'Tài liệu chưa sẵn sàng để tóm tắt hoặc đang được cập nhật.' },
  })
  assert.match(getSummaryErrorMessage(concurrent), /yêu cầu khác/i)
  assert.match(getSummaryErrorMessage(unready), /chưa sẵn sàng/i)
})

test('HTTP 429 uses a safe Retry-After value when available', () => {
  const error = new ApiHttpError('hidden', {
    status: 429,
    statusText: 'Too Many Requests',
    data: { detail: 'hidden' },
    retryAfter: '5',
  })
  assert.match(getSummaryErrorMessage(error), /5 giây/i)

  const unsafe = new ApiHttpError('hidden', {
    status: 429,
    statusText: 'Too Many Requests',
    data: { detail: 'hidden' },
    retryAfter: 'tomorrow',
  })
  assert.doesNotMatch(getSummaryErrorMessage(unsafe), /tomorrow/i)
})

test('summary Markdown remains safe for raw HTML and unsafe links', () => {
  const html = renderToStaticMarkup(createElement(AssistantMarkdown, {
    content: '# Tiêu đề\n\n**đậm**\n\n- mục\n\n```js\nconst ok = true\n```\n\n<script>alert(1)</script> [xấu](javascript:alert(2))',
  }))
  assert.match(html, /<h1>Tiêu đề<\/h1>/)
  assert.match(html, /<strong>đậm<\/strong>/)
  assert.match(html, /<ul>/)
  assert.match(html, /<pre><code class="language-js">/)
  assert.doesNotMatch(html, /<script|javascript:|href=/i)
})

test('copy helper writes the exact backend summary to the clipboard', async () => {
  let copied = null
  await copySummaryContent('**Nội dung gốc**', {
    async writeText(value) { copied = value },
  })
  assert.equal(copied, '**Nội dung gốc**')
})
