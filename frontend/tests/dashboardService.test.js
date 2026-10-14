import assert from 'node:assert/strict'
import test from 'node:test'

import apiClient, { ApiHttpError, ApiNetworkError } from '../src/services/apiClient.js'
import { getDashboardOverview } from '../src/services/dashboardService.js'


test('getDashboardOverview sends JWT to the exact authenticated endpoint', async (context) => {
  const response = {
    document_count: 4,
    ready_document_count: 2,
    summary_count: 3,
    chat_session_count: 5,
  }
  const controller = new AbortController()
  let capturedRequest
  context.mock.method(apiClient, 'get', async (...args) => {
    capturedRequest = args
    return response
  })

  const result = await getDashboardOverview({
    accessToken: 'header.payload.signature',
    signal: controller.signal,
  })

  assert.equal(result, response)
  assert.equal(capturedRequest[0], '/dashboard/overview')
  assert.deepEqual(capturedRequest[1].headers, {
    Authorization: 'Bearer header.payload.signature',
  })
  assert.equal(capturedRequest[1].signal, controller.signal)
  assert.equal(capturedRequest[0].includes('header.payload.signature'), false)
})

test('getDashboardOverview validates token before requesting', (context) => {
  const get = context.mock.method(apiClient, 'get', async () => ({}))
  for (const accessToken of [undefined, '', ' token ', 123]) {
    assert.throws(() => getDashboardOverview({ accessToken }), TypeError)
  }
  assert.equal(get.mock.callCount(), 0)
})

for (const status of [401, 500]) {
  test(`getDashboardOverview preserves HTTP ${status} for safe UI mapping`, async (context) => {
    const error = new ApiHttpError('hidden', {
      status,
      statusText: 'Failure',
      data: { detail: 'hidden' },
    })
    context.mock.method(apiClient, 'get', async () => { throw error })
    await assert.rejects(
      getDashboardOverview({ accessToken: 'token' }),
      (caught) => caught === error,
    )
  })
}

test('getDashboardOverview preserves network and abort errors', async (context) => {
  const networkError = new ApiNetworkError('hidden')
  const get = context.mock.method(apiClient, 'get', async () => {
    throw networkError
  })
  await assert.rejects(
    getDashboardOverview({ accessToken: 'token' }),
    (caught) => caught === networkError,
  )

  const abortError = new DOMException('Aborted', 'AbortError')
  get.mock.mockImplementation(async () => { throw abortError })
  await assert.rejects(
    getDashboardOverview({ accessToken: 'token' }),
    (caught) => caught === abortError,
  )
})
