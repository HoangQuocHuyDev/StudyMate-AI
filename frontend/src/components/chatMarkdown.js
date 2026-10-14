import { createElement } from 'react'
import ReactMarkdown from 'react-markdown'

const SAFE_PROTOCOLS = new Set(['http:', 'https:', 'mailto:'])

export function sanitizeMarkdownUrl(url) {
  if (typeof url !== 'string') return ''

  const value = url.trim()
  if (!value || value.startsWith('//')) return ''

  const compactValue = [...value]
    .filter((character) => character.codePointAt(0) > 0x20)
    .join('')
  const scheme = compactValue.match(/^([a-z][a-z\d+.-]*):/i)?.[1]
  if (scheme) {
    return SAFE_PROTOCOLS.has(`${scheme.toLowerCase()}:`) ? value : ''
  }

  return value
}

function SafeLink({ href, children, node: _node, ...props }) {
  const safeHref = sanitizeMarkdownUrl(href)
  if (!safeHref) {
    return createElement('span', { className: 'chat-markdown__blocked-link' }, children)
  }

  return createElement('a', {
    ...props,
    href: safeHref,
    target: '_blank',
    rel: 'noopener noreferrer',
  }, children)
}

export function AssistantMarkdown({ content }) {
  return createElement(
    'div',
    { className: 'chat-markdown' },
    createElement(
      ReactMarkdown,
      {
        skipHtml: true,
        urlTransform: sanitizeMarkdownUrl,
        components: { a: SafeLink },
      },
      content,
    ),
  )
}

export function PlainTextMessage({ content }) {
  return createElement('p', null, content)
}
