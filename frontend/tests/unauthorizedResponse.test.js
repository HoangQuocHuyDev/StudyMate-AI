import assert from 'node:assert/strict'
import test from 'node:test'
import { createUnauthorizedResponseController } from '../src/services/unauthorizedResponse.js'

function bearerHeaders(accessToken = 'token-one') {
  return new Headers({ Authorization: `Bearer ${accessToken}` })
}

test('an authenticated 401 clears the active in-memory session once', () => {
  const controller = createUnauthorizedResponseController()
  const rejectedTokens = []
  let unregister = null
  unregister = controller.register((accessToken) => {
    rejectedTokens.push(accessToken)
    unregister()
  })
  const dashboardRequest = controller.capture(bearerHeaders())

  assert.equal(controller.handle(dashboardRequest, 401), true)
  assert.equal(controller.handle(dashboardRequest, 401), false)
  assert.deepEqual(rejectedTokens, ['token-one'])
})

test('Dashboard and Documents requests share the same 401 handler', () => {
  const controller = createUnauthorizedResponseController()
  const rejectedTokens = []
  controller.register((accessToken) => rejectedTokens.push(accessToken))

  const dashboardRequest = controller.capture(bearerHeaders('dashboard-token'))
  const documentListRequest = controller.capture(bearerHeaders('document-token'))
  const uploadRequest = controller.capture(bearerHeaders('upload-token'))

  assert.equal(controller.handle(dashboardRequest, 401), true)
  assert.equal(controller.handle(documentListRequest, 401), true)
  assert.equal(controller.handle(uploadRequest, 401), true)
  assert.deepEqual(rejectedTokens, [
    'dashboard-token',
    'document-token',
    'upload-token',
  ])
})

test('403 and server failures never clear the session', () => {
  const controller = createUnauthorizedResponseController()
  let logoutCount = 0
  controller.register(() => { logoutCount += 1 })

  const request = controller.capture(bearerHeaders())
  assert.equal(controller.handle(request, 403), false)
  assert.equal(controller.handle(request, 500), false)
  assert.equal(controller.handle(request, 503), false)
  assert.equal(logoutCount, 0)
})

test('a public or aborted request has no captured authentication session', () => {
  const controller = createUnauthorizedResponseController()
  let logoutCount = 0
  controller.register(() => { logoutCount += 1 })

  assert.equal(controller.capture(new Headers()), null)
  assert.equal(controller.handle(null, 401), false)
  assert.equal(logoutCount, 0)
})

test('a stale 401 cannot clear a newly registered login session', () => {
  const controller = createUnauthorizedResponseController()
  const events = []
  const unregisterOld = controller.register(() => events.push('old-cleared'))
  const staleRequest = controller.capture(bearerHeaders('same-jwt-value'))

  const unregisterNew = controller.register(() => events.push('new-cleared'))
  const currentRequest = controller.capture(bearerHeaders('same-jwt-value'))

  assert.equal(controller.handle(staleRequest, 401), false)
  assert.equal(controller.handle(currentRequest, 401), true)
  assert.deepEqual(events, ['new-cleared'])

  unregisterOld()
  unregisterNew()
})

test('re-registering after a 401 supports login without a redirect loop', () => {
  const controller = createUnauthorizedResponseController()
  const events = []
  let unregister = null
  unregister = controller.register(() => {
    events.push('first-session-cleared')
    unregister()
  })

  const expiredRequest = controller.capture(bearerHeaders('expired-token'))
  assert.equal(controller.handle(expiredRequest, 401), true)

  controller.register(() => events.push('new-session-cleared'))
  const loginEndpointRequest = controller.capture(new Headers())
  assert.equal(controller.handle(loginEndpointRequest, 401), false)
  assert.deepEqual(events, ['first-session-cleared'])
})
