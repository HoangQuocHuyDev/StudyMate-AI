import assert from 'node:assert/strict'
import test from 'node:test'

import apiClient, { ApiHttpError } from '../src/services/apiClient.js'
import {
  getAdminDashboardActivity,
  getAdminDashboardOverview,
  getAdminRecentActivities,
} from '../src/services/adminDashboardService.js'


test('Admin Dashboard services call exact endpoints with the in-memory JWT', async (context) => {
  const controller = new AbortController()
  const requests = []
  context.mock.method(apiClient, 'get', async (...args) => {
    requests.push(args)
    return { ok: true }
  })
  const options = {
    accessToken: 'header.payload.signature',
    signal: controller.signal,
  }

  await getAdminDashboardOverview(options)
  await getAdminDashboardActivity(options)
  await getAdminRecentActivities({ ...options, limit: 10 })

  assert.deepEqual(requests.map(([path]) => path), [
    '/admin/dashboard/overview',
    '/admin/dashboard/activity',
    '/admin/dashboard/recent-activities?limit=10',
  ])
  for (const [path, requestOptions] of requests) {
    assert.deepEqual(requestOptions.headers, {
      Authorization: 'Bearer header.payload.signature',
    })
    assert.equal(requestOptions.signal, controller.signal)
    assert.equal(path.includes('header.payload.signature'), false)
  }
})

test('Admin Dashboard services reject invalid tokens and limits before fetch', (context) => {
  const get = context.mock.method(apiClient, 'get', async () => ({}))
  for (const accessToken of [undefined, '', ' token ', 123]) {
    assert.throws(() => getAdminDashboardOverview({ accessToken }), TypeError)
  }
  for (const limit of [0, 51, 1.5, '10']) {
    assert.throws(() => getAdminRecentActivities({ accessToken: 'token', limit }), TypeError)
  }
  assert.equal(get.mock.callCount(), 0)
})

for (const status of [401, 403, 500]) {
  test(`Admin Dashboard services preserve HTTP ${status} for UI handling`, async (context) => {
    const error = new ApiHttpError('hidden', {
      status, statusText: 'Failure', data: { detail: 'hidden' },
    })
    context.mock.method(apiClient, 'get', async () => { throw error })
    await assert.rejects(
      getAdminDashboardOverview({ accessToken: 'token' }),
      (caught) => caught === error,
    )
  })
}

