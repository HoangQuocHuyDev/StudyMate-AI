import assert from 'node:assert/strict'
import { File as NodeFile } from 'node:buffer'
import test from 'node:test'

import apiClient, {
  ApiHttpError,
  ApiNetworkError,
} from '../src/services/apiClient.js'
import { uploadDocument } from '../src/services/documentService.js'


if (typeof globalThis.File === 'undefined') {
  globalThis.File = NodeFile
}

function createFile() {
  return new File(['study material'], 'notes.txt', { type: 'text/plain' })
}

test('uploadDocument sends multipart metadata and returns the API response', async (context) => {
  const file = createFile()
  const controller = new AbortController()
  const metadata = {
    id: 7,
    title: 'Ghi chú',
    original_filename: 'notes.txt',
    file_type: 'TXT',
    mime_type: 'text/plain; charset=utf-8',
    file_size: file.size,
    status: 'UPLOADED',
    created_at: '2026-10-12T10:00:00Z',
  }
  let capturedRequest
  context.mock.method(apiClient, 'postForm', async (...args) => {
    capturedRequest = args
    return metadata
  })

  const result = await uploadDocument({
    file,
    title: '  Ghi chú  ',
    accessToken: 'header.payload.signature',
    signal: controller.signal,
  })

  assert.equal(result, metadata)
  assert.equal(capturedRequest[0], '/documents/upload')
  assert.ok(capturedRequest[1] instanceof FormData)
  assert.equal(capturedRequest[1].get('file'), file)
  assert.equal(capturedRequest[1].get('title'), 'Ghi chú')
  assert.deepEqual(capturedRequest[2].headers, {
    Authorization: 'Bearer header.payload.signature',
  })
  assert.equal(capturedRequest[2].signal, controller.signal)
  assert.equal(new Headers(capturedRequest[2].headers).has('Content-Type'), false)
  assert.equal(capturedRequest[1].has('user_id'), false)
})

test('uploadDocument omits an empty optional title', async (context) => {
  let capturedFormData
  context.mock.method(apiClient, 'postForm', async (path, formData) => {
    capturedFormData = formData
    return { id: 1 }
  })

  await uploadDocument({
    file: createFile(),
    title: '   ',
    accessToken: 'header.payload.signature',
  })

  assert.equal(capturedFormData.has('title'), false)
})

test('uploadDocument validates file, title, and accessToken before requesting', () => {
  const validFile = createFile()

  assert.throws(
    () => uploadDocument({ file: {}, accessToken: 'token' }),
    TypeError,
  )
  assert.throws(
    () => uploadDocument({ file: validFile, title: 42, accessToken: 'token' }),
    TypeError,
  )
  assert.throws(
    () => uploadDocument({ file: validFile, accessToken: '   ' }),
    TypeError,
  )
  assert.throws(
    () => uploadDocument({ file: validFile, accessToken: ' token ' }),
    TypeError,
  )
})

for (const status of [401, 413, 415]) {
  test(`uploadDocument preserves HTTP ${status} errors`, async (context) => {
    const error = new ApiHttpError('Request failed', {
      status,
      statusText: 'Error',
      data: { detail: 'Request failed' },
    })
    context.mock.method(apiClient, 'postForm', async () => {
      throw error
    })

    await assert.rejects(
      uploadDocument({
        file: createFile(),
        accessToken: 'header.payload.signature',
      }),
      (received) => received === error,
    )
  })
}

test('uploadDocument preserves network errors', async (context) => {
  const error = new ApiNetworkError('Network unavailable')
  context.mock.method(apiClient, 'postForm', async () => {
    throw error
  })

  await assert.rejects(
    uploadDocument({
      file: createFile(),
      accessToken: 'header.payload.signature',
    }),
    (received) => received === error,
  )
})

test('uploadDocument forwards AbortSignal and preserves cancellation', async (context) => {
  const controller = new AbortController()
  const abortError = new DOMException('Request aborted', 'AbortError')
  context.mock.method(apiClient, 'postForm', async (path, formData, options) => {
    assert.equal(options.signal, controller.signal)
    throw abortError
  })

  await assert.rejects(
    uploadDocument({
      file: createFile(),
      accessToken: 'header.payload.signature',
      signal: controller.signal,
    }),
    (received) => received === abortError && received.name === 'AbortError',
  )
})

test('uploadDocument does not access browser storage', async (context) => {
  let storageAccessed = false
  const guardedStorage = {
    getItem() { storageAccessed = true },
    setItem() { storageAccessed = true },
  }
  Object.defineProperty(globalThis, 'localStorage', {
    configurable: true,
    value: guardedStorage,
  })
  Object.defineProperty(globalThis, 'sessionStorage', {
    configurable: true,
    value: guardedStorage,
  })
  context.after(() => {
    delete globalThis.localStorage
    delete globalThis.sessionStorage
  })
  context.mock.method(apiClient, 'postForm', async () => ({ id: 1 }))

  await uploadDocument({
    file: createFile(),
    accessToken: 'header.payload.signature',
  })

  assert.equal(storageAccessed, false)
})
