export const MAX_DOCUMENT_SEARCH_LENGTH = 255

export function normalizeDocumentSearchTerm(value) {
  if (typeof value !== 'string') return ''
  return value.trim()
}

export function getDocumentSearchValidationMessage(value) {
  if (typeof value !== 'string') {
    return 'Từ khóa tìm kiếm không hợp lệ.'
  }
  if (normalizeDocumentSearchTerm(value).length > MAX_DOCUMENT_SEARCH_LENGTH) {
    return `Từ khóa tìm kiếm không được vượt quá ${MAX_DOCUMENT_SEARCH_LENGTH} ký tự.`
  }
  return ''
}

export function parseDocumentSearch(search) {
  const value = new URLSearchParams(search).get('search') ?? ''
  return normalizeDocumentSearchTerm(value).slice(0, MAX_DOCUMENT_SEARCH_LENGTH)
}

export function getInitialDocumentSearchState(search) {
  const value = parseDocumentSearch(search)
  return { query: value, debouncedSearch: value }
}

export function buildDocumentSearchUrl({
  keyword,
  currentPath = '/',
  currentSearch = '',
  currentHash = '',
}) {
  const validationMessage = getDocumentSearchValidationMessage(keyword)
  if (validationMessage) throw new RangeError(validationMessage)

  const params = currentPath === '/documents'
    ? new URLSearchParams(currentSearch)
    : new URLSearchParams()
  const normalizedKeyword = normalizeDocumentSearchTerm(keyword)

  if (normalizedKeyword) params.set('search', normalizedKeyword)
  else params.delete('search')

  if (params.has('page')) params.set('page', '1')

  const query = params.toString()
  const hash = currentPath === '/documents' && currentHash
    ? (currentHash.startsWith('#') ? currentHash : `#${currentHash}`)
    : ''
  return `/documents${query ? `?${query}` : ''}${hash}`
}

export function shouldCommitDocumentSearch({
  query,
  urlSearch,
  scheduledLocationKey,
  currentLocationKey,
}) {
  return scheduledLocationKey === currentLocationKey
    && normalizeDocumentSearchTerm(query) !== parseDocumentSearch(urlSearch)
}
