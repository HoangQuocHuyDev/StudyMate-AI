import assert from 'node:assert/strict'
import test from 'node:test'

import apiClient, { ApiHttpError } from '../src/services/apiClient.js'
import {
  getAdminUsers,
  updateAdminUserStatus,
} from '../src/services/adminUsersService.js'


test('getAdminUsers sends JWT with search, filters, and offset pagination', async (context) => {
  const controller = new AbortController()
  let captured
  context.mock.method(apiClient, 'get', async (...args) => {
    captured = args
    return { items: [], total: 0, limit: 20, offset: 40 }
  })

  await getAdminUsers({
    accessToken: 'header.payload.signature',
    limit: 20,
    offset: 40,
    search: '  sinh viên & AI  ',
    role: 'USER',
    isActive: false,
    signal: controller.signal,
  })

  const [path, options] = captured
  const url = new URL(path, 'https://studymate.local')
  assert.equal(url.pathname, '/admin/users')
  assert.deepEqual(Object.fromEntries(url.searchParams), {
    limit: '20',
    offset: '40',
    search: 'sinh viên & AI',
    role: 'USER',
    is_active: 'false',
  })
  assert.deepEqual(options.headers, {
    Authorization: 'Bearer header.payload.signature',
  })
  assert.equal(options.signal, controller.signal)
  assert.equal(path.includes('header.payload.signature'), false)
})

test('getAdminUsers omits empty optional filters', async (context) => {
  let path
  context.mock.method(apiClient, 'get', async (requestPath) => {
    path = requestPath
    return { items: [], total: 0, limit: 20, offset: 0 }
  })

  await getAdminUsers({ accessToken: 'token', search: '   ' })
  assert.equal(path, '/admin/users?limit=20&offset=0')
})

test('updateAdminUserStatus sends only the requested boolean status', async (context) => {
  let captured
  context.mock.method(apiClient, 'patch', async (...args) => {
    captured = args
    return { id: 9, is_active: false }
  })

  await updateAdminUserStatus(9, false, { accessToken: 'token' })
  assert.deepEqual(captured, [
    '/admin/users/9/status',
    { is_active: false },
    {
      headers: { Authorization: 'Bearer token' },
      signal: undefined,
    },
  ])
})

test('Admin Users service validates inputs before making requests', (context) => {
  const get = context.mock.method(apiClient, 'get', async () => ({}))
  const patch = context.mock.method(apiClient, 'patch', async () => ({}))

  for (const accessToken of [undefined, '', ' token ', 123]) {
    assert.throws(() => getAdminUsers({ accessToken }), TypeError)
  }
  for (const limit of [0, 101, 1.5, '20']) {
    assert.throws(() => getAdminUsers({ accessToken: 'token', limit }), TypeError)
  }
  assert.throws(() => getAdminUsers({ accessToken: 'token', offset: -1 }), TypeError)
  assert.throws(() => getAdminUsers({ accessToken: 'token', search: 'x'.repeat(256) }), TypeError)
  assert.throws(() => getAdminUsers({ accessToken: 'token', role: 'OWNER' }), TypeError)
  assert.throws(() => getAdminUsers({ accessToken: 'token', isActive: 'false' }), TypeError)
  assert.throws(() => updateAdminUserStatus(0, false, { accessToken: 'token' }), TypeError)
  assert.throws(() => updateAdminUserStatus(1, 'false', { accessToken: 'token' }), TypeError)
  assert.equal(get.mock.callCount(), 0)
  assert.equal(patch.mock.callCount(), 0)
})

for (const status of [401, 403, 404, 409, 422, 500]) {
  test(`Admin Users service preserves HTTP ${status} for safe UI handling`, async (context) => {
    const error = new ApiHttpError('hidden', {
      status,
      statusText: 'Failure',
      data: { detail: 'hidden' },
    })
    context.mock.method(apiClient, 'patch', async () => { throw error })
    await assert.rejects(
      updateAdminUserStatus(2, false, { accessToken: 'token' }),
      (caught) => caught === error,
    )
  })
}

test('Admin Users service never accesses browser token storage', async (context) => {
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
  context.mock.method(apiClient, 'get', async () => ({ items: [], total: 0, limit: 20, offset: 0 }))

  await getAdminUsers({ accessToken: 'memory-token' })
})
