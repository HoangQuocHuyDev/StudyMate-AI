import assert from 'node:assert/strict'
import test from 'node:test'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'

import {
  AssistantMarkdown,
  PlainTextMessage,
  sanitizeMarkdownUrl,
} from '../src/components/chatMarkdown.js'

function renderAssistant(content) {
  return renderToStaticMarkup(createElement(AssistantMarkdown, { content }))
}

test('assistant renders emphasis, headings, and both list types', () => {
  const html = renderAssistant([
    '## Tiêu đề',
    '',
    '**đậm** và *nghiêng*',
    '',
    '- mục một',
    '- mục hai',
    '',
    '1. bước một',
    '2. bước hai',
  ].join('\n'))

  assert.match(html, /<h2>Tiêu đề<\/h2>/)
  assert.match(html, /<strong>đậm<\/strong>/)
  assert.match(html, /<em>nghiêng<\/em>/)
  assert.match(html, /<ul>/)
  assert.match(html, /<ol>/)
})

test('assistant renders inline code and fenced code blocks', () => {
  const html = renderAssistant('Dùng `const`:\n\n```js\nconst answer = 42\n```')

  assert.match(html, /<code>const<\/code>/)
  assert.match(html, /<pre><code class="language-js">const answer = 42/)
})

test('raw HTML is not rendered or executed', () => {
  const html = renderAssistant('An toàn <img src=x onerror="alert(1)"> <script>alert(2)</script>')

  assert.doesNotMatch(html, /<img|<script|onerror=/i)
})

test('unsafe link schemes are blocked while safe links are protected', () => {
  const unsafeHtml = renderAssistant('[xấu](javascript:alert(1))')
  const safeHtml = renderAssistant('[tốt](https://example.com/tai-lieu)')

  assert.doesNotMatch(unsafeHtml, /<a\b|href=|javascript:/i)
  assert.match(safeHtml, /href="https:\/\/example\.com\/tai-lieu"/)
  assert.match(safeHtml, /target="_blank"/)
  assert.match(safeHtml, /rel="noopener noreferrer"/)
  assert.equal(sanitizeMarkdownUrl('data:text/html,unsafe'), '')
})

test('user messages remain plain text instead of Markdown', () => {
  const html = renderToStaticMarkup(createElement(PlainTextMessage, {
    content: '**không in đậm** <script>alert(1)</script>',
  }))

  assert.doesNotMatch(html, /<strong>|<script>/)
  assert.match(html, /\*\*không in đậm\*\*/)
  assert.match(html, /&lt;script&gt;alert\(1\)&lt;\/script&gt;/)
})

test('old assistant message content still renders through the same renderer', () => {
  const html = renderAssistant('Nội dung hội thoại cũ')
  assert.match(html, /<p>Nội dung hội thoại cũ<\/p>/)
})
