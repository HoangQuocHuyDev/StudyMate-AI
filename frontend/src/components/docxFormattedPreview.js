import {
  ApiConfigurationError,
  ApiHttpError,
  ApiNetworkError,
} from '../services/apiClient.js'

export const MAX_DOCX_RENDER_SIZE = 10 * 1024 * 1024

const OOXML_FONT_PART = /^word\/(?:document|styles|numbering|footnotes|endnotes|header\d+|footer\d+)\.xml$/i

const BLOCKED_ELEMENTS = new Set([
  'audio',
  'base',
  'embed',
  'form',
  'iframe',
  'link',
  'meta',
  'object',
  'script',
  'source',
  'video',
])
const URL_ATTRIBUTES = new Set([
  'action',
  'formaction',
  'href',
  'poster',
  'src',
  'srcset',
  'xlink:href',
])

export function validateDocxRenderBlob(blob, maxBytes = MAX_DOCX_RENDER_SIZE) {
  if (!(blob instanceof Blob) || blob.size === 0) {
    throw new TypeError('Dữ liệu tài liệu Word không hợp lệ.')
  }
  if (!Number.isInteger(maxBytes) || maxBytes < 1) {
    throw new TypeError('Giới hạn xem trước không hợp lệ.')
  }
  if (blob.size > maxBytes) {
    const error = new RangeError('Tài liệu vượt quá giới hạn xem trước.')
    error.code = 'DOCX_PREVIEW_TOO_LARGE'
    throw error
  }
  return blob
}

export function isSafeDocxResourceUrl(value, attributeName) {
  if (typeof value !== 'string') return false
  const normalized = value.trim()
  if (!normalized) return false
  if (attributeName === 'href' || attributeName === 'xlink:href') {
    return normalized.startsWith('#')
  }
  return /^data:(?:image|font)\//i.test(normalized)
    || /^data:application\/(?:font-|vnd\.ms-fontobject)/i.test(normalized)
}

export function sanitizeDocxPreviewCss(cssText) {
  if (typeof cssText !== 'string') return ''
  return cssText
    .replace(/@import\s+[^;]+;?/gi, '')
    .replace(/url\(([^)]*)\)/gi, (match, rawValue) => {
      const value = rawValue.trim().replace(/^(['"])(.*)\1$/, '$2')
      return isSafeDocxResourceUrl(value, 'src') ? match : 'url("")'
    })
}

function sanitizeRenderedTree(root) {
  for (const element of Array.from(root.querySelectorAll('*'))) {
    const tagName = element.tagName.toLocaleLowerCase('en')
    if (BLOCKED_ELEMENTS.has(tagName)) {
      element.remove()
      continue
    }

    for (const attribute of Array.from(element.attributes)) {
      const name = attribute.name.toLocaleLowerCase('en')
      if (name.startsWith('on')) {
        element.removeAttribute(attribute.name)
        continue
      }
      if (URL_ATTRIBUTES.has(name) && !isSafeDocxResourceUrl(attribute.value, name)) {
        element.removeAttribute(attribute.name)
      }
    }

    if (element.hasAttribute('style')) {
      element.setAttribute(
        'style',
        sanitizeDocxPreviewCss(element.getAttribute('style') ?? ''),
      )
    }
    if (tagName === 'style') {
      element.textContent = sanitizeDocxPreviewCss(element.textContent ?? '')
    }
  }
}

export function getDocxRenderOptions() {
  return {
    breakPages: true,
    debug: false,
    experimental: false,
    ignoreFonts: false,
    renderAltChunks: false,
    renderChanges: false,
    renderComments: false,
    useBase64URL: true,
  }
}

function readXmlAttribute(attributes, localName) {
  const expression = new RegExp(
    `(?:^|\\s)((?:[A-Za-z_][\\w.-]*:)?${localName})\\s*=\\s*(["'])(.*?)\\2`,
    'i',
  )
  const match = expression.exec(attributes)
  return match ? { name: match[1], value: match[3] } : null
}

export function addDocxPreviewFontFallbacks(xml) {
  if (typeof xml !== 'string' || !xml) return xml
  return xml.replace(
    /<((?:[A-Za-z_][\w.-]*:)?rFonts)\b([^>]*?)(\/?)>/gi,
    (element, qualifiedName, attributes, selfClosing) => {
      const hAnsi = readXmlAttribute(attributes, 'hAnsi')
      const hAnsiTheme = readXmlAttribute(attributes, 'hAnsiTheme')
      const ascii = readXmlAttribute(attributes, 'ascii')
      const asciiTheme = readXmlAttribute(attributes, 'asciiTheme')
      const prefix = qualifiedName.includes(':')
        ? qualifiedName.slice(0, qualifiedName.indexOf(':') + 1)
        : (hAnsi?.name.includes(':') ? hAnsi.name.split(':')[0] + ':' : '')
      let additions = ''
      if (!ascii && hAnsi) additions += ` ${prefix}ascii="${hAnsi.value}"`
      if (!asciiTheme && hAnsiTheme) {
        additions += ` ${prefix}asciiTheme="${hAnsiTheme.value}"`
      }
      return `<${qualifiedName}${attributes}${additions}${selfClosing}>`
    },
  )
}

export async function normalizeDocxFontsForPreview(
  blob,
  {
    loadZip = () => import('jszip'),
    maxBytes = MAX_DOCX_RENDER_SIZE,
  } = {},
) {
  validateDocxRenderBlob(blob, maxBytes)
  const zipModule = await loadZip()
  const Zip = zipModule?.default ?? zipModule
  if (typeof Zip?.loadAsync !== 'function') {
    throw new TypeError('Không thể đọc cấu hình font của tài liệu Word.')
  }
  const archive = await Zip.loadAsync(blob)
  let changed = false
  const fontParts = Object.values(archive.files).filter(
    (file) => !file.dir && OOXML_FONT_PART.test(file.name),
  )
  await Promise.all(fontParts.map(async (file) => {
    const original = await file.async('string')
    const normalized = addDocxPreviewFontFallbacks(original)
    if (normalized !== original) {
      archive.file(file.name, normalized)
      changed = true
    }
  }))
  if (!changed) return blob
  return archive.generateAsync({
    type: 'blob',
    compression: 'DEFLATE',
    compressionOptions: { level: 6 },
  })
}

export async function renderDocxPreview(
  blob,
  container,
  {
    documentObject = document,
    loadRenderer = () => import('docx-preview'),
    maxBytes = MAX_DOCX_RENDER_SIZE,
    normalizeFonts = normalizeDocxFontsForPreview,
  } = {},
) {
  validateDocxRenderBlob(blob, maxBytes)
  if (!container || typeof container.replaceChildren !== 'function') {
    throw new TypeError('Vùng xem trước tài liệu không hợp lệ.')
  }

  const normalizedBlob = await normalizeFonts(blob, { maxBytes })
  const body = documentObject.createElement('div')
  const styles = documentObject.createElement('div')
  const renderer = await loadRenderer()
  if (typeof renderer?.renderAsync !== 'function') {
    throw new TypeError('Không thể khởi tạo trình xem tài liệu Word.')
  }

  await renderer.renderAsync(normalizedBlob, body, styles, getDocxRenderOptions())
  sanitizeRenderedTree(styles)
  sanitizeRenderedTree(body)
  container.replaceChildren(...styles.childNodes, ...body.childNodes)
}

export function clearDocxPreview(container) {
  container?.replaceChildren?.()
}

export function getFormattedDocxErrorMessage(error) {
  if (error?.code === 'DOCX_PREVIEW_TOO_LARGE') {
    return 'Tài liệu vượt quá giới hạn 10 MiB để xem định dạng trực tiếp.'
  }
  if (error instanceof ApiNetworkError) {
    return 'Không thể tải tài liệu. Vui lòng kiểm tra kết nối mạng và thử lại.'
  }
  if (error instanceof ApiConfigurationError) {
    return 'Ứng dụng chưa được cấu hình đầy đủ để xem tài liệu.'
  }
  if (error instanceof ApiHttpError) {
    if (error.status === 404) return 'Tài liệu không tồn tại hoặc bạn không có quyền truy cập.'
    if (error.status === 409) return 'Tài liệu đang thay đổi trạng thái. Vui lòng thử lại sau.'
    if (error.status === 413) return 'Tài liệu vượt quá giới hạn cho phép để xem trước.'
  }
  return 'Không thể hiển thị định dạng Word. Bạn vẫn có thể xem dạng văn bản.'
}
