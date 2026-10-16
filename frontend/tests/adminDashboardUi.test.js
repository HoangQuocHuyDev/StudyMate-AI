import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

import { ApiHttpError, ApiNetworkError } from '../src/services/apiClient.js'
import {
  ADMIN_NAVIGATION,
  ADMIN_STATISTICS,
  adminDashboardReducer,
  getAdminActivityChart,
  getAdminDashboardErrorMessage,
  getAdminRecentActivityPresentation,
  getAdminStatisticCards,
  initialAdminDashboardState,
  validateAdminActivityResponse,
  validateAdminOverviewResponse,
  validateAdminRecentActivitiesResponse,
} from '../src/components/admin/adminDashboardUi.js'
import { getRouteRedirect } from '../src/navigation/routePolicy.js'


const overview = {
  user_count: 12,
  document_count: 8,
  chat_session_count: 21,
  processing_document_count: 2,
}

const zeroActivity = {
  timezone: 'UTC',
  days: 7,
  items: Array.from({ length: 7 }, (_, index) => ({
    date: `2026-10-${String(index + 9).padStart(2, '0')}`,
    registered_user_count: 0,
    uploaded_document_count: 0,
    created_chat_session_count: 0,
    generated_summary_count: 0,
  })),
}

test('admin overview maps the four live API statistics in stable order', () => {
  assert.deepEqual(
    ADMIN_STATISTICS.map(({ key, label }) => ({ key, label })),
    [
      { key: 'user_count', label: 'Tổng người dùng' },
      { key: 'document_count', label: 'Tổng tài liệu' },
      { key: 'chat_session_count', label: 'Tổng cuộc hội thoại' },
      { key: 'processing_document_count', label: 'Tài liệu đang xử lý' },
    ],
  )
  assert.deepEqual(
    getAdminStatisticCards(overview).map(({ key, value }) => ({ key, value })),
    [
      { key: 'user_count', value: 12 },
      { key: 'document_count', value: 8 },
      { key: 'chat_session_count', value: 21 },
      { key: 'processing_document_count', value: 2 },
    ],
  )
})

test('admin overview preserves real zero values and rejects fabricated omissions', () => {
  const zero = {
    user_count: 0,
    document_count: 0,
    chat_session_count: 0,
    processing_document_count: 0,
  }
  assert.deepEqual(validateAdminOverviewResponse(zero), zero)
  assert.ok(getAdminStatisticCards(zero).every(({ value }) => value === 0))
  assert.throws(() => validateAdminOverviewResponse({}), TypeError)
  assert.throws(() => validateAdminOverviewResponse({ ...zero, user_count: -1 }), TypeError)
})

test('activity chart validates seven UTC days and keeps zero bars truthful', () => {
  const validated = validateAdminActivityResponse(zeroActivity)
  const chart = getAdminActivityChart(validated)
  assert.equal(chart.items.length, 7)
  assert.equal(chart.maximum, 0)
  assert.ok(chart.items.every((day) => day.series.every((series) => (
    series.value === 0 && series.height === 0
  ))))

  const populated = structuredClone(zeroActivity)
  populated.items[6].uploaded_document_count = 4
  const populatedChart = getAdminActivityChart(populated)
  assert.equal(populatedChart.maximum, 4)
  assert.equal(populatedChart.items[6].series[1].height, 100)
})

test('activity response rejects missing days, duplicate dates and invalid counts', () => {
  assert.throws(() => validateAdminActivityResponse({ ...zeroActivity, items: [] }), TypeError)
  const duplicate = structuredClone(zeroActivity)
  duplicate.items[1].date = duplicate.items[0].date
  assert.throws(() => validateAdminActivityResponse(duplicate), TypeError)
  const negative = structuredClone(zeroActivity)
  negative.items[0].registered_user_count = -1
  assert.throws(() => validateAdminActivityResponse(negative), TypeError)
})

test('recent activity uses only identifiers supplied by the API', () => {
  const response = {
    items: [{
      activity_type: 'CHAT_SESSION_CREATED',
      occurred_at: '2026-10-15T08:00:00Z',
      resource_id: 45,
      user_id: 2,
      document_id: 12,
      session_id: 45,
      file_type: 'PDF',
    }],
    limit: 10,
    is_audit_log: false,
  }
  const validated = validateAdminRecentActivitiesResponse(response)
  const presentation = getAdminRecentActivityPresentation(validated.items[0])
  assert.equal(presentation.title, 'Cuộc hội thoại #45 được tạo')
  assert.equal(presentation.detail, 'Tài liệu #12 · Người dùng #2')
  assert.equal(JSON.stringify(presentation).includes('Nguyễn'), false)
})

test('recent activity requires the derived-data marker and known safe types', () => {
  assert.throws(() => validateAdminRecentActivitiesResponse({
    items: [], limit: 10, is_audit_log: true,
  }), TypeError)
  assert.throws(() => validateAdminRecentActivitiesResponse({
    items: [{
      activity_type: 'PASSWORD_CHANGED',
      occurred_at: '2026-10-15T08:00:00Z',
      resource_id: 1,
      user_id: 1,
      document_id: null,
      session_id: null,
      file_type: null,
    }],
    limit: 10,
    is_audit_log: false,
  }), TypeError)
})

test('admin reducer ignores stale responses and keeps valid data on refresh failure', () => {
  let state = adminDashboardReducer(initialAdminDashboardState, {
    type: 'request-started', section: 'overview', requestId: 2,
  })
  state = adminDashboardReducer(state, {
    type: 'request-succeeded', section: 'overview', requestId: 1, data: { user_count: 99 },
  })
  assert.equal(state.overview.data, null)
  state = adminDashboardReducer(state, {
    type: 'request-succeeded', section: 'overview', requestId: 2, data: overview,
  })
  state = adminDashboardReducer(state, {
    type: 'request-started', section: 'overview', requestId: 3,
  })
  state = adminDashboardReducer(state, {
    type: 'request-failed', section: 'overview', requestId: 3, error: 'Mất kết nối',
  })
  assert.equal(state.overview.data, overview)
  assert.equal(state.overview.status, 'error')
})

test('admin errors distinguish expired sessions, permissions and server failures', () => {
  const createError = (status) => new ApiHttpError('hidden', {
    status, statusText: 'Failure', data: { detail: 'hidden' },
  })
  assert.match(getAdminDashboardErrorMessage(createError(401)), /hết hạn/)
  assert.match(getAdminDashboardErrorMessage(createError(403)), /không có quyền/)
  assert.match(getAdminDashboardErrorMessage(createError(500)), /thử lại/)
  assert.match(getAdminDashboardErrorMessage(new ApiNetworkError('hidden')), /kết nối/)
})

test('admin sidebar contains no fake actions and route remains ADMIN-only', () => {
  assert.deepEqual(ADMIN_NAVIGATION.map(({ id }) => id), ['overview', 'users', 'documents'])
  assert.equal(getRouteRedirect({
    currentPath: '/admin', isAuthenticated: true, isLoading: false, role: 'ADMIN',
  }), null)
  assert.equal(getRouteRedirect({
    currentPath: '/admin', isAuthenticated: true, isLoading: false, role: 'USER',
  }), '/')
})

test('admin dashboard source no longer exposes legacy mock management data', async () => {
  const source = await readFile(
    new URL('../src/components/admin/AdminDashboard.jsx', import.meta.url),
    'utf8',
  )

  assert.equal(source.includes('initialUsers'), false)
  assert.equal(source.includes('initialDocuments'), false)
  assert.equal(source.includes('toggleUserStatus'), false)
  assert.equal(source.includes('deleteDocument'), false)
})
