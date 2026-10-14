import assert from 'node:assert/strict'
import test from 'node:test'

import {
  createLocationSnapshot,
  locationToString,
  locationsEqual,
  navigateBrowserLocation,
  normalizePath,
  subscribeToBrowserLocation,
} from '../src/navigation/location.js'

function fakeWindow(path = '/documents?search=AI') {
  const url = new URL(path, 'https://studymate.test')
  const listeners = new Map()
  const calls = []
  return {
    location: url,
    history: {
      pushState: (...args) => calls.push(['pushState', ...args]),
      replaceState: (...args) => calls.push(['replaceState', ...args]),
    },
    addEventListener: (name, listener) => listeners.set(name, listener),
    removeEventListener: (name, listener) => {
      if (listeners.get(name) === listener) listeners.delete(name)
    },
    calls,
    listeners,
  }
}

test('location snapshot preserves pathname, search, and hash', () => {
  const location = createLocationSnapshot({
    pathname: '/documents/',
    search: 'search=AI',
    hash: 'results',
  })
  assert.deepEqual(location, {
    pathname: '/documents',
    search: '?search=AI',
    hash: '#results',
  })
  assert.equal(locationToString(location), '/documents?search=AI#results')
})

test('query-only and hash-only navigation are observable location changes', () => {
  const first = createLocationSnapshot({ pathname: '/documents', search: '?search=AI' })
  const second = createLocationSnapshot({ pathname: '/documents', search: '?search=RAG' })
  const third = createLocationSnapshot({ pathname: '/documents', search: '?search=RAG', hash: '#list' })

  assert.equal(locationsEqual(first, second), false)
  assert.equal(locationsEqual(second, third), false)
  assert.equal(locationsEqual(second, createLocationSnapshot(second)), true)
  assert.equal(normalizePath('/'), '/')
})

test('query-only navigation uses push or replace and skips duplicate history entries', () => {
  const browser = fakeWindow()
  const pushed = navigateBrowserLocation(browser, '/documents?search=RAG')
  assert.equal(pushed.changed, true)
  assert.deepEqual(browser.calls[0], ['pushState', null, '', '/documents?search=RAG'])

  const replacedBrowser = fakeWindow()
  navigateBrowserLocation(replacedBrowser, '/documents?search=RAG', { replace: true })
  assert.equal(replacedBrowser.calls[0][0], 'replaceState')

  const unchangedBrowser = fakeWindow()
  const unchanged = navigateBrowserLocation(unchangedBrowser, '/documents?search=AI')
  assert.equal(unchanged.changed, false)
  assert.equal(unchangedBrowser.calls.length, 0)
})

test('popstate subscription reports search changes on the same pathname and cleans up', () => {
  const browser = fakeWindow()
  const received = []
  const unsubscribe = subscribeToBrowserLocation(browser, (location) => received.push(location))

  browser.location = new URL('/documents?search=RAG', browser.location.origin)
  browser.listeners.get('popstate')()
  assert.equal(received[0].pathname, '/documents')
  assert.equal(received[0].search, '?search=RAG')

  unsubscribe()
  assert.equal(browser.listeners.has('popstate'), false)
})
