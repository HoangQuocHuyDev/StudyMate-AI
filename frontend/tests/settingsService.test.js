import assert from 'node:assert/strict'
import test from 'node:test'

import apiClient, { ApiHttpError } from '../src/services/apiClient.js'
import { changePassword, updateProfile } from '../src/services/authService.js'

const accessToken = 'header.payload.signature'
const userResponse = {
  id: 7,
  full_name: 'Nguyễn Văn An',
  username: 'nguyenvanan',
  role: 'USER',
  is_active: true,
  created_at: '2026-10-16T08:00:00Z',
}

test('updateProfile sends only full_name with the active bearer token', async (context) => {
  let captured
  context.mock.method(apiClient, 'patch', async (...args) => {
    captured = args
    return userResponse
  })

  const result = await updateProfile('Nguyễn Văn An', { accessToken })
  assert.equal(result, userResponse)
  assert.deepEqual(captured, [
    '/auth/me',
    { full_name: 'Nguyễn Văn An' },
    { headers: { Authorization: `Bearer ${accessToken}` }, signal: undefined },
  ])
})

test('changePassword sends the three password fields and accepts a 204 response', async (context) => {
  let captured
  context.mock.method(apiClient, 'post', async (...args) => {
    captured = args
    return null
  })

  const result = await changePassword({
    currentPassword: 'CurrentPass123',
    newPassword: 'NewPassword456',
    confirmNewPassword: 'NewPassword456',
  }, { accessToken })

  assert.equal(result, undefined)
  assert.deepEqual(captured, [
    '/auth/change-password',
    {
      current_password: 'CurrentPass123',
      new_password: 'NewPassword456',
      confirm_new_password: 'NewPassword456',
    },
    { headers: { Authorization: `Bearer ${accessToken}` }, signal: undefined },
  ])
})

test('Settings service preserves safe backend errors for the UI', async (context) => {
  const error = new ApiHttpError('Mật khẩu hiện tại không chính xác.', {
    status: 400,
    statusText: 'Bad Request',
    data: { detail: 'Mật khẩu hiện tại không chính xác.' },
  })
  context.mock.method(apiClient, 'post', async () => { throw error })

  await assert.rejects(
    changePassword({
      currentPassword: 'wrong',
      newPassword: 'NewPassword456',
      confirmNewPassword: 'NewPassword456',
    }, { accessToken }),
    (caught) => caught === error,
  )
})

test('Settings service validates tokens and never reads browser token storage', async (context) => {
  const patch = context.mock.method(apiClient, 'patch', async () => userResponse)
  const post = context.mock.method(apiClient, 'post', async () => null)
  const originalLocalStorage = globalThis.localStorage
  const originalSessionStorage = globalThis.sessionStorage
  Object.defineProperty(globalThis, 'localStorage', {
    configurable: true,
    get() { throw new Error('token storage must not be read') },
  })
  Object.defineProperty(globalThis, 'sessionStorage', {
    configurable: true,
    get() { throw new Error('token storage must not be read') },
  })

  try {
    await assert.rejects(updateProfile('Valid Name', { accessToken: ' token ' }), TypeError)
    await assert.rejects(changePassword({
      currentPassword: 'a',
      newPassword: 'b',
      confirmNewPassword: 'b',
    }, { accessToken: '' }), TypeError)
    assert.equal(patch.mock.callCount(), 0)
    assert.equal(post.mock.callCount(), 0)
  } finally {
    if (originalLocalStorage === undefined) delete globalThis.localStorage
    else Object.defineProperty(globalThis, 'localStorage', { configurable: true, value: originalLocalStorage })
    if (originalSessionStorage === undefined) delete globalThis.sessionStorage
    else Object.defineProperty(globalThis, 'sessionStorage', { configurable: true, value: originalSessionStorage })
  }
})
