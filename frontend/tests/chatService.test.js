import assert from 'node:assert/strict'
import test from 'node:test'

import apiClient, { ApiHttpError } from '../src/services/apiClient.js'
import {
  askDocument,
  getChatCitation,
  getChatMessages,
  getChatMessagesCursor,
  getChatSessions,
} from '../src/services/chatService.js'

test('askDocument sends the expected authenticated POST payload', async (context) => {
  const controller = new AbortController()
  let captured
  context.mock.method(apiClient, 'post', async (...args) => {
    captured = args
    return { session_id: 5 }
  })

  const result = await askDocument(3, '  Tài liệu nói gì?  ', 5, {
    accessToken: 'header.payload.signature',
    signal: controller.signal,
  })

  assert.deepEqual(result, { session_id: 5 })
  assert.equal(captured[0], '/chat/ask')
  assert.deepEqual(captured[1], {
    document_id: 3,
    question: 'Tài liệu nói gì?',
    session_id: 5,
  })
  assert.deepEqual(captured[2].headers, {
    Authorization: 'Bearer header.payload.signature',
  })
  assert.equal(captured[2].signal, controller.signal)
  assert.equal(JSON.stringify(captured).includes('user_id'), false)
})

test('askDocument starts a new session with a null session_id', async (context) => {
  let payload
  context.mock.method(apiClient, 'post', async (path, json) => {
    payload = json
    return { session_id: 1 }
  })

  await askDocument(1, 'Câu hỏi', null, { accessToken: 'token' })

  assert.equal(payload.session_id, null)
})

test('chat history services use safe query strings and authenticated GET', async (context) => {
  const calls = []
  context.mock.method(apiClient, 'get', async (...args) => {
    calls.push(args)
    return { items: [], total: 0, limit: 20, offset: 0 }
  })

  await getChatSessions(7, 20, 40, { accessToken: 'token' })
  await getChatMessages(9, 50, 100, { accessToken: 'token' })

  const sessionsUrl = new URL(calls[0][0], 'https://frontend.test')
  assert.equal(sessionsUrl.pathname, '/chat/sessions')
  assert.equal(sessionsUrl.searchParams.get('document_id'), '7')
  assert.equal(sessionsUrl.searchParams.get('limit'), '20')
  assert.equal(sessionsUrl.searchParams.get('offset'), '40')
  assert.equal(calls[1][0], '/chat/sessions/9/messages?limit=50&offset=100')
  assert.deepEqual(calls[0][1].headers, { Authorization: 'Bearer token' })
  assert.deepEqual(calls[1][1].headers, { Authorization: 'Bearer token' })
})

test('cursor history requests newest and older pages with JWT', async (context) => {
  const controller = new AbortController()
  const calls = []
  context.mock.method(apiClient, 'get', async (...args) => {
    calls.push(args)
    return {
      session_id: 9,
      items: [],
      total: 0,
      limit: 50,
      next_before_sequence_no: null,
      has_more: false,
    }
  })

  await getChatMessagesCursor(9, null, 50, {
    accessToken: 'header.payload.signature',
    signal: controller.signal,
  })
  await getChatMessagesCursor(9, 70, 50, {
    accessToken: 'header.payload.signature',
    signal: controller.signal,
  })

  const newestUrl = new URL(calls[0][0], 'https://frontend.test')
  const olderUrl = new URL(calls[1][0], 'https://frontend.test')
  assert.equal(newestUrl.pathname, '/chat/sessions/9/messages/cursor')
  assert.equal(newestUrl.searchParams.get('limit'), '50')
  assert.equal(newestUrl.searchParams.has('before_sequence_no'), false)
  assert.equal(olderUrl.searchParams.get('before_sequence_no'), '70')
  assert.deepEqual(calls[0][1].headers, {
    Authorization: 'Bearer header.payload.signature',
  })
  assert.equal(calls[0][1].signal, controller.signal)
})

test('getChatCitation sends all verified citation identifiers with JWT', async (context) => {
  const controller = new AbortController()
  let captured
  context.mock.method(apiClient, 'get', async (...args) => {
    captured = args
    return { chunk_id: 11, content: 'Nội dung gốc' }
  })

  const result = await getChatCitation(11, 7, 19, {
    accessToken: 'header.payload.signature',
    signal: controller.signal,
  })

  const url = new URL(captured[0], 'https://frontend.test')
  assert.equal(url.pathname, '/chat/citations/11')
  assert.equal(url.searchParams.get('session_id'), '7')
  assert.equal(url.searchParams.get('message_id'), '19')
  assert.deepEqual(captured[1].headers, {
    Authorization: 'Bearer header.payload.signature',
  })
  assert.equal(captured[1].signal, controller.signal)
  assert.equal(result.content, 'Nội dung gốc')
})

test('chat services validate questions, ids, pagination, and token before requests', (context) => {
  let requestCount = 0
  context.mock.method(apiClient, 'post', async () => { requestCount += 1 })
  context.mock.method(apiClient, 'get', async () => { requestCount += 1 })

  for (const question of ['', '   ', 'x'.repeat(2001), null]) {
    assert.throws(
      () => askDocument(1, question, null, { accessToken: 'token' }),
      TypeError,
    )
  }
  for (const id of [0, -1, 1.5, '1', true]) {
    assert.throws(() => askDocument(id, 'Q', null, { accessToken: 'token' }), TypeError)
    assert.throws(() => getChatSessions(id, 20, 0, { accessToken: 'token' }), TypeError)
    assert.throws(() => getChatMessages(id, 50, 0, { accessToken: 'token' }), TypeError)
    assert.throws(() => getChatMessagesCursor(id, null, 50, { accessToken: 'token' }), TypeError)
    assert.throws(() => getChatCitation(id, 1, 1, { accessToken: 'token' }), TypeError)
    assert.throws(() => getChatCitation(1, id, 1, { accessToken: 'token' }), TypeError)
    assert.throws(() => getChatCitation(1, 1, id, { accessToken: 'token' }), TypeError)
  }
  assert.throws(() => askDocument(1, 'Q', 0, { accessToken: 'token' }), TypeError)
  assert.throws(() => getChatSessions(1, 101, 0, { accessToken: 'token' }), TypeError)
  assert.throws(() => getChatMessages(1, 50, -1, { accessToken: 'token' }), TypeError)
  for (const cursor of [-1, 1.5, '1', true]) {
    assert.throws(
      () => getChatMessagesCursor(1, cursor, 50, { accessToken: 'token' }),
      TypeError,
    )
  }
  for (const limit of [0, 51, 1.5]) {
    assert.throws(
      () => getChatMessagesCursor(1, null, limit, { accessToken: 'token' }),
      TypeError,
    )
  }
  assert.throws(() => askDocument(1, 'Q', null, { accessToken: ' token ' }), TypeError)
  assert.equal(requestCount, 0)
})

for (const status of [401, 404, 409, 422, 429, 500, 503, 504]) {
  test(`askDocument preserves HTTP ${status} for safe UI mapping`, async (context) => {
    const error = new ApiHttpError('secret raw error', {
      status,
      statusText: 'Failure',
      data: { detail: 'secret raw error' },
    })
    context.mock.method(apiClient, 'post', async () => { throw error })
    await assert.rejects(
      askDocument(1, 'Q', null, { accessToken: 'token' }),
      (received) => received === error,
    )
  })
}

test('chat services never access browser storage', async (context) => {
  let storageAccessed = false
  const storage = {
    getItem() { storageAccessed = true },
    setItem() { storageAccessed = true },
  }
  Object.defineProperty(globalThis, 'localStorage', { configurable: true, value: storage })
  Object.defineProperty(globalThis, 'sessionStorage', { configurable: true, value: storage })
  context.after(() => {
    delete globalThis.localStorage
    delete globalThis.sessionStorage
  })
  context.mock.method(apiClient, 'post', async () => ({ session_id: 1 }))
  context.mock.method(apiClient, 'get', async () => ({ items: [], total: 0 }))

  await askDocument(1, 'Q', null, { accessToken: 'token' })
  await getChatSessions(1, 20, 0, { accessToken: 'token' })
  await getChatMessages(1, 50, 0, { accessToken: 'token' })
  await getChatMessagesCursor(1, null, 50, { accessToken: 'token' })
  await getChatCitation(1, 1, 1, { accessToken: 'token' })

  assert.equal(storageAccessed, false)
})
