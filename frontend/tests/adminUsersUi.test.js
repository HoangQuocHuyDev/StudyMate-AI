import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

import { ApiHttpError, ApiNetworkError } from '../src/services/apiClient.js'
import {
  ADMIN_USERS_PAGE_SIZE,
  adminUsersReducer,
  createAdminUserStatusController,
  getAdminUserStatusAction,
  getAdminUsersAdjustedOffset,
  getAdminUsersErrorMessage,
  getAdminUsersPageInfo,
  initialAdminUsersState,
  parseActivityFilter,
  validateAdminUserListResponse,
  validateAdminUserResponse,
} from '../src/components/admin/adminUsersUi.js'


const account = {
  id: 2,
  full_name: 'Nguyễn Văn A',
  username: 'student01',
  role: 'USER',
  is_active: true,
  created_at: '2026-10-15T08:00:00Z',
}

const page = {
  items: [account],
  total: 41,
  limit: 20,
  offset: 20,
}

test('Admin Users response maps real API data and pagination', () => {
  const result = validateAdminUserListResponse(page)
  assert.deepEqual(result.items, [account])
  assert.equal(ADMIN_USERS_PAGE_SIZE, 20)
  assert.deepEqual(getAdminUsersPageInfo(result), {
    currentPage: 2,
    pageCount: 3,
    firstItem: 21,
    lastItem: 40,
    canGoBack: true,
    canGoForward: true,
  })
})

test('Admin Users validates role, status, dates, duplicates and pagination', () => {
  assert.throws(() => validateAdminUserListResponse({}), TypeError)
  assert.throws(() => validateAdminUserListResponse({ ...page, total: -1 }), TypeError)
  assert.throws(() => validateAdminUserListResponse({ ...page, items: [account, account] }), TypeError)
  assert.throws(() => validateAdminUserListResponse({
    ...page,
    items: [{ ...account, role: 'OWNER' }],
  }), TypeError)
  assert.throws(() => validateAdminUserResponse({
    ...account,
    created_at: 'not-a-date',
  }), TypeError)
})

test('sensitive authentication fields are rejected and never mapped for display', () => {
  for (const sensitiveField of ['password_hash', 'token_version', 'password', 'access_token']) {
    assert.throws(() => validateAdminUserResponse({
      ...account,
      [sensitiveField]: 'secret',
    }), TypeError)
  }
  assert.deepEqual(Object.keys(validateAdminUserResponse(account)), [
    'id',
    'full_name',
    'username',
    'role',
    'is_active',
    'created_at',
  ])
})

test('search filters and pagination state have explicit mappings', () => {
  assert.equal(parseActivityFilter('active'), true)
  assert.equal(parseActivityFilter('inactive'), false)
  assert.equal(parseActivityFilter('all'), null)
  assert.deepEqual(getAdminUsersPageInfo({ total: 0, offset: 0, limit: 20 }), {
    currentPage: 1,
    pageCount: 1,
    firstItem: 0,
    lastItem: 0,
    canGoBack: false,
    canGoForward: false,
  })
})

test('Admin Users accepts an empty page beyond total and adjusts to the last page', () => {
  const overflow = validateAdminUserListResponse({
    items: [], total: 25, limit: 20, offset: 40,
  })
  assert.deepEqual(overflow.items, [])
  assert.equal(getAdminUsersAdjustedOffset(overflow), 20)

  const filtered = validateAdminUserListResponse({
    items: [], total: 11, limit: 20, offset: 60,
  })
  assert.equal(getAdminUsersAdjustedOffset(filtered), 0)
})

test('Admin Users normalizes an empty data set to offset zero without a loop', () => {
  const empty = validateAdminUserListResponse({
    items: [], total: 0, limit: 20, offset: 20,
  })
  assert.equal(getAdminUsersAdjustedOffset(empty), 0)
  assert.equal(getAdminUsersAdjustedOffset({ ...empty, offset: 0 }), 0)
})

test('confirmation action identifies lock, unlock, and blocks self-lock', () => {
  assert.equal(getAdminUserStatusAction(account, account.id), null)
  const lock = getAdminUserStatusAction(account, 99)
  assert.equal(lock.desiredStatus, false)
  assert.equal(lock.title, 'Khóa tài khoản?')
  const unlock = getAdminUserStatusAction({ ...account, is_active: false }, account.id)
  assert.equal(unlock.desiredStatus, true)
  assert.equal(unlock.confirmLabel, 'Mở khóa')
})

test('canceling confirmation does not invoke PATCH and double submit shares one request', async () => {
  let calls = 0
  let resolveRequest
  const controller = createAdminUserStatusController(({ signal }) => {
    calls += 1
    assert.equal(signal.aborted, false)
    return new Promise((resolve) => { resolveRequest = resolve })
  })

  assert.equal(calls, 0)
  const first = controller.run({ userId: 2, isActive: false })
  const second = controller.run({ userId: 2, isActive: false })
  assert.equal(first, second)
  assert.equal(calls, 1)
  assert.equal(controller.isPending(), true)
  resolveRequest(account)
  await first
  assert.equal(controller.isPending(), false)
})

test('status controller releases the guard after failure so the user can retry', async () => {
  let calls = 0
  const controller = createAdminUserStatusController(async () => {
    calls += 1
    if (calls === 1) throw new Error('safe failure')
    return account
  })
  await assert.rejects(controller.run({}), /safe failure/)
  assert.deepEqual(await controller.run({}), account)
  assert.equal(calls, 2)
})

test('Admin Users reducer ignores stale data and keeps trusted data on refresh error', () => {
  let state = adminUsersReducer(initialAdminUsersState, {
    type: 'request-started', requestId: 2,
  })
  state = adminUsersReducer(state, {
    type: 'request-succeeded', requestId: 1, data: { ...page, total: 99 },
  })
  assert.equal(state.data, null)
  state = adminUsersReducer(state, {
    type: 'request-succeeded', requestId: 2, data: page,
  })
  state = adminUsersReducer(state, {
    type: 'request-started', requestId: 3,
  })
  state = adminUsersReducer(state, {
    type: 'request-failed', requestId: 3, error: 'Mất kết nối',
  })
  assert.equal(state.data, page)
  assert.equal(state.status, 'error')
})

test('Admin Users ignores an older response that arrives after the newest response', () => {
  const newestPage = { ...page, items: [], total: 0, offset: 0 }
  let state = adminUsersReducer(initialAdminUsersState, {
    type: 'request-started', requestId: 4,
  })
  state = adminUsersReducer(state, {
    type: 'request-started', requestId: 5,
  })
  state = adminUsersReducer(state, {
    type: 'request-succeeded', requestId: 5, data: newestPage,
  })
  state = adminUsersReducer(state, {
    type: 'request-succeeded', requestId: 4, data: page,
  })
  assert.equal(state.data, newestPage)
})

for (const [status, pattern] of [
  [401, /hết hạn/],
  [403, /không có quyền/],
  [404, /không còn tồn tại/],
  [409, /bảo vệ quản trị viên/],
  [422, /không hợp lệ/],
  [500, /Máy chủ/],
]) {
  test(`HTTP ${status} has a safe Vietnamese Admin Users message`, () => {
    const error = new ApiHttpError('raw secret', {
      status,
      statusText: 'Failure',
      data: { detail: 'raw secret' },
    })
    const message = getAdminUsersErrorMessage(error)
    assert.match(message, pattern)
    assert.equal(message.includes('raw secret'), false)
  })
}

test('network error is safe and retryable', () => {
  assert.match(getAdminUsersErrorMessage(new ApiNetworkError('raw')), /kết nối/)
})

test('AdminUsers source contains confirmation-only status mutation and no mock data', async () => {
  const source = await readFile(
    new URL('../src/components/admin/AdminUsers.jsx', import.meta.url),
    'utf8',
  )
  assert.equal(source.includes('initialUsers'), false)
  assert.match(source, /onClick=\{confirmStatusChange\}/)
  assert.match(source, /onClick=\{closeConfirmation\}/)
  assert.match(source, /maxLength=\{255\}/)
  assert.match(source, /setTimeout\(\(\) => \{/)
  assert.match(source, /\}, 350\)/)
})
