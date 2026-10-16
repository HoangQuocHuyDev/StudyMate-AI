import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

import {
  ApiHttpError,
  ApiNetworkError,
} from '../src/services/apiClient.js'
import {
  getDocxPreviewErrorMessage,
  validateDocxPreviewResponse,
} from '../src/components/documentPreviewUi.js'


const preview = {
  document_id: 7,
  title: 'Bài học',
  original_filename: 'bai-hoc.docx',
  file_type: 'DOCX',
  content: 'Dòng thứ nhất.\n\nDòng thứ hai.',
  character_count: 31,
}


test('DOCX preview response preserves plain text and supports empty content', () => {
  assert.equal(validateDocxPreviewResponse(preview, 7), preview)
  assert.equal(validateDocxPreviewResponse({
    ...preview,
    content: '',
    character_count: 0,
  }, 7).content, '')
})

test('DOCX preview rejects mismatched or malformed responses', () => {
  for (const invalid of [
    null,
    { ...preview, document_id: 8 },
    { ...preview, file_type: 'PDF' },
    { ...preview, content: null },
    { ...preview, character_count: -1 },
    { ...preview, original_filename: '' },
  ]) {
    assert.throws(() => validateDocxPreviewResponse(invalid, 7), TypeError)
  }
})

for (const [status, pattern] of [
  [400, /không hỗ trợ/i],
  [404, /không tồn tại/i],
  [409, /chưa được xử lý xong/i],
  [413, /vượt quá giới hạn/i],
  [500, /không thể tạo bản xem trước/i],
]) {
  test(`HTTP ${status} uses a safe DOCX preview message`, () => {
    const secret = 'private-path-and-stack-trace'
    const message = getDocxPreviewErrorMessage(new ApiHttpError(secret, {
      status,
      statusText: 'Failure',
      data: { detail: secret },
    }))
    assert.match(message, pattern)
    assert.equal(message.includes(secret), false)
  })
}

test('DOCX preview network failure uses a safe retryable message', () => {
  const message = getDocxPreviewErrorMessage(new ApiNetworkError('private'))
  assert.match(message, /kiểm tra mạng/i)
  assert.equal(message.includes('private'), false)
})

test('Documents renders PDF and DOCX viewers safely with stale-response guards', async () => {
  const source = await readFile(new URL('../src/components/Documents.jsx', import.meta.url), 'utf8')
  const css = await readFile(new URL('../src/components/Documents.css', import.meta.url), 'utf8')
  const themeCss = await readFile(new URL('../src/ui-polish.css', import.meta.url), 'utf8')

  assert.match(source, /\['PDF', 'DOCX'\]\.includes\(document\.file_type\)/)
  assert.match(source, /previewDocumentDocx\(document\.id/)
  assert.match(source, /downloadDocument\(document\.id/)
  assert.match(source, /viewDocumentPdf\(document\.id/)
  assert.match(source, /viewerRequestRef/)
  assert.match(source, /controller\?\.abort\(\)/)
  assert.match(source, /Tài liệu này chưa có nội dung văn bản để xem trước\./)
  assert.match(source, /Tải xuống bản gốc/)
  assert.equal(source.includes('dangerouslySetInnerHTML'), false)
  assert.match(css, /white-space:\s*pre-wrap/)
  assert.match(css, /document-viewer__docx[^}]*overflow:\s*auto/s)
  assert.match(themeCss, /\[data-theme='dark'\] \.document-viewer__docx/)
})
