import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

import {
  MAX_DOCUMENT_UPLOAD_SIZE,
  createDocumentAutoUploadController,
  getDocumentUploadValidationMessage,
  getSingleDocumentUploadFile,
} from '../src/components/documentUploadUi.js'


function file(name = 'bai-giang.pdf', size = 1024) {
  return { name, size }
}

function deferred() {
  let resolve
  let reject
  const promise = new Promise((resolvePromise, rejectPromise) => {
    resolve = resolvePromise
    reject = rejectPromise
  })
  return { promise, resolve, reject }
}

test('file picker selection starts upload immediately and refreshes after success', async () => {
  const controller = createDocumentAutoUploadController()
  const selected = getSingleDocumentUploadFile([file()])
  let uploadCount = 0
  let refreshCount = 0
  let state = 'idle'

  const result = await controller.submit(selected.file, {
    upload: async () => {
      uploadCount += 1
      return { id: 9, title: 'Bài giảng' }
    },
    onStart: () => { state = 'uploading' },
    onSuccess: () => {
      state = 'success'
      refreshCount += 1
    },
  })

  assert.equal(selected.error, null)
  assert.equal(result.status, 'success')
  assert.equal(uploadCount, 1)
  assert.equal(refreshCount, 1)
  assert.equal(state, 'success')
})

test('drop selection uses the same immediate auto-upload path', async () => {
  const controller = createDocumentAutoUploadController()
  const dropped = getSingleDocumentUploadFile([file('giao-trinh.docx')])
  let uploadedFile

  const result = await controller.submit(dropped.file, {
    upload: async (candidate) => {
      uploadedFile = candidate
      return { id: 10 }
    },
  })

  assert.equal(result.status, 'success')
  assert.equal(uploadedFile, dropped.file)
})

test('invalid extension, oversized file, and multiple drop are rejected before upload', async () => {
  const controller = createDocumentAutoUploadController()
  let uploadCount = 0
  const upload = async () => { uploadCount += 1 }

  const txt = file('ghi-chu.txt')
  const oversized = file('giao-trinh.pdf', MAX_DOCUMENT_UPLOAD_SIZE + 1)
  const multiple = getSingleDocumentUploadFile([file(), file('khac.docx')])

  assert.match(getDocumentUploadValidationMessage(txt), /PDF hoặc DOCX/)
  assert.match(getDocumentUploadValidationMessage(oversized), /10 MiB/)
  assert.match(multiple.error, /một file/)
  assert.equal((await controller.submit(txt, { upload })).status, 'invalid')
  assert.equal((await controller.submit(oversized, { upload })).status, 'invalid')
  assert.equal(uploadCount, 0)
})

test('double click or double drop cannot create two concurrent upload requests', async () => {
  const controller = createDocumentAutoUploadController()
  const pending = deferred()
  let uploadCount = 0
  const upload = () => {
    uploadCount += 1
    return pending.promise
  }

  const first = controller.submit(file(), { upload })
  const second = await controller.submit(file(), { upload })

  assert.equal(second.status, 'busy')
  assert.equal(uploadCount, 1)
  pending.resolve({ id: 11 })
  assert.equal((await first).status, 'success')
  assert.equal(controller.isBusy(), false)
})

test('upload failure is reported and releases the guard so the file can be selected again', async () => {
  const controller = createDocumentAutoUploadController()
  const failure = new Error('network detail must stay inside the error mapper')
  let displayedError
  let attempt = 0
  const upload = async () => {
    attempt += 1
    if (attempt === 1) throw failure
    return { id: 12 }
  }

  const failed = await controller.submit(file(), {
    upload,
    onError: (error) => { displayedError = error },
  })
  const retried = await controller.submit(file(), { upload })

  assert.equal(failed.status, 'error')
  assert.equal(displayedError, failure)
  assert.equal(retried.status, 'success')
  assert.equal(attempt, 2)
})

test('invalidating on unmount suppresses late success, error, and settled callbacks', async () => {
  const controller = createDocumentAutoUploadController()
  const pending = deferred()
  const effects = []

  const request = controller.submit(file(), {
    upload: () => pending.promise,
    onSuccess: () => effects.push('success'),
    onError: () => effects.push('error'),
    onSettled: () => effects.push('settled'),
  })
  controller.invalidate()
  pending.resolve({ id: 13 })

  assert.equal((await request).status, 'stale')
  assert.deepEqual(effects, [])
})

test('Documents uses one accessible dropzone for auto-upload and every upload state', async () => {
  const source = await readFile(
    new URL('../src/components/Documents.jsx', import.meta.url),
    'utf8',
  )

  assert.match(source, /void startAutoUpload\(files\)/)
  assert.match(source, /void startAutoUpload\(event\.dataTransfer\.files\)/)
  assert.doesNotMatch(source, /handleUpload/)
  assert.doesNotMatch(source, /document-title-field/)
  assert.doesNotMatch(source, /document-upload-submit/)
  assert.doesNotMatch(source, /type="submit"/)
  assert.doesNotMatch(source, /document-selected-file/)
  assert.doesNotMatch(source, /document-upload-notice/)
  assert.doesNotMatch(source, /documents-upload/)
  assert.doesNotMatch(source, /openFilePicker/)
  assert.doesNotMatch(source, /uploadSectionRef/)
  assert.equal(source.includes('Tải tài liệu lên'), false)
  assert.match(source, /htmlFor=\{inputId\}/)
  assert.equal(source.includes('Chưa có tài liệu'), true)
  assert.equal(
    source.includes('Tài liệu bạn tải lên sẽ xuất hiện tại đây.'),
    true,
  )
  assert.match(source, /Chọn tài liệu hoặc kéo thả vào đây/)
  assert.match(source, /Đang tải tài liệu lên\.\.\./)
  assert.match(source, /Đang xử lý nội dung tài liệu\.\.\./)
  assert.match(source, /Đang chuẩn bị tài liệu cho AI\.\.\./)
  assert.match(source, /uploadAndPrepareDocument\(file/)
  assert.match(source, /processDocument\(documentId/)
  assert.match(source, /indexDocument\(documentId/)
  assert.match(source, /role=\{uploadState === 'error' \? 'alert' : 'status'\}/)
  assert.match(source, /aria-live="polite"/)
  assert.match(source, /aria-busy=\{isUploading\}/)
  assert.match(source, /onKeyDown=/)
  assert.match(source, /setListRefreshVersion\(\(version\) => version \+ 1\)/)
})

test('the unified upload area keeps focus, mobile, and dark-mode states', async () => {
  const [documentsCss, sharedCss] = await Promise.all([
    readFile(new URL('../src/components/Documents.css', import.meta.url), 'utf8'),
    readFile(new URL('../src/ui-polish.css', import.meta.url), 'utf8'),
  ])

  assert.match(documentsCss, /\.document-dropzone:focus-visible/)
  assert.match(documentsCss, /\.document-dropzone--uploading/)
  assert.match(documentsCss, /\.document-dropzone--success/)
  assert.match(documentsCss, /\.document-dropzone--error/)
  assert.match(documentsCss, /@media \(max-width: 430px\)/)
  assert.doesNotMatch(documentsCss, /\.documents-upload/)
  assert.doesNotMatch(sharedCss, /\.documents-upload/)
  assert.match(sharedCss, /\[data-theme='dark'\] \.document-dropzone--success/)
  assert.match(sharedCss, /\[data-theme='dark'\] \.document-dropzone--error/)
})

test('true library empty state shows the compact three-step guide only after an unfiltered success', async () => {
  const [source, documentsCss, sharedCss] = await Promise.all([
    readFile(new URL('../src/components/Documents.jsx', import.meta.url), 'utf8'),
    readFile(new URL('../src/components/Documents.css', import.meta.url), 'utf8'),
    readFile(new URL('../src/ui-polish.css', import.meta.url), 'utf8'),
  ])

  assert.match(source, /const isLibraryEmpty = Boolean\(/)
  assert.match(source, /listStatus === 'success'/)
  assert.match(source, /documents\.length === 0/)
  assert.match(source, /pagination\.total === 0/)
  assert.match(source, /!hasActiveFilters/)
  assert.match(source, /loadedListScope\?\.search === ''/)
  assert.match(source, /loadedListScope\?\.fileType === 'Tất cả'/)
  assert.match(source, /\{isLibraryEmpty && \(/)
  assert.equal(source.includes('Bắt đầu học cùng StudyMate AI'), true)
  assert.equal(source.includes('Bước 1'), true)
  assert.equal(source.includes('Tải tài liệu'), true)
  assert.equal(source.includes('Chọn PDF hoặc DOCX để bắt đầu.'), true)
  assert.equal(source.includes('Bước 2'), true)
  assert.equal(source.includes('Tóm tắt AI'), true)
  assert.equal(source.includes('Nắm nhanh nội dung quan trọng.'), true)
  assert.equal(source.includes('Bước 3'), true)
  assert.equal(source.includes('Hỏi đáp AI'), true)
  assert.equal(source.includes('Đặt câu hỏi dựa trên tài liệu.'), true)
  assert.doesNotMatch(source, /documents-empty[^\n]*Tải tài liệu lên/)

  assert.match(documentsCss, /\.documents-getting-started__steps/)
  assert.match(documentsCss, /grid-template-columns: repeat\(3, minmax\(0, 1fr\)\)/)
  assert.match(documentsCss, /@media \(max-width: 720px\)/)
  assert.match(sharedCss, /\[data-theme='dark'\] \.documents-getting-started__icon/)
})
