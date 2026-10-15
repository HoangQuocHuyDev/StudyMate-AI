export class ChatDeepLinkError extends Error {
  constructor(message, code = 'invalid_link') {
    super(message)
    this.name = 'ChatDeepLinkError'
    this.code = code
  }
}

function parsePositiveInteger(value) {
  if (typeof value !== 'string' || !/^[1-9]\d*$/.test(value)) return null
  const parsed = Number(value)
  return Number.isSafeInteger(parsed) ? parsed : null
}

export function parseChatDeepLink(search = '') {
  const params = new URLSearchParams(search)
  const documentValues = params.getAll('document_id')
  const sessionValues = params.getAll('session_id')
  if (documentValues.length === 0 && sessionValues.length === 0) {
    return { kind: 'none', documentId: null, sessionId: null }
  }
  if (documentValues.length !== 1 || sessionValues.length > 1) {
    return { kind: 'invalid', documentId: null, sessionId: null }
  }

  const documentId = parsePositiveInteger(documentValues[0])
  const sessionId = sessionValues.length === 1
    ? parsePositiveInteger(sessionValues[0])
    : null
  if (!documentId || (sessionValues.length === 1 && !sessionId)) {
    return { kind: 'invalid', documentId: null, sessionId: null }
  }
  return { kind: 'valid', documentId, sessionId }
}

export function buildChatDeepLinkUrl(documentId, sessionId = null) {
  if (!Number.isSafeInteger(documentId) || documentId < 1) {
    throw new TypeError('Mã tài liệu không hợp lệ.')
  }
  if (sessionId !== null && (!Number.isSafeInteger(sessionId) || sessionId < 1)) {
    throw new TypeError('Mã cuộc trò chuyện không hợp lệ.')
  }
  const params = new URLSearchParams({ document_id: String(documentId) })
  if (sessionId !== null) params.set('session_id', String(sessionId))
  return `/chat?${params.toString()}`
}

export function mergeDeepLinkedDocument(pageItems, targetDocument) {
  const merged = pageItems.slice()
  const index = merged.findIndex((document) => document.id === targetDocument.id)
  if (index === -1) merged.push(targetDocument)
  else merged[index] = targetDocument
  return merged
}

export function isChatDeepLinkRequestCurrent({
  requestVersion,
  currentRequestVersion,
  aborted = false,
}) {
  return !aborted && requestVersion === currentRequestVersion
}

export async function findSessionAcrossPages({
  targetSessionId,
  pageSize,
  fetchPage,
}) {
  if (!Number.isSafeInteger(targetSessionId) || targetSessionId < 1) {
    throw new TypeError('Mã cuộc trò chuyện không hợp lệ.')
  }
  if (!Number.isInteger(pageSize) || pageSize < 1) {
    throw new TypeError('Kích thước trang không hợp lệ.')
  }

  const items = []
  const positions = new Map()
  let offset = 0
  let total = null
  let fetchedCount = 0
  let remainingPageBudget = null

  while ((total === null || offset < total) && remainingPageBudget !== 0) {
    const page = await fetchPage(offset)
    if (
      !page
      || !Array.isArray(page.items)
      || !Number.isInteger(page.total)
      || page.total < 0
      || page.limit !== pageSize
      || page.offset !== offset
    ) {
      throw new TypeError('Phản hồi phân trang hội thoại không hợp lệ.')
    }
    if (total === null) {
      total = page.total
      remainingPageBudget = Math.ceil(total / pageSize) + 1
    }
    remainingPageBudget -= 1
    fetchedCount += page.items.length

    for (const session of page.items) {
      if (!session || !Number.isSafeInteger(session.id) || session.id < 1) {
        throw new TypeError('Phản hồi phân trang hội thoại không hợp lệ.')
      }
      const existing = positions.get(session.id)
      if (existing === undefined) {
        positions.set(session.id, items.length)
        items.push(session)
      } else {
        items[existing] = session
      }
    }

    const target = items.find((session) => session.id === targetSessionId)
    if (target) return { target, items, total, fetchedCount }
    if (page.items.length === 0 || fetchedCount >= total) break
    offset += page.items.length
  }

  throw new ChatDeepLinkError(
    'Cuộc trò chuyện không tồn tại hoặc bạn không có quyền truy cập.',
    'session_not_found',
  )
}
