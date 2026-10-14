import assert from 'node:assert/strict'
import { File as NodeFile } from 'node:buffer'
import test from 'node:test'

import apiClient, {
  ApiHttpError,
  ApiNetworkError,
} from '../src/services/apiClient.js'
import {
  deleteDocument,
  downloadDocument,
  getDocumentDetail,
  getDocumentRagStatus,
  getDocumentStatus,
  getDocuments,
  indexDocument,
  processDocument,
  uploadDocument,
  viewDocumentPdf,
} from '../src/services/documentService.js'


if (typeof globalThis.File === 'undefined') {
  globalThis.File = NodeFile
}

function createFile() {
  return new File(['%PDF-test'], 'notes.pdf', { type: 'application/pdf' })
}

function emptyDocumentPage() {
  return {
    items: [],
    page: 1,
    page_size: 10,
    total: 0,
    total_pages: 0,
  }
}

test('getDocuments sends an authenticated GET and returns the API response', async (context) => {
  const response = {
    items: [{ id: 7, title: 'Ghi chú', file_type: 'PDF' }],
    page: 2,
    page_size: 25,
    total: 26,
    total_pages: 2,
  }
  let capturedRequest
  context.mock.method(apiClient, 'get', async (...args) => {
    capturedRequest = args
    return response
  })

  const result = await getDocuments({
    accessToken: 'header.payload.signature',
    page: 2,
    pageSize: 25,
  })

  assert.equal(result, response)
  assert.equal(capturedRequest[0], '/documents?page=2&page_size=25')
  assert.deepEqual(capturedRequest[1].headers, {
    Authorization: 'Bearer header.payload.signature',
  })
  assert.equal(capturedRequest[0].includes('header.payload.signature'), false)
  assert.equal(capturedRequest[0].includes('user_id'), false)
})

test('document detail, PDF view, and download use authenticated owner-scoped endpoints', async (context) => {
  const detail = { id: 7, title: 'Bài giảng', file_type: 'PDF' }
  const blob = new Blob(['%PDF-test'], { type: 'application/pdf' })
  const getCalls = []
  const blobCalls = []
  context.mock.method(apiClient, 'get', async (...args) => {
    getCalls.push(args)
    return detail
  })
  context.mock.method(apiClient, 'getBlob', async (...args) => {
    blobCalls.push(args)
    return blob
  })
  const controller = new AbortController()

  assert.equal(await getDocumentDetail(7, {
    accessToken: 'header.payload.signature',
    signal: controller.signal,
  }), detail)
  assert.equal(await viewDocumentPdf(7, {
    accessToken: 'header.payload.signature',
    signal: controller.signal,
  }), blob)
  assert.equal(await downloadDocument(7, {
    accessToken: 'header.payload.signature',
    signal: controller.signal,
  }), blob)

  assert.equal(getCalls[0][0], '/documents/7')
  assert.equal(blobCalls[0][0], '/documents/7/view')
  assert.equal(blobCalls[1][0], '/documents/7/download')
  for (const [, options] of [...getCalls, ...blobCalls]) {
    assert.deepEqual(options.headers, {
      Authorization: 'Bearer header.payload.signature',
    })
    assert.equal(options.signal, controller.signal)
  }
  assert.equal(blobCalls.some(([path]) => path.includes('header.payload.signature')), false)
})

test('deleteDocument sends one authenticated DELETE and accepts an empty 204 response', async (context) => {
  const controller = new AbortController()
  let capturedRequest
  context.mock.method(apiClient, 'delete', async (...args) => {
    capturedRequest = args
    return null
  })

  const result = await deleteDocument(7, {
    accessToken: 'header.payload.signature',
    signal: controller.signal,
  })

  assert.equal(result, null)
  assert.equal(capturedRequest[0], '/documents/7')
  assert.deepEqual(capturedRequest[1].headers, {
    Authorization: 'Bearer header.payload.signature',
  })
  assert.equal(capturedRequest[1].signal, controller.signal)
  assert.equal(capturedRequest[0].includes('header.payload.signature'), false)
  assert.equal(capturedRequest[0].includes('user_id'), false)
})

for (const status of [401, 404, 409, 500, 503]) {
  test(`deleteDocument preserves HTTP ${status} errors`, async (context) => {
    const error = new ApiHttpError('Request failed', {
      status,
      statusText: 'Error',
      data: { detail: 'Request failed' },
    })
    context.mock.method(apiClient, 'delete', async () => { throw error })

    await assert.rejects(
      deleteDocument(7, { accessToken: 'token' }),
      (received) => received === error,
    )
  })
}

test('deleteDocument preserves network errors and validates input before requesting', async (context) => {
  const networkError = new ApiNetworkError('Network unavailable')
  let requestCount = 0
  context.mock.method(apiClient, 'delete', async () => {
    requestCount += 1
    throw networkError
  })

  await assert.rejects(
    deleteDocument(7, { accessToken: 'token' }),
    (received) => received === networkError,
  )
  for (const documentId of [0, -1, 1.5, '7', true]) {
    assert.throws(() => deleteDocument(documentId, { accessToken: 'token' }), TypeError)
  }
  for (const accessToken of [undefined, '', '   ', ' token ']) {
    assert.throws(() => deleteDocument(7, { accessToken }), TypeError)
  }
  assert.equal(requestCount, 1)
})

test('document file services reject invalid input before requesting', () => {
  for (const operation of [getDocumentDetail, viewDocumentPdf, downloadDocument]) {
    assert.throws(() => operation(0, { accessToken: 'token' }), TypeError)
    assert.throws(() => operation(1, { accessToken: '' }), TypeError)
    assert.throws(() => operation(1, { accessToken: ' token ' }), TypeError)
  }
})

for (const status of [400, 401, 404, 500]) {
  test(`document Blob services preserve HTTP ${status} errors`, async (context) => {
    const error = new ApiHttpError('Request failed', {
      status,
      statusText: 'Error',
      data: { detail: 'Request failed' },
    })
    context.mock.method(apiClient, 'getBlob', async () => { throw error })

    await assert.rejects(
      viewDocumentPdf(1, { accessToken: 'token' }),
      (received) => received === error,
    )
    await assert.rejects(
      downloadDocument(1, { accessToken: 'token' }),
      (received) => received === error,
    )
  })
}

test('getDocuments trims and safely encodes search', async (context) => {
  let capturedPath
  context.mock.method(apiClient, 'get', async (path) => {
    capturedPath = path
    return emptyDocumentPage()
  })

  await getDocuments({
    accessToken: 'token',
    search: '  AI & học máy  ',
  })

  const url = new URL(capturedPath, 'https://frontend.test')
  assert.equal(url.searchParams.get('search'), 'AI & học máy')
  assert.match(capturedPath, /search=AI\+%26\+h%E1%BB%8Dc\+m%C3%A1y/)
  assert.equal(capturedPath.includes('search=++AI'), false)
})

test('getDocuments normalizes file type and omits empty optional filters', async (context) => {
  const capturedPaths = []
  context.mock.method(apiClient, 'get', async (path) => {
    capturedPaths.push(path)
    return emptyDocumentPage()
  })

  await getDocuments({ accessToken: 'token', fileType: 'docx' })
  await getDocuments({ accessToken: 'token', search: '   ', fileType: '' })

  assert.equal(
    new URL(capturedPaths[0], 'https://frontend.test').searchParams.get('file_type'),
    'DOCX',
  )
  assert.equal(capturedPaths[1], '/documents?page=1&page_size=10')
})

test('getDocuments preserves an empty list response', async (context) => {
  const response = emptyDocumentPage()
  context.mock.method(apiClient, 'get', async () => response)

  const result = await getDocuments({ accessToken: 'token' })

  assert.equal(result, response)
  assert.deepEqual(result, emptyDocumentPage())
})

for (const status of [401, 422]) {
  test(`getDocuments preserves HTTP ${status} errors`, async (context) => {
    const error = new ApiHttpError('Request failed', {
      status,
      statusText: 'Error',
      data: { detail: 'Request failed' },
    })
    context.mock.method(apiClient, 'get', async () => {
      throw error
    })

    await assert.rejects(
      getDocuments({ accessToken: 'token' }),
      (received) => received === error,
    )
  })
}

test('getDocuments preserves network errors', async (context) => {
  const error = new ApiNetworkError('Network unavailable')
  context.mock.method(apiClient, 'get', async () => {
    throw error
  })

  await assert.rejects(
    getDocuments({ accessToken: 'token' }),
    (received) => received === error,
  )
})

test('getDocuments forwards AbortSignal and preserves cancellation', async (context) => {
  const controller = new AbortController()
  const abortError = new DOMException('Request aborted', 'AbortError')
  context.mock.method(apiClient, 'get', async (path, options) => {
    assert.equal(options.signal, controller.signal)
    throw abortError
  })

  await assert.rejects(
    getDocuments({
      accessToken: 'token',
      signal: controller.signal,
    }),
    (received) => received === abortError && received.name === 'AbortError',
  )
})

test('getDocuments validates inputs before requesting', (context) => {
  let requestCount = 0
  context.mock.method(apiClient, 'get', async () => {
    requestCount += 1
    return emptyDocumentPage()
  })

  const invalidInputs = [
    {},
    { accessToken: '' },
    { accessToken: ' token ' },
    { accessToken: 'token', page: 0 },
    { accessToken: 'token', page: 1.5 },
    { accessToken: 'token', pageSize: 0 },
    { accessToken: 'token', pageSize: 101 },
    { accessToken: 'token', pageSize: 1.5 },
    { accessToken: 'token', search: null },
    { accessToken: 'token', search: ` ${'a'.repeat(256)} ` },
    { accessToken: 'token', fileType: null },
    { accessToken: 'token', fileType: 'EXE' },
    { accessToken: 'token', fileType: 'TXT' },
    { accessToken: 'token', fileType: ' pdf ' },
  ]

  for (const input of invalidInputs) {
    assert.throws(() => getDocuments(input), TypeError)
  }
  assert.equal(requestCount, 0)
})

test('getDocuments does not access browser storage', async (context) => {
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
  context.mock.method(apiClient, 'get', async () => emptyDocumentPage())

  await getDocuments({ accessToken: 'token' })

  assert.equal(storageAccessed, false)
})

test('uploadDocument sends multipart metadata and returns the API response', async (context) => {
  const file = createFile()
  const controller = new AbortController()
  const metadata = {
    id: 7,
    title: 'Ghi chú',
    original_filename: 'notes.pdf',
    file_type: 'PDF',
    mime_type: 'application/pdf',
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

test('uploadDocument accepts DOCX files', async (context) => {
  const file = new File(['docx'], 'notes.docx', {
    type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  })
  let capturedFile
  context.mock.method(apiClient, 'postForm', async (path, formData) => {
    capturedFile = formData.get('file')
    return { id: 8, file_type: 'DOCX' }
  })

  const result = await uploadDocument({
    file,
    accessToken: 'header.payload.signature',
  })

  assert.equal(capturedFile, file)
  assert.equal(result.file_type, 'DOCX')
})

test('uploadDocument rejects new TXT files before requesting', (context) => {
  let requestCount = 0
  context.mock.method(apiClient, 'postForm', async () => {
    requestCount += 1
  })

  const txtFile = new File(['legacy text'], 'notes.txt', { type: 'text/plain' })

  assert.throws(
    () => uploadDocument({
      file: txtFile,
      accessToken: 'header.payload.signature',
    }),
    (error) => error instanceof TypeError
      && error.message === 'Chỉ hỗ trợ tải lên file PDF hoặc DOCX.',
  )
  assert.equal(requestCount, 0)
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

for (const status of [400, 401, 413, 415]) {
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

test('processDocument sends an authenticated POST without a request body', async (context) => {
  const controller = new AbortController()
  const response = { document_id: 7, status: 'READY', chunk_count: 2 }
  let capturedRequest
  context.mock.method(apiClient, 'post', async (...args) => {
    capturedRequest = args
    return response
  })

  const result = await processDocument(7, {
    accessToken: 'header.payload.signature',
    signal: controller.signal,
  })

  assert.equal(result, response)
  assert.equal(capturedRequest[0], '/documents/7/process')
  assert.equal(capturedRequest[1], undefined)
  assert.deepEqual(capturedRequest[2].headers, {
    Authorization: 'Bearer header.payload.signature',
  })
  assert.equal(capturedRequest[2].signal, controller.signal)
  assert.equal(capturedRequest[0].includes('header.payload.signature'), false)
  assert.equal(capturedRequest[0].includes('user_id'), false)
})

test('getDocumentStatus sends an authenticated GET', async (context) => {
  const controller = new AbortController()
  const response = { document_id: 9, status: 'FAILED', chunk_count: 0 }
  let capturedRequest
  context.mock.method(apiClient, 'get', async (...args) => {
    capturedRequest = args
    return response
  })

  const result = await getDocumentStatus(9, {
    accessToken: 'header.payload.signature',
    signal: controller.signal,
  })

  assert.equal(result, response)
  assert.equal(capturedRequest[0], '/documents/9/status')
  assert.deepEqual(capturedRequest[1].headers, {
    Authorization: 'Bearer header.payload.signature',
  })
  assert.equal(capturedRequest[1].signal, controller.signal)
  assert.equal(capturedRequest[0].includes('header.payload.signature'), false)
})

test('processing services validate documentId and accessToken before requesting', (context) => {
  let postCount = 0
  let getCount = 0
  context.mock.method(apiClient, 'post', async () => { postCount += 1 })
  context.mock.method(apiClient, 'get', async () => { getCount += 1 })

  for (const documentId of [0, -1, 1.5, '1', true]) {
    assert.throws(
      () => processDocument(documentId, { accessToken: 'token' }),
      TypeError,
    )
    assert.throws(
      () => getDocumentStatus(documentId, { accessToken: 'token' }),
      TypeError,
    )
  }
  for (const accessToken of [undefined, '', '   ', ' token ']) {
    assert.throws(() => processDocument(1, { accessToken }), TypeError)
    assert.throws(() => getDocumentStatus(1, { accessToken }), TypeError)
  }
  assert.equal(postCount, 0)
  assert.equal(getCount, 0)
})

for (const status of [401, 404, 409, 422, 500]) {
  test(`processDocument preserves HTTP ${status} errors`, async (context) => {
    const error = new ApiHttpError('Request failed', {
      status,
      statusText: 'Error',
      data: { detail: 'Request failed' },
    })
    context.mock.method(apiClient, 'post', async () => { throw error })

    await assert.rejects(
      processDocument(1, { accessToken: 'token' }),
      (received) => received === error,
    )
  })
}

test('processing services preserve network errors and AbortError', async (context) => {
  const networkError = new ApiNetworkError('Network unavailable')
  const abortError = new DOMException('Request aborted', 'AbortError')
  context.mock.method(apiClient, 'post', async () => { throw networkError })
  context.mock.method(apiClient, 'get', async () => { throw abortError })

  await assert.rejects(
    processDocument(1, { accessToken: 'token' }),
    (received) => received === networkError,
  )
  await assert.rejects(
    getDocumentStatus(1, { accessToken: 'token' }),
    (received) => received === abortError && received.name === 'AbortError',
  )
})

test('processing services do not access browser storage', async (context) => {
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
  context.mock.method(apiClient, 'post', async () => ({ document_id: 1 }))
  context.mock.method(apiClient, 'get', async () => ({ document_id: 1 }))

  await processDocument(1, { accessToken: 'token' })
  await getDocumentStatus(1, { accessToken: 'token' })
  await indexDocument(1, { accessToken: 'token' })
  await getDocumentRagStatus(1, { accessToken: 'token' })

  assert.equal(storageAccessed, false)
})

test('indexDocument sends an authenticated POST without a request body', async (context) => {
  const controller = new AbortController()
  const response = {
    document_id: 7,
    rag_status: 'READY',
    vector_count: 2,
    indexed_at: '2026-10-12T12:00:00Z',
  }
  let capturedRequest
  context.mock.method(apiClient, 'post', async (...args) => {
    capturedRequest = args
    return response
  })

  const result = await indexDocument(7, {
    accessToken: 'header.payload.signature',
    signal: controller.signal,
  })

  assert.equal(result, response)
  assert.equal(capturedRequest[0], '/documents/7/index')
  assert.equal(capturedRequest[1], undefined)
  assert.deepEqual(capturedRequest[2].headers, {
    Authorization: 'Bearer header.payload.signature',
  })
  assert.equal(capturedRequest[2].signal, controller.signal)
  assert.equal(capturedRequest[0].includes('header.payload.signature'), false)
  assert.equal(capturedRequest[0].includes('user_id'), false)
})

test('getDocumentRagStatus sends an authenticated GET', async (context) => {
  const controller = new AbortController()
  const response = {
    document_id: 9,
    status: 'READY',
    rag_status: 'PENDING',
    chunk_count: 2,
    indexed_at: null,
    can_index: true,
  }
  let capturedRequest
  context.mock.method(apiClient, 'get', async (...args) => {
    capturedRequest = args
    return response
  })

  const result = await getDocumentRagStatus(9, {
    accessToken: 'header.payload.signature',
    signal: controller.signal,
  })

  assert.equal(result, response)
  assert.equal(capturedRequest[0], '/documents/9/rag-status')
  assert.deepEqual(capturedRequest[1].headers, {
    Authorization: 'Bearer header.payload.signature',
  })
  assert.equal(capturedRequest[1].signal, controller.signal)
  assert.equal(capturedRequest[0].includes('header.payload.signature'), false)
})

test('RAG services validate documentId and accessToken before requesting', (context) => {
  let postCount = 0
  let getCount = 0
  context.mock.method(apiClient, 'post', async () => { postCount += 1 })
  context.mock.method(apiClient, 'get', async () => { getCount += 1 })

  for (const documentId of [0, -1, 1.5, '1', true]) {
    assert.throws(
      () => indexDocument(documentId, { accessToken: 'token' }),
      TypeError,
    )
    assert.throws(
      () => getDocumentRagStatus(documentId, { accessToken: 'token' }),
      TypeError,
    )
  }
  for (const accessToken of [undefined, '', '   ', ' token ']) {
    assert.throws(() => indexDocument(1, { accessToken }), TypeError)
    assert.throws(() => getDocumentRagStatus(1, { accessToken }), TypeError)
  }
  assert.equal(postCount, 0)
  assert.equal(getCount, 0)
})

for (const status of [401, 404, 409, 500, 503]) {
  test(`indexDocument preserves HTTP ${status} errors`, async (context) => {
    const error = new ApiHttpError('Request failed', {
      status,
      statusText: 'Error',
      data: { detail: 'Request failed' },
    })
    context.mock.method(apiClient, 'post', async () => { throw error })

    await assert.rejects(
      indexDocument(1, { accessToken: 'token' }),
      (received) => received === error,
    )
  })
}

test('RAG services preserve network errors and AbortError', async (context) => {
  const networkError = new ApiNetworkError('Network unavailable')
  const abortError = new DOMException('Request aborted', 'AbortError')
  context.mock.method(apiClient, 'post', async () => { throw networkError })
  context.mock.method(apiClient, 'get', async () => { throw abortError })

  await assert.rejects(
    indexDocument(1, { accessToken: 'token' }),
    (received) => received === networkError,
  )
  await assert.rejects(
    getDocumentRagStatus(1, { accessToken: 'token' }),
    (received) => received === abortError && received.name === 'AbortError',
  )
})
