import assert from 'node:assert/strict'
import test from 'node:test'

import {
  buildDocumentSearchUrl,
  getInitialDocumentSearchState,
  getDocumentSearchValidationMessage,
  normalizeDocumentSearchTerm,
  parseDocumentSearch,
  shouldCommitDocumentSearch,
} from '../src/components/documentSearchUrl.js'

test('header search trims and safely encodes Vietnamese and reserved characters', () => {
  const destination = buildDocumentSearchUrl({
    keyword: '  Trí tuệ % _ & ? # /  ',
    currentPath: '/',
  })
  assert.equal(parseDocumentSearch(new URL(destination, 'https://example.test').search), 'Trí tuệ % _ & ? # /')
  assert.match(destination, /%25/)
  assert.match(destination, /%26/)
  assert.match(destination, /%23/)
  assert.match(destination, /%2F/)
})

test('search on Documents preserves other parameters and resets an existing page', () => {
  assert.equal(
    buildDocumentSearchUrl({
      keyword: 'AI',
      currentPath: '/documents',
      currentSearch: '?file_type=PDF&page=4',
    }),
    '/documents?file_type=PDF&page=1&search=AI',
  )
})

test('empty search removes only the search parameter', () => {
  assert.equal(
    buildDocumentSearchUrl({
      keyword: '   ',
      currentPath: '/documents',
      currentSearch: '?search=AI&file_type=DOCX',
    }),
    '/documents?file_type=DOCX',
  )
})

test('search longer than 255 characters is rejected', () => {
  const value = 'a'.repeat(256)
  assert.match(getDocumentSearchValidationMessage(value), /255/)
  assert.throws(() => buildDocumentSearchUrl({ keyword: value }), RangeError)
  assert.equal(getDocumentSearchValidationMessage('a'.repeat(255)), '')
})

test('URL parsing is normalized and capped defensively', () => {
  assert.equal(parseDocumentSearch('?search=%20AI%20'), 'AI')
  assert.equal(parseDocumentSearch(`?search=${'x'.repeat(300)}`).length, 255)
  assert.equal(normalizeDocumentSearchTerm('  RAG  '), 'RAG')
})

test('Documents initializes both input and API search from an F5 URL', () => {
  assert.deepEqual(
    getInitialDocumentSearchState('?search=Python'),
    { query: 'Python', debouncedSearch: 'Python' },
  )
  assert.deepEqual(
    getInitialDocumentSearchState('?search=Tr%C3%AD+tu%E1%BB%87+nh%C3%A2n+t%E1%BA%A1o'),
    {
      query: 'Trí tuệ nhân tạo',
      debouncedSearch: 'Trí tuệ nhân tạo',
    },
  )
})

test('debounced search cannot overwrite a newer Header or Back/Forward location', () => {
  assert.equal(shouldCommitDocumentSearch({
    query: 'old',
    urlSearch: '?search=initial',
    scheduledLocationKey: '/documents?search=initial',
    currentLocationKey: '/documents?search=new',
  }), false)
  assert.equal(shouldCommitDocumentSearch({
    query: 'new',
    urlSearch: '?search=initial',
    scheduledLocationKey: '/documents?search=initial',
    currentLocationKey: '/documents?search=initial',
  }), true)
  assert.equal(shouldCommitDocumentSearch({
    query: 'AI',
    urlSearch: '?search=AI',
    scheduledLocationKey: '/documents?search=AI',
    currentLocationKey: '/documents?search=AI',
  }), false)
})
