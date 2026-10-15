import assert from 'node:assert/strict'
import test from 'node:test'

import {
  ADMIN_NAVIGATION,
  ADMIN_STATISTICS,
  getAdminStatisticCards,
} from '../src/components/admin/adminDashboardUi.js'
import { getRouteRedirect } from '../src/navigation/routePolicy.js'

test('admin overview defines the four approved statistics in a stable order', () => {
  assert.deepEqual(
    ADMIN_STATISTICS.map(({ key, label }) => ({ key, label })),
    [
      { key: 'user_count', label: 'Tổng người dùng' },
      { key: 'document_count', label: 'Tổng tài liệu' },
      { key: 'chat_session_count', label: 'Tổng cuộc hội thoại' },
      { key: 'processing_document_count', label: 'Tài liệu đang xử lý' },
    ],
  )
})

test('admin overview never substitutes fabricated numbers when no API exists', () => {
  const cards = getAdminStatisticCards()

  assert.equal(cards.length, 4)
  assert.ok(cards.every(({ value }) => value === null))
  assert.ok(cards.every(({ description }) => /Admin API/.test(description)))
})

test('admin sidebar keeps one and only one stable view identifier per item', () => {
  assert.deepEqual(
    ADMIN_NAVIGATION.map(({ id }) => id),
    ['overview', 'users', 'documents'],
  )
  assert.equal(new Set(ADMIN_NAVIGATION.map(({ id }) => id)).size, 3)
})

test('admin route remains available only to an authenticated ADMIN', () => {
  assert.equal(getRouteRedirect({
    currentPath: '/admin',
    isAuthenticated: true,
    isLoading: false,
    role: 'ADMIN',
  }), null)
  assert.equal(getRouteRedirect({
    currentPath: '/admin',
    isAuthenticated: true,
    isLoading: false,
    role: 'USER',
  }), '/')
})
