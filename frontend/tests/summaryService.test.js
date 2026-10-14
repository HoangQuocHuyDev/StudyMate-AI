import assert from 'node:assert/strict'
import test from 'node:test'

import apiClient, { ApiHttpError } from '../src/services/apiClient.js'
import {
  generateSummary,
  getDocumentSummaries,
} from '../src/services/summaryService.js'

test('generateSummary sends the authenticated POST payload', async (context) => {
  const controller = new AbortController()
  let captured
  context.mock.method(apiClient, 'post', async (...args) => {
    captured = args
    return { summary_id: 1, summary_type: 'STANDARD' }
  })

  const result = await generateSummary(7, ' standard ', {
    accessToken: 'header.payload.signature',
    signal: controller.signal,
  })

  assert.equal(captured[0], '/summaries/generate')
  assert.deepEqual(captured[1], { document_id: 7, summary_type: 'STANDARD' })
  assert.deepEqual(captured[2].headers, {
    Authorization: 'Bearer header.payload.signature',
  })
  assert.equal(captured[2].signal, controller.signal)
  assert.equal(JSON.stringify(captured).includes('user_id'), false)
  assert.equal(result.summary_id, 1)
})

for (const summaryType of ['SHORT', 'STANDARD', 'DETAILED']) {
  test(`generateSummary accepts ${summaryType}`, async (context) => {
    let payload
    context.mock.method(apiClient, 'post', async (_path, json) => {
      payload = json
      return { summary_type: summaryType }
    })
    await generateSummary(1, summaryType, { accessToken: 'token' })
    assert.equal(payload.summary_type, summaryType)
  })
}

test('getDocumentSummaries uses a safe query and JWT Bearer', async (context) => {
  let captured
  context.mock.method(apiClient, 'get', async (...args) => {
    captured = args
    return { document_id: 12, items: [] }
  })

  const response = await getDocumentSummaries(12, { accessToken: 'token' })
  const url = new URL(captured[0], 'https://frontend.test')
  assert.equal(url.pathname, '/summaries')
  assert.equal(url.searchParams.get('document_id'), '12')
  assert.deepEqual(captured[1].headers, { Authorization: 'Bearer token' })
  assert.deepEqual(response.items, [])
})

test('summary services validate ids, summary types, and token before requests', (context) => {
  let calls = 0
  context.mock.method(apiClient, 'post', async () => { calls += 1 })
  context.mock.method(apiClient, 'get', async () => { calls += 1 })

  for (const id of [0, -1, 1.5, '1', true]) {
    assert.throws(() => generateSummary(id, 'SHORT', { accessToken: 'token' }), TypeError)
    assert.throws(() => getDocumentSummaries(id, { accessToken: 'token' }), TypeError)
  }
  for (const summaryType of ['', 'MEDIUM', null, 1]) {
    assert.throws(() => generateSummary(1, summaryType, { accessToken: 'token' }), TypeError)
  }
  for (const accessToken of ['', ' token ', null]) {
    assert.throws(() => generateSummary(1, 'SHORT', { accessToken }), TypeError)
    assert.throws(() => getDocumentSummaries(1, { accessToken }), TypeError)
  }
  assert.equal(calls, 0)
})

for (const status of [401, 404, 409, 413, 422, 429, 500, 503, 504]) {
  test(`summary service preserves HTTP ${status} for safe UI mapping`, async (context) => {
    const error = new ApiHttpError('secret raw error', {
      status,
      statusText: 'Failure',
      data: { detail: 'secret raw error' },
    })
    context.mock.method(apiClient, 'post', async () => { throw error })
    await assert.rejects(
      generateSummary(1, 'SHORT', { accessToken: 'token' }),
      (received) => received === error,
    )
  })
}

test('summary services never access browser storage', async (context) => {
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
  context.mock.method(apiClient, 'post', async () => ({ summary_id: 1 }))
  context.mock.method(apiClient, 'get', async () => ({ document_id: 1, items: [] }))

  await generateSummary(1, 'SHORT', { accessToken: 'token' })
  await getDocumentSummaries(1, { accessToken: 'token' })
  assert.equal(storageAccessed, false)
})
