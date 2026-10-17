import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

import {
  MAX_DOCX_RENDER_SIZE,
  addDocxPreviewFontFallbacks,
  clearDocxPreview,
  getDocxRenderOptions,
  getFormattedDocxErrorMessage,
  isSafeDocxResourceUrl,
  normalizeDocxFontsForPreview,
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

test('hAnsi font declarations gain only the ascii fallback required by docx-preview', () => {
  const input = [
    '<w:rFonts w:hAnsi="Times New Roman"/>',
    '<w:rFonts w:ascii="Arial" w:hAnsi="Calibri"/>',
    '<w:rFonts w:hAnsiTheme="minorHAnsi"/>',
  ].join('')
  const output = addDocxPreviewFontFallbacks(input)

  assert.match(output, /w:hAnsi="Times New Roman" w:ascii="Times New Roman"/)
  assert.match(output, /w:ascii="Arial" w:hAnsi="Calibri"/)
  assert.doesNotMatch(output, /w:ascii="Calibri"/)
  assert.match(output, /w:hAnsiTheme="minorHAnsi" w:asciiTheme="minorHAnsi"/)
})

test('font normalization updates an in-memory DOCX without changing its text', async () => {
  const JSZip = (await import('jszip')).default
  const bytes = await readFile(new URL('./fixtures/docx/typography-vietnamese.docx', import.meta.url))
  const sourceBlob = new Blob([bytes])
  const sourceArchive = await JSZip.loadAsync(sourceBlob)
  const sourceXml = await sourceArchive.file('word/document.xml').async('string')

  const normalizedBlob = await normalizeDocxFontsForPreview(sourceBlob)
  const normalizedArchive = await JSZip.loadAsync(normalizedBlob)
  const normalizedXml = await normalizedArchive.file('word/document.xml').async('string')

  assert.equal(normalizedXml.replace(/<w:rFonts\b[^>]*\/>/g, ''), sourceXml.replace(/<w:rFonts\b[^>]*\/>/g, ''))
  assert.match(normalizedXml, /w:hAnsi="Arial"[^>]*w:ascii="Arial"/)
  assert.match(normalizedXml, /Tiếng Việt rõ ràng/)
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
    normalizeFonts: async (blob) => blob,
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

test('DOCX paragraphs keep Word indentation without modal text clipping', async () => {
  const css = await readFile(new URL('../src/components/Documents.css', import.meta.url), 'utf8')
  const themeCss = await readFile(new URL('../src/ui-polish.css', import.meta.url), 'utf8')

  assert.doesNotMatch(css, /\.document-viewer__panel p\s*\{/)
  assert.doesNotMatch(css, /\.document-viewer__panel h2\s*\{/)
  assert.doesNotMatch(themeCss, /\.document-viewer__panel p\s*\{/)
  assert.doesNotMatch(themeCss, /\.document-viewer__panel h2\s*\{/)
  assert.match(css, /\.document-viewer__panel header p\s*\{[^}]*overflow:\s*hidden/s)
  assert.match(css, /\.document-viewer__docx-render\s*\{[^}]*width:\s*max-content;[^}]*min-width:\s*100%;/s)
  assert.match(css, /\.document-viewer__docx\s*\{[^}]*overflow:\s*auto;/s)
})

test('DOCX typography is isolated from the application font without overriding OOXML runs', async () => {
  const css = await readFile(new URL('../src/components/Documents.css', import.meta.url), 'utf8')
  const wrapperRule = css.match(/\.document-viewer__docx-render \.docx-wrapper\s*\{([^}]*)\}/s)?.[1] ?? ''
  const sectionRule = css.match(/\.document-viewer__docx-render section\.docx\s*\{([^}]*)\}/s)?.[1] ?? ''

  assert.match(wrapperRule, /font-family:\s*initial;/)
  assert.match(wrapperRule, /font-synthesis:\s*auto;/)
  assert.match(wrapperRule, /font-kerning:\s*auto;/)
  assert.match(wrapperRule, /text-rendering:\s*auto;/)
  assert.doesNotMatch(wrapperRule, /letter-spacing|word-spacing|text-align|text-align-last|font-stretch/)
  assert.doesNotMatch(sectionRule, /font-family|letter-spacing|word-spacing|text-align|text-align-last/)
})
