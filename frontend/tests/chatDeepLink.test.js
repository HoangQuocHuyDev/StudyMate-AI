import assert from 'node:assert/strict'
import test from 'node:test'

import {
  buildChatDeepLinkUrl,
  ChatDeepLinkError,
  findSessionAcrossPages,
  isChatDeepLinkRequestCurrent,
  mergeDeepLinkedDocument,
  parseChatDeepLink,
} from '../src/components/chatDeepLink.js'

test('History builds a minimal encoded Chat deep-link without sensitive data', () => {
  const url = buildChatDeepLinkUrl(12, 45)
  assert.equal(url, '/chat?document_id=12&session_id=45')
  assert.equal(url.includes('token'), false)
  assert.equal(url.includes('content'), false)
})

test('Chat parses valid document and session ids after F5 or return_to restoration', () => {
  assert.deepEqual(
    parseChatDeepLink('?document_id=12&session_id=45'),
    { kind: 'valid', documentId: 12, sessionId: 45 },
  )
  assert.deepEqual(
    parseChatDeepLink('?document_id=12'),
    { kind: 'valid', documentId: 12, sessionId: null },
  )
  assert.deepEqual(
    parseChatDeepLink(''),
    { kind: 'none', documentId: null, sessionId: null },
  )
})

test('Chat rejects ambiguous, unsafe, incomplete, and invalid deep-link ids', () => {
  const invalidQueries = [
    '?session_id=4',
    '?document_id=0&session_id=4',
    '?document_id=-1&session_id=4',
    '?document_id=1.5&session_id=4',
    '?document_id=01&session_id=4',
    '?document_id=true&session_id=4',
    '?document_id=4&session_id=0',
    '?document_id=4&session_id=5&session_id=6',
    '?document_id=4&document_id=5&session_id=6',
    `?document_id=${Number.MAX_SAFE_INTEGER + 1}&session_id=4`,
  ]
  for (const search of invalidQueries) {
    assert.equal(parseChatDeepLink(search).kind, 'invalid')
  }
  assert.throws(() => buildChatDeepLinkUrl(0, 1), TypeError)
  assert.throws(() => buildChatDeepLinkUrl(1, -1), TypeError)
})

test('a document outside the first page is retained exactly once', () => {
  const firstPage = [{ id: 1, title: 'Trang đầu' }, { id: 2, title: 'Khác' }]
  const target = { id: 45, title: 'Tài liệu đích' }
  assert.deepEqual(
    mergeDeepLinkedDocument(firstPage, target).map(({ id }) => id),
    [1, 2, 45],
  )
  assert.equal(
    mergeDeepLinkedDocument([...firstPage, { id: 45, title: 'Cũ' }], target)
      .filter(({ id }) => id === 45).length,
    1,
  )
})

test('a session outside the first page is found without creating a new session', async () => {
  const calls = []
  const pages = new Map([
    [0, {
      items: Array.from({ length: 20 }, (_, index) => ({ id: index + 1 })),
      total: 45,
      limit: 20,
      offset: 0,
    }],
    [20, {
      items: Array.from({ length: 20 }, (_, index) => ({ id: index + 21 })),
      total: 45,
      limit: 20,
      offset: 20,
    }],
    [40, {
      items: Array.from({ length: 5 }, (_, index) => ({ id: index + 41 })),
      total: 45,
      limit: 20,
      offset: 40,
    }],
  ])

  const result = await findSessionAcrossPages({
    targetSessionId: 43,
    pageSize: 20,
    fetchPage: async (offset) => {
      calls.push(offset)
      return pages.get(offset)
    },
  })

  assert.equal(result.target.id, 43)
  assert.equal(result.items.length, 45)
  assert.equal(result.fetchedCount, 45)
  assert.deepEqual(calls, [0, 20, 40])
})

test('session pagination deduplicates shifted items and rejects a mismatched session', async () => {
  const pages = new Map([
    [0, {
      items: [{ id: 5 }, { id: 4 }], total: 4, limit: 2, offset: 0,
    }],
    [2, {
      items: [{ id: 4 }, { id: 3 }], total: 4, limit: 2, offset: 2,
    }],
  ])

  await assert.rejects(
    findSessionAcrossPages({
      targetSessionId: 99,
      pageSize: 2,
      fetchPage: async (offset) => pages.get(offset),
    }),
    (error) => error instanceof ChatDeepLinkError
      && error.code === 'session_not_found',
  )
})

test('query-only Back/Forward values resolve independently', () => {
  const first = parseChatDeepLink('?document_id=3&session_id=7')
  const second = parseChatDeepLink('?document_id=8&session_id=12')
  assert.notDeepEqual(first, second)
  assert.equal(first.sessionId, 7)
  assert.equal(second.sessionId, 12)
})

test('aborted and stale deep-link responses cannot replace the active selection', () => {
  assert.equal(isChatDeepLinkRequestCurrent({
    requestVersion: 4,
    currentRequestVersion: 4,
    aborted: false,
  }), true)
  assert.equal(isChatDeepLinkRequestCurrent({
    requestVersion: 3,
    currentRequestVersion: 4,
    aborted: false,
  }), false)
  assert.equal(isChatDeepLinkRequestCurrent({
    requestVersion: 4,
    currentRequestVersion: 4,
    aborted: true,
  }), false)
})
