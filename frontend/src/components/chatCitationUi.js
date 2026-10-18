import { createElement } from 'react'

function isPositiveInteger(value) {
  return Number.isInteger(value) && value > 0
}

export function validateCitationDetail(response, expected = {}) {
  if (
    !response
    || !isPositiveInteger(response.chunk_id)
    || !isPositiveInteger(response.document_id)
    || !Number.isInteger(response.chunk_index)
    || response.chunk_index < 0
    || typeof response.content !== 'string'
    || !response.content
    || (response.page_number !== null && !isPositiveInteger(response.page_number))
    || !Number.isInteger(response.citation_order)
    || response.citation_order < 0
    || (expected.chunkId !== undefined && response.chunk_id !== expected.chunkId)
    || (expected.documentId !== undefined && response.document_id !== expected.documentId)
  ) {
    throw new TypeError('Phản hồi nguồn trích dẫn không hợp lệ.')
  }
  return response
}

export function isCitationRequestCurrent({
  requestVersion,
  currentRequestVersion,
  conversationVersion,
  currentConversationVersion,
  documentId,
  currentDocumentId,
  sessionId,
  currentSessionId,
}) {
  return (
    requestVersion === currentRequestVersion
    && conversationVersion === currentConversationVersion
    && documentId === currentDocumentId
    && sessionId === currentSessionId
  )
}

export function CitationSourceButton({ citation, onSelect }) {
  const label = `Nguồn ${citation.citation_order + 1} — Đoạn ${citation.chunk_index + 1}`
  const page = citation.page_number ? ` · Trang ${citation.page_number}` : ''
  return createElement(
    'button',
    {
      type: 'button',
      onClick: () => onSelect(citation),
      'aria-label': `Xem ${label}${page}`,
    },
    `${label}${page}`,
  )
}

export function CitationDetailPanel({ state, onClose, panelRef, closeButtonRef }) {
  if (!state.open) return null

  const data = state.data
  const handleBackdropClick = (event) => {
    if (event.target === event.currentTarget) onClose()
  }

  return createElement(
    'div',
    {
      className: 'chat-citation-modal',
      role: 'presentation',
      onMouseDown: handleBackdropClick,
    },
    createElement(
      'section',
      {
        className: 'chat-citation-panel',
        ref: panelRef,
        tabIndex: -1,
        role: 'dialog',
        'aria-modal': 'true',
        'aria-labelledby': 'chat-citation-title',
      },
      createElement(
        'header',
        { className: 'chat-citation-panel__header' },
        createElement(
          'div',
          null,
          createElement('span', null, 'Nguồn tham khảo'),
          createElement('h2', { id: 'chat-citation-title' }, data
            ? `Nguồn ${data.citation_order + 1} — Đoạn ${data.chunk_index + 1}`
            : 'Nội dung nguồn trích dẫn'),
        ),
        createElement(
          'button',
          { ref: closeButtonRef, type: 'button', onClick: onClose, 'aria-label': 'Đóng nguồn trích dẫn' },
          '×',
        ),
      ),
      createElement(
        'div',
        { className: 'chat-citation-panel__body' },
        state.loading
          ? createElement(
            'div',
            { className: 'chat-citation-panel__state', role: 'status' },
            createElement('span', { className: 'chat-spinner' }),
            'Đang tải nội dung nguồn...',
          )
          : state.error
            ? createElement(
              'div',
              { className: 'chat-citation-panel__state chat-citation-panel__state--error', role: 'alert' },
              state.error,
            )
            : data
              ? createElement(
                'div',
                { className: 'chat-citation-detail' },
                createElement(
                  'div',
                  { className: 'chat-citation-detail__meta' },
                  createElement('span', null, `Đoạn ${data.chunk_index + 1}`),
                  data.page_number
                    ? createElement('span', null, `Trang ${data.page_number}`)
                    : null,
                ),
                createElement('p', null, data.content),
              )
              : null,
      ),
    ),
  )
}
