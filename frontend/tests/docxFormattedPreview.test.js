import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

import {
  MAX_DOCX_RENDER_SIZE,
  clearDocxPreview,
  getDocxRenderOptions,
  getFormattedDocxErrorMessage,
  isSafeDocxResourceUrl,
  renderDocxPreview,
  sanitizeDocxPreviewCss,
  validateDocxRenderBlob,
} from '../src/components/docxFormattedPreview.js'
import { ApiHttpError, ApiNetworkError } from '../src/services/apiClient.js'


test('formatted DOCX preview enforces the existing 10 MiB limit', () => {
  assert.equal(MAX_DOCX_RENDER_SIZE, 10 * 1024 * 1024)
  const blob = new Blob(['docx'])
  assert.equal(validateDocxRenderBlob(blob), blob)
  assert.throws(
    () => validateDocxRenderBlob(new Blob(['12345']), 4),
    (error) => error?.code === 'DOCX_PREVIEW_TOO_LARGE',
  )
  assert.throws(() => validateDocxRenderBlob(new Blob([])), TypeError)
})

test('DOCX renderer disables active content and embeds internal resources', () => {
  const options = getDocxRenderOptions()
  assert.equal(options.renderAltChunks, false)
  assert.equal(options.renderChanges, false)
  assert.equal(options.renderComments, false)
  assert.equal(options.experimental, false)
  assert.equal(options.useBase64URL, true)

  assert.equal(isSafeDocxResourceUrl('#bookmark', 'href'), true)
  assert.equal(isSafeDocxResourceUrl('https://example.com/image.png', 'src'), false)
  assert.equal(isSafeDocxResourceUrl('javascript:alert(1)', 'href'), false)
  assert.equal(isSafeDocxResourceUrl('data:image/png;base64,AA==', 'src'), true)

  const sanitized = sanitizeDocxPreviewCss(
    '@import url("https://example.com/a.css"); .safe{background:url(data:image/png;base64,AA==)} .unsafe{background:url(https://example.com/a.png)}',
  )
  assert.equal(sanitized.includes('@import'), false)
  assert.equal(sanitized.includes('https://'), false)
  assert.equal(sanitized.includes('data:image/png'), true)
})

test('DOCX renderer is loaded lazily and replaces only its isolated container', async () => {
  class FakeElement {
    constructor() {
      this.childNodes = []
    }

    querySelectorAll() {
      return []
    }

    replaceChildren(...children) {
      this.childNodes = children
    }
  }

  const target = new FakeElement()
  const documentObject = { createElement: () => new FakeElement() }
  let loadCount = 0
  let receivedOptions
  const loadRenderer = async () => {
    loadCount += 1
    return {
      renderAsync: async (blob, body, styles, options) => {
        assert.ok(blob instanceof Blob)
        receivedOptions = options
        styles.childNodes.push({ nodeName: 'STYLE' })
        body.childNodes.push({ nodeName: 'SECTION' })
      },
    }
  }

  await renderDocxPreview(new Blob(['docx']), target, {
    documentObject,
    loadRenderer,
  })

  assert.equal(loadCount, 1)
  assert.equal(receivedOptions.useBase64URL, true)
  assert.equal(target.childNodes.length, 2)
  clearDocxPreview(target)
  assert.deepEqual(target.childNodes, [])
})

test('formatted DOCX errors remain safe and direct users to text fallback', () => {
  assert.match(
    getFormattedDocxErrorMessage(new ApiNetworkError('private detail')),
    /kết nối mạng/i,
  )
  assert.match(
    getFormattedDocxErrorMessage(new ApiHttpError('private detail', {
      status: 404,
      statusText: 'Not Found',
      data: { detail: 'private detail' },
    })),
    /không tồn tại/i,
  )
  const fallback = getFormattedDocxErrorMessage(new Error('private stack'))
  assert.match(fallback, /xem dạng văn bản/i)
  assert.equal(fallback.includes('private'), false)
})

test('Documents keeps PDF Blob viewing and adds formatted DOCX with text fallback', async () => {
  const source = await readFile(new URL('../src/components/Documents.jsx', import.meta.url), 'utf8')
  const helper = await readFile(new URL('../src/components/docxFormattedPreview.js', import.meta.url), 'utf8')
  const css = await readFile(new URL('../src/components/Documents.css', import.meta.url), 'utf8')
  const themeCss = await readFile(new URL('../src/ui-polish.css', import.meta.url), 'utf8')

  assert.match(source, /viewDocumentPdf\(document\.id/)
  assert.match(source, /downloadDocument\(document\.id/)
  assert.match(source, /previewDocumentDocx\(document\.id/)
  assert.match(source, /FormattedDocxPreview/)
  assert.match(source, /Xem dạng văn bản/)
  assert.match(source, /Tải xuống bản gốc/)
  assert.match(helper, /import\('docx-preview'\)/)
  assert.equal(source.includes('dangerouslySetInnerHTML'), false)
  assert.equal(helper.includes('dangerouslySetInnerHTML'), false)
  assert.match(css, /document-viewer__docx--formatted[^}]*overflow|document-viewer__docx[^}]*overflow:\s*auto/s)
  assert.match(css, /document-viewer__docx-render section\.docx[^}]*background:\s*#fff/s)
  assert.match(themeCss, /\[data-theme='dark'\] \.document-viewer__docx-render section\.docx/)
})
