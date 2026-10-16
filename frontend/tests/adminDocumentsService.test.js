import assert from 'node:assert/strict'
import test from 'node:test'

import apiClient, { ApiHttpError } from '../src/services/apiClient.js'
import {
  getAdminDocumentDetail,
  getAdminDocuments,
} from '../src/services/adminDocumentsService.js'


test('getAdminDocuments sends JWT, search, filters, and pagination', async (context) => {
  const controller = new AbortController()
  let captured
  context.mock.method(apiClient, 'get', async (...args) => {
    captured = args
    return { items: [], total: 0, limit: 20, offset: 20 }
  })

  await getAdminDocuments({
    accessToken: 'header.payload.signature',
    limit: 20,
    offset: 20,
    search: '  Giáo trình & AI  ',
    fileType: 'PDF',
    status: 'READY',
    ragStatus: 'INDEXING',
    signal: controller.signal,
  })

  const [path, options] = captured
  const url = new URL(path, 'https://studymate.local')
  assert.equal(url.pathname, '/admin/documents')
  assert.deepEqual(Object.fromEntries(url.searchParams), {
    limit: '20',
    offset: '20',
    search: 'Giáo trình & AI',
    file_type: 'PDF',
    status: 'READY',
    rag_status: 'INDEXING',
  })
  assert.deepEqual(options.headers, { Authorization: 'Bearer header.payload.signature' })
  assert.equal(options.signal, controller.signal)
  assert.equal(path.includes('header.payload.signature'), false)
})

test('getAdminDocuments omits empty optional filters', async (context) => {
  let path
  context.mock.method(apiClient, 'get', async (requestPath) => {
    path = requestPath
    return { items: [], total: 0, limit: 20, offset: 0 }
  })
  await getAdminDocuments({ accessToken: 'token', search: '   ' })
  assert.equal(path, '/admin/documents?limit=20&offset=0')
})

test('getAdminDocumentDetail uses the read-only detail endpoint and JWT', async (context) => {
  let captured
  context.mock.method(apiClient, 'get', async (...args) => {
    captured = args
    return { id: 17 }
  })
  await getAdminDocumentDetail(17, { accessToken: 'token' })
  assert.deepEqual(captured, [
    '/admin/documents/17',
    { headers: { Authorization: 'Bearer token' }, signal: undefined },
  ])
})

test('Admin Documents service validates inputs before requesting', (context) => {
  const get = context.mock.method(apiClient, 'get', async () => ({}))
  for (const accessToken of [undefined, '', ' token ', 123]) {
    assert.throws(() => getAdminDocuments({ accessToken }), TypeError)
  }
  for (const limit of [0, 101, 1.5, '20']) {
    assert.throws(() => getAdminDocuments({ accessToken: 'token', limit }), TypeError)
  }
  assert.throws(() => getAdminDocuments({ accessToken: 'token', offset: -1 }), TypeError)
  assert.throws(() => getAdminDocuments({ accessToken: 'token', search: 'x'.repeat(256) }), TypeError)
  assert.throws(() => getAdminDocuments({ accessToken: 'token', fileType: 'TXT' }), TypeError)
  assert.throws(() => getAdminDocuments({ accessToken: 'token', status: 'DELETED' }), TypeError)
  assert.throws(() => getAdminDocuments({ accessToken: 'token', ragStatus: 'UNKNOWN' }), TypeError)
  assert.throws(() => getAdminDocumentDetail(0, { accessToken: 'token' }), TypeError)
  assert.equal(get.mock.callCount(), 0)
})

for (const status of [401, 403, 404, 422, 500]) {
  test(`Admin Documents service preserves HTTP ${status}`, async (context) => {
    const error = new ApiHttpError('hidden', {
      status,
      statusText: 'Failure',
      data: { detail: 'hidden' },
    })
    context.mock.method(apiClient, 'get', async () => { throw error })
    await assert.rejects(
      getAdminDocumentDetail(2, { accessToken: 'token' }),
      (caught) => caught === error,
    )
  })
}

test('Admin Documents service never reads browser token storage or calls DELETE', async (context) => {
  const originalLocalStorage = globalThis.localStorage
  const originalSessionStorage = globalThis.sessionStorage
  Object.defineProperty(globalThis, 'localStorage', {
    configurable: true,
    get() { throw new Error('localStorage must not be read') },
  })
  Object.defineProperty(globalThis, 'sessionStorage', {
    configurable: true,
    get() { throw new Error('sessionStorage must not be read') },
  })
  context.after(() => {
    if (originalLocalStorage === undefined) delete globalThis.localStorage
    else Object.defineProperty(globalThis, 'localStorage', { configurable: true, value: originalLocalStorage })
    if (originalSessionStorage === undefined) delete globalThis.sessionStorage
    else Object.defineProperty(globalThis, 'sessionStorage', { configurable: true, value: originalSessionStorage })
  })
  const get = context.mock.method(apiClient, 'get', async () => ({ items: [], total: 0, limit: 20, offset: 0 }))
  const remove = context.mock.method(apiClient, 'delete', async () => null)

  await getAdminDocuments({ accessToken: 'memory-token' })
  assert.equal(get.mock.callCount(), 1)
  assert.equal(remove.mock.callCount(), 0)
})
