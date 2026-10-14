import assert from 'node:assert/strict'
import test from 'node:test'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'

import {
  CitationDetailPanel,
  CitationSourceButton,
  isCitationRequestCurrent,
  validateCitationDetail,
} from '../src/components/chatCitationUi.js'

const detail = {
  chunk_id: 11,
  document_id: 3,
  chunk_index: 2,
  content: '<img src=x onerror=alert(1)> Nội dung nguyên văn',
  page_number: 4,
  citation_order: 0,
}

test('citation source button invokes selection with backend metadata', () => {
  let selected
  const citation = { chunk_id: 11, chunk_index: 2, page_number: 4, citation_order: 0 }
  const element = CitationSourceButton({ citation, onSelect: (value) => { selected = value } })

  element.props.onClick()

  assert.equal(selected, citation)
  assert.match(element.props.children, /Nguồn 1 — Đoạn 3 · Trang 4/)
})

test('citation panel renders PostgreSQL content as escaped plain text', () => {
  const html = renderToStaticMarkup(createElement(CitationDetailPanel, {
    state: { open: true, loading: false, error: null, data: detail },
    onClose() {},
  }))

  assert.match(html, /Nguồn 1 — Đoạn 3/)
  assert.match(html, /Trang 4/)
  assert.match(html, /&lt;img src=x onerror=alert\(1\)&gt;/)
  assert.doesNotMatch(html, /<img|dangerouslySetInnerHTML/i)
})

test('citation panel exposes loading, safe error, and close states', () => {
  const loading = renderToStaticMarkup(createElement(CitationDetailPanel, {
    state: { open: true, loading: true, error: null, data: null },
    onClose() {},
  }))
  const failed = renderToStaticMarkup(createElement(CitationDetailPanel, {
    state: { open: true, loading: false, error: 'Không thể tải nguồn.', data: null },
    onClose() {},
  }))
  let closed = false
  const tree = CitationDetailPanel({
    state: { open: true, loading: false, error: null, data: detail },
    onClose: () => { closed = true },
  })
  const closeButton = tree.props.children.props.children[0].props.children[1]
  closeButton.props.onClick()

  assert.match(loading, /Đang tải nội dung nguồn/)
  assert.match(failed, /role="alert"/)
  assert.equal(closed, true)
})

test('stale citation response is rejected after session or document changes', () => {
  const base = {
    requestVersion: 2,
    currentRequestVersion: 2,
    conversationVersion: 5,
    currentConversationVersion: 5,
    documentId: 3,
    currentDocumentId: 3,
    sessionId: 7,
    currentSessionId: 7,
  }
  assert.equal(isCitationRequestCurrent(base), true)
  assert.equal(isCitationRequestCurrent({ ...base, currentSessionId: 8 }), false)
  assert.equal(isCitationRequestCurrent({ ...base, currentDocumentId: 4 }), false)
  assert.equal(isCitationRequestCurrent({ ...base, currentRequestVersion: 3 }), false)
})

test('citation detail response must match the requested chunk and document', () => {
  assert.equal(validateCitationDetail(detail, { chunkId: 11, documentId: 3 }), detail)
  assert.throws(
    () => validateCitationDetail({ ...detail, chunk_id: 12 }, { chunkId: 11, documentId: 3 }),
    TypeError,
  )
  assert.throws(() => validateCitationDetail({ ...detail, content: '' }), TypeError)
})
