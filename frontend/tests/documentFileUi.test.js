import assert from 'node:assert/strict'
import test from 'node:test'

import {
  createDocumentObjectUrl,
  revokeDocumentObjectUrl,
  triggerDocumentDownload,
} from '../src/components/documentFileUi.js'


test('PDF object URL can be created and explicitly revoked', () => {
  const calls = []
  const urlApi = {
    createObjectURL(blob) {
      calls.push(['create', blob])
      return 'blob:studymate-view'
    },
    revokeObjectURL(url) {
      calls.push(['revoke', url])
    },
  }
  const blob = new Blob(['pdf'], { type: 'application/pdf' })

  const objectUrl = createDocumentObjectUrl(blob, urlApi)
  revokeDocumentObjectUrl(objectUrl, urlApi)

  assert.equal(objectUrl, 'blob:studymate-view')
  assert.deepEqual(calls, [
    ['create', blob],
    ['revoke', 'blob:studymate-view'],
  ])
})

test('download clicks a temporary link and always revokes its object URL', () => {
  const calls = []
  const link = {
    click() { calls.push('click') },
    remove() { calls.push('remove') },
  }
  const documentObject = {
    createElement(tag) {
      assert.equal(tag, 'a')
      return link
    },
    body: {
      append(element) {
        assert.equal(element, link)
        calls.push('append')
      },
    },
  }
  const urlApi = {
    createObjectURL() {
      calls.push('create')
      return 'blob:studymate-download'
    },
    revokeObjectURL(url) {
      calls.push(`revoke:${url}`)
    },
  }

  triggerDocumentDownload(
    new Blob(['docx']),
    'bài học.docx',
    { urlApi, documentObject },
  )

  assert.equal(link.href, 'blob:studymate-download')
  assert.equal(link.download, 'bài học.docx')
  assert.deepEqual(calls, [
    'create',
    'append',
    'click',
    'remove',
    'revoke:blob:studymate-download',
  ])
})

test('download revokes the object URL even when clicking fails', () => {
  const revoked = []
  const urlApi = {
    createObjectURL: () => 'blob:failed-download',
    revokeObjectURL: (url) => revoked.push(url),
  }
  const link = {
    click() { throw new Error('test click failure') },
    remove() {},
  }
  const documentObject = {
    createElement: () => link,
    body: { append() {} },
  }

  assert.throws(
    () => triggerDocumentDownload(
      new Blob(['pdf']),
      'lesson.pdf',
      { urlApi, documentObject },
    ),
    /test click failure/,
  )
  assert.deepEqual(revoked, ['blob:failed-download'])
})
