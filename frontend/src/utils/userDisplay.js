const fallbackName = 'Người dùng'
const vietnameseSegmenter = typeof Intl.Segmenter === 'function'
  ? new Intl.Segmenter('vi', { granularity: 'grapheme' })
  : null

function normalizeText(value) {
  return typeof value === 'string' ? value.trim().replace(/\s+/gu, ' ') : ''
}

function getGraphemes(value) {
  if (!vietnameseSegmenter) return Array.from(value)
  return Array.from(vietnameseSegmenter.segment(value), ({ segment }) => segment)
}

export function getDisplayName(user) {
  return normalizeText(user?.full_name) || normalizeText(user?.username) || fallbackName
}

export function getDisplayUsername(user) {
  return normalizeText(user?.username)
}

export function getRoleLabel(user) {
  if (user?.role === 'ADMIN') return 'Quản trị viên'
  if (user?.role === 'USER') return 'Sinh viên'
  return fallbackName
}

export function getUserInitials(user) {
  const displayName = getDisplayName(user)
  const words = displayName.split(/\s+/u)
  const characters = words.length === 1
    ? getGraphemes(words[0]).slice(0, 2)
    : [getGraphemes(words[0])[0], getGraphemes(words.at(-1))[0]]

  return characters.filter(Boolean).join('').toLocaleUpperCase('vi-VN') || 'ND'
}
