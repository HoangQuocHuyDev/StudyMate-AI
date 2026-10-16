import assert from 'node:assert/strict'
import test from 'node:test'

import { createPasswordChangeResponseGuard } from '../src/components/settingsPasswordFlow.js'


function createHarness() {
  let currentSession = { accessToken: 'token-a', generation: 1 }
  let logoutCount = 0
  const guard = createPasswordChangeResponseGuard({
    getSessionIdentity: () => ({ ...currentSession }),
    isCurrentSession: (identity) => (
      identity?.accessToken === currentSession.accessToken
      && identity?.generation === currentSession.generation
    ),
    logoutCurrentSession: (identity) => {
      if (
        identity?.accessToken !== currentSession.accessToken
        || identity?.generation !== currentSession.generation
      ) return false
      logoutCount += 1
      currentSession = { accessToken: null, generation: currentSession.generation + 1 }
      return true
    },
  })
  return {
    guard,
    get logoutCount() { return logoutCount },
    setSession(accessToken, generation) {
      currentSession = { accessToken, generation }
    },
  }
}

test('successful password change logs out the same authenticated session', () => {
  const harness = createHarness()
  const request = harness.guard.begin()

  assert.equal(harness.guard.complete(request), true)
  assert.equal(harness.logoutCount, 1)
})

test('an old password response cannot log out a newer session', () => {
  const harness = createHarness()
  const request = harness.guard.begin()
  harness.setSession('token-b', 2)

  assert.equal(harness.guard.complete(request), false)
  assert.equal(harness.guard.canHandleResponse(request), false)
  assert.equal(harness.logoutCount, 0)
})

test('a password response after unmount has no session side effect', () => {
  const harness = createHarness()
  const request = harness.guard.begin()
  harness.guard.unmount()

  assert.equal(harness.guard.complete(request), false)
  assert.equal(harness.guard.canHandleResponse(request), false)
  assert.equal(harness.logoutCount, 0)
})

test('a failed password request may update UI only for its original session', () => {
  const harness = createHarness()
  const request = harness.guard.begin()

  assert.equal(harness.guard.canHandleResponse(request), true)
  assert.equal(harness.logoutCount, 0)
})
