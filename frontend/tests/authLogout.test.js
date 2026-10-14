import assert from 'node:assert/strict'
import test from 'node:test'

import apiClient, {
  ApiHttpError,
  ApiNetworkError,
} from '../src/services/apiClient.js'
import { logout as requestLogout } from '../src/services/authService.js'
import { createLogoutController } from '../src/contexts/authLogout.js'


function deferred() {
  let resolve
  let reject
  const promise = new Promise((resolvePromise, rejectPromise) => {
    resolve = resolvePromise
    reject = rejectPromise
  })
  return { promise, reject, resolve }
}

function createControllerHarness(request) {
  let session = {
    accessToken: 'header.payload.signature',
    version: 1,
  }
  const pendingStates = []
  let clearCount = 0
  const controller = createLogoutController(request)
  const logout = () => controller.logout({
    getSession: () => session,
    clearSession: () => {
      clearCount += 1
      session = { accessToken: null, version: session.version + 1 }
    },
    setPending: (pending) => pendingStates.push(pending),
  })

  return {
    controller,
    logout,
    getClearCount: () => clearCount,
    getPendingStates: () => pendingStates,
    replaceSession: (nextSession) => { session = nextSession },
  }
}

test('logout service sends the current Bearer token and accepts a 204 result', async (context) => {
  let captured
  context.mock.method(apiClient, 'post', async (...args) => {
    captured = args
    return null
  })

  const result = await requestLogout('header.payload.signature')

  assert.equal(result, undefined)
  assert.equal(captured[0], '/auth/logout')
  assert.equal(captured[1], undefined)
  assert.deepEqual(captured[2].headers, {
    Authorization: 'Bearer header.payload.signature',
  })
})

test('logout service forwards AbortSignal and validates the token', async (context) => {
  const abortController = new AbortController()
  let capturedSignal
  context.mock.method(apiClient, 'post', async (path, json, options) => {
    capturedSignal = options.signal
    return null
  })

  await requestLogout('token', { signal: abortController.signal })

  assert.equal(capturedSignal, abortController.signal)
  for (const token of [undefined, '', '   ', ' token ']) {
    await assert.rejects(requestLogout(token), TypeError)
  }
})

for (const error of [
  new ApiHttpError('Unauthorized', {
    status: 401,
    statusText: 'Unauthorized',
    data: null,
  }),
  new ApiHttpError('Server error', {
    status: 500,
    statusText: 'Server Error',
    data: null,
  }),
  new ApiNetworkError('Network unavailable'),
]) {
  test(`local session is cleared when logout fails with ${error.name} ${error.status ?? ''}`, async () => {
    const harness = createControllerHarness(async () => { throw error })

    const cleared = await harness.logout()

    assert.equal(cleared, true)
    assert.equal(harness.getClearCount(), 1)
    assert.deepEqual(harness.getPendingStates(), [true, false])
  })
}

test('double logout reuses one in-flight request', async () => {
  const request = deferred()
  let requestCount = 0
  const harness = createControllerHarness(() => {
    requestCount += 1
    return request.promise
  })

  const first = harness.logout()
  const second = harness.logout()
  request.resolve(null)

  assert.equal(first, second)
  assert.equal(await first, true)
  assert.equal(requestCount, 1)
  assert.equal(harness.getClearCount(), 1)
})

test('an old logout response cannot clear a replacement session', async () => {
  const request = deferred()
  let capturedToken
  const harness = createControllerHarness((token) => {
    capturedToken = token
    return request.promise
  })

  const logoutResult = harness.logout()
  harness.replaceSession({
    accessToken: 'new.header.payload',
    version: 2,
  })
  request.resolve(null)

  assert.equal(await logoutResult, false)
  assert.equal(capturedToken, 'header.payload.signature')
  assert.equal(harness.getClearCount(), 0)
})

test('logout does not access browser storage', async (context) => {
  let storageAccessed = false
  const storage = {
    getItem() { storageAccessed = true },
    setItem() { storageAccessed = true },
    removeItem() { storageAccessed = true },
  }
  Object.defineProperty(globalThis, 'localStorage', {
    configurable: true,
    value: storage,
  })
  Object.defineProperty(globalThis, 'sessionStorage', {
    configurable: true,
    value: storage,
  })
  context.after(() => {
    delete globalThis.localStorage
    delete globalThis.sessionStorage
  })
  context.mock.method(apiClient, 'post', async () => null)
  const harness = createControllerHarness(requestLogout)

  await harness.logout()

  assert.equal(storageAccessed, false)
})
