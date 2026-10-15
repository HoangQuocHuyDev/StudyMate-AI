import assert from 'node:assert/strict'
import test from 'node:test'

import {
  buildLoginRedirect,
  getPostLoginRoute,
  getRouteRedirect,
} from '../src/navigation/routePolicy.js'

test('F5 on a protected document search preserves the full internal destination', () => {
  const redirect = getRouteRedirect({
    currentPath: '/documents',
    currentSearch: '?search=Python',
    currentHash: '#results',
    isAuthenticated: false,
    isLoading: false,
    role: undefined,
  })

  assert.equal(
    redirect,
    '/login?return_to=%2Fdocuments%3Fsearch%3DPython%23results',
  )
  assert.equal(
    getPostLoginRoute({
      currentSearch: new URL(redirect, 'https://studymate.test').search,
      role: 'USER',
    }),
    '/documents?search=Python#results',
  )
})

test('authenticated login routing restores the document search URL', () => {
  const currentSearch = '?return_to=%2Fdocuments%3Fsearch%3DPython'
  assert.equal(getRouteRedirect({
    currentPath: '/login',
    currentSearch,
    isAuthenticated: true,
    isLoading: false,
    role: 'USER',
  }), '/documents?search=Python')
})

test('F5 and login restore an authenticated Chat deep-link intact', () => {
  const redirect = getRouteRedirect({
    currentPath: '/chat',
    currentSearch: '?document_id=12&session_id=45',
    currentHash: '',
    isAuthenticated: false,
    isLoading: false,
    role: undefined,
  })
  const loginSearch = new URL(redirect, 'https://studymate.test').search
  assert.equal(
    getPostLoginRoute({ currentSearch: loginSearch, role: 'USER' }),
    '/chat?document_id=12&session_id=45',
  )
})

test('return destination accepts only known internal routes allowed for the role', () => {
  assert.equal(
    getPostLoginRoute({ currentSearch: '?return_to=https%3A%2F%2Fevil.test', role: 'USER' }),
    '/',
  )
  assert.equal(
    getPostLoginRoute({ currentSearch: '?return_to=%2F%2Fevil.test', role: 'USER' }),
    '/',
  )
  assert.equal(
    getPostLoginRoute({ currentSearch: '?return_to=%2Fadmin', role: 'USER' }),
    '/',
  )
  assert.equal(
    getPostLoginRoute({ currentSearch: '?return_to=%2Funknown', role: 'USER' }),
    '/',
  )
})

test('login redirect encodes reserved search characters without losing them', () => {
  const redirect = buildLoginRedirect({
    currentPath: '/documents',
    currentSearch: '?search=C%23+%26+AI',
  })
  const loginSearch = new URL(redirect, 'https://studymate.test').search
  assert.equal(
    getPostLoginRoute({ currentSearch: loginSearch, role: 'USER' }),
    '/documents?search=C%23+%26+AI',
  )
})
