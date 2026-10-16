import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { useAuth } from '../contexts/AuthContext'
import { useNavigation } from '../navigation/NavigationContext'
import {
  askDocument,
  getChatCitation,
  getChatMessagesCursor,
  getChatSessions,
  MAX_CHAT_QUESTION_LENGTH,
} from '../services/chatService'
import { ApiHttpError } from '../services/apiClient'
import {
  getDocumentDetail,
  getDocumentRagStatus,
  getDocuments,
} from '../services/documentService'
import { getUserInitials } from '../utils/userDisplay'
import {
  buildChatStatusMessages,
  chooseChatDocumentId,
  classifyDocumentForChat,
  getChatDocumentStatusLabel,
  getChatErrorMessage,
  getPrependedScrollTop,
  getRagStatusFailureKind,
  getQuestionValidationMessage,
  isChatReadyDocument,
  isChatResponseCurrent,
  mapWithConcurrency,
  mergeChatMessages,
  mergeUniqueById,
  unavailableChatDocument,
  validateChatMessageCursorPage,
} from './chatUi'
import {
  CitationDetailPanel,
  CitationSourceButton,
  isCitationRequestCurrent,
  validateCitationDetail,
} from './chatCitationUi'
import { AssistantMarkdown, PlainTextMessage } from './chatMarkdown'
import {
  buildChatDeepLinkUrl,
  ChatDeepLinkError,
  findSessionAcrossPages,
  isChatDeepLinkRequestCurrent,
  mergeDeepLinkedDocument,
  parseChatDeepLink,
} from './chatDeepLink'
import Header from './Header'
import Icon from './Icons'
import Sidebar from './Sidebar'
import './Chat.css'

const DOCUMENT_PAGE_SIZE = 20
const SESSION_PAGE_SIZE = 20
const MESSAGE_PAGE_SIZE = 50
const MAX_CONCURRENT_STATUS_REQUESTS = 4
const suggestions = [
  'Tóm tắt những ý chính của tài liệu',
  'Giải thích khái niệm quan trọng nhất',
  'Tạo 5 câu hỏi ôn tập từ tài liệu',
]

function formatDateTime(value) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return 'Không rõ thời gian'
  return new Intl.DateTimeFormat('vi-VN', {
    dateStyle: 'short',
    timeStyle: 'short',
  }).format(date)
}

function validatePage(response, expectedLimit, expectedOffset) {
  if (
    !response
    || !Array.isArray(response.items)
    || !Number.isInteger(response.total)
    || response.total < 0
    || response.limit !== expectedLimit
    || response.offset !== expectedOffset
  ) {
    throw new TypeError('Phản hồi phân trang hội thoại không hợp lệ.')
  }
  return response
}

function validateAskResponse(response) {
  if (
    !response
    || !Number.isInteger(response.session_id)
    || !Number.isInteger(response.user_message_id)
    || !Number.isInteger(response.assistant_message_id)
    || typeof response.answer_text !== 'string'
    || !response.answer_text.trim()
    || typeof response.model_name !== 'string'
    || !Array.isArray(response.citations)
  ) {
    throw new TypeError('Phản hồi hỏi đáp không hợp lệ.')
  }
  return response
}

function CitationList({ citations, onSelect }) {
  if (!Array.isArray(citations) || citations.length === 0) return null
  return (
    <div className="chat-citations" aria-label="Nguồn trích dẫn">
      <div className="chat-citations__title">
        <Icon name="file" size={15} /><strong>Nguồn tham khảo</strong>
      </div>
      <div className="chat-citations__list">
        {citations.map((citation) => (
          <CitationSourceButton
            citation={citation}
            onSelect={onSelect}
            key={`${citation.chunk_id}-${citation.citation_order}`}
          />
        ))}
      </div>
    </div>
  )
}

function ChatMessage({ message, onCopy, onCitationSelect, copied, userInitials }) {
  if (message.role === 'USER') {
    return (
      <article className="chat-message chat-message--user">
        <div className="chat-message__avatar">{userInitials}</div>
        <div className="chat-message__body">
          <div className="chat-message__bubble">
            <PlainTextMessage content={message.content} />
          </div>
        </div>
      </article>
    )
  }
  return (
    <article className="chat-message chat-message--ai">
      <div className="chat-message__avatar"><Icon name="bot" size={19} /></div>
      <div className="chat-message__body">
        <div className="chat-message__label">
          <strong>StudyMate AI</strong>
          <span>{message.model_name || 'Trả lời từ tài liệu của bạn'}</span>
        </div>
        <div className="chat-message__bubble">
          <AssistantMarkdown content={message.content} />
          <CitationList
            citations={message.citations}
            onSelect={(citation) => onCitationSelect(message, citation)}
          />
        </div>
        <button className="chat-copy" type="button" onClick={() => onCopy(message)}>
          <Icon name={copied ? 'check' : 'copy'} size={15} />
          {copied ? 'Đã sao chép' : 'Sao chép câu trả lời'}
        </button>
      </div>
    </article>
  )
}

function TypingIndicator() {
  return (
    <div className="chat-message chat-message--ai" role="status" aria-live="polite">
      <div className="chat-message__avatar"><Icon name="bot" size={19} /></div>
      <div className="chat-message__body">
        <div className="chat-message__label">
          <strong>StudyMate AI</strong><span>AI đang trả lời...</span>
        </div>
        <div className="chat-typing"><i /><i /><i /></div>
      </div>
    </div>
  )
}

function Chat({ isSidebarOpen, onOpenSidebar, onCloseSidebar }) {
  const { accessToken, user } = useAuth()
  const { currentSearch, navigate } = useNavigation()
  const deepLink = useMemo(() => parseChatDeepLink(currentSearch), [currentSearch])
  const userInitials = getUserInitials(user)
  const [documents, setDocuments] = useState([])
  const [selectedDocumentId, setSelectedDocumentId] = useState(null)
  const [documentsState, setDocumentsState] = useState({
    loading: true,
    loadingMore: false,
    error: null,
    loadMoreError: null,
    page: 0,
    totalPages: 0,
    total: 0,
    deletedCount: 0,
  })
  const [sessions, setSessions] = useState([])
  const [sessionTotal, setSessionTotal] = useState(0)
  const [sessionFetchedCount, setSessionFetchedCount] = useState(0)
  const [sessionsState, setSessionsState] = useState({ loading: false, error: null })
  const [selectedSessionId, setSelectedSessionId] = useState(null)
  const [messages, setMessages] = useState([])
  const [messageCursor, setMessageCursor] = useState({
    hasMore: false,
    nextBeforeSequenceNo: null,
  })
  const [messagesState, setMessagesState] = useState({
    loading: false,
    loadingMore: false,
    error: null,
  })
  const [question, setQuestion] = useState('')
  const [sendError, setSendError] = useState(null)
  const [isAnswering, setIsAnswering] = useState(false)
  const [copiedId, setCopiedId] = useState(null)
  const [citationState, setCitationState] = useState({
    open: false,
    loading: false,
    error: null,
    data: null,
  })
  const [deepLinkState, setDeepLinkState] = useState({
    loading: false,
    error: null,
    retryVersion: 0,
  })

  const documentRequest = useRef({ version: 0, controller: null })
  const deepLinkRequest = useRef({ version: 0, controller: null })
  const skipDeepLinkSearch = useRef(null)
  const skipNextSessionLoad = useRef(null)
  const documentsRef = useRef([])
  const sessionRequest = useRef({ version: 0, controller: null })
  const messageRequest = useRef({ version: 0, controller: null, loadingMore: false })
  const sendRequest = useRef({ version: 0, controller: null, active: false })
  const citationRequest = useRef({ version: 0, controller: null })
  const conversationVersion = useRef(0)
  const selectedDocumentIdRef = useRef(null)
  const selectedSessionIdRef = useRef(null)
  const copyTimer = useRef(null)
  const threadRef = useRef(null)
  const conversationEnd = useRef(null)
  const shouldAutoScroll = useRef(true)
  const pendingScrollRestore = useRef(null)
  const inputRef = useRef(null)

  const selectedDocument = useMemo(
    () => documents.find((document) => document.id === selectedDocumentId) ?? null,
    [documents, selectedDocumentId],
  )
  const canAsk = isChatReadyDocument(selectedDocument)
  const documentStatusMessages = useMemo(() => {
    const messages = buildChatStatusMessages(documents)
    if (documentsState.deletedCount > 0) {
      messages.push(`${documentsState.deletedCount} tài liệu không còn tồn tại hoặc quyền truy cập đã thay đổi.`)
    }
    return messages
  }, [documents, documentsState.deletedCount])

  const handleRequestError = useCallback((error) => {
    return getChatErrorMessage(error)
  }, [])

  const navigateToChatSelection = useCallback((documentId, sessionId = null, options = {}) => {
    const destination = buildChatDeepLinkUrl(documentId, sessionId)
    const destinationSearch = new URL(destination, window.location.origin).search
    if (destinationSearch === window.location.search) return
    skipDeepLinkSearch.current = destinationSearch
    navigate(destination, options)
  }, [navigate])

  const closeCitationPanel = useCallback(() => {
    citationRequest.current.version += 1
    citationRequest.current.controller?.abort()
    citationRequest.current.controller = null
    setCitationState({ open: false, loading: false, error: null, data: null })
  }, [])

  const resetConversationState = useCallback(() => {
    conversationVersion.current += 1
    sendRequest.current.version += 1
    sendRequest.current.controller?.abort()
    sendRequest.current.active = false
    messageRequest.current.version += 1
    messageRequest.current.controller?.abort()
    selectedSessionIdRef.current = null
    setSelectedSessionId(null)
    setMessages([])
    setMessageCursor({ hasMore: false, nextBeforeSequenceNo: null })
    setMessagesState({ loading: false, loadingMore: false, error: null })
    pendingScrollRestore.current = null
    setQuestion('')
    setSendError(null)
    setIsAnswering(false)
    setSessions([])
    setSessionTotal(0)
    setSessionFetchedCount(0)
    closeCitationPanel()
  }, [closeCitationPanel])

  const removeDeletedDocument = useCallback((documentId) => {
    const remaining = documentsRef.current.filter(
      (document) => document.id !== documentId,
    )
    documentsRef.current = remaining
    setDocuments(remaining)
    setDocumentsState((current) => ({
      ...current,
      total: Math.max(0, current.total - 1),
    }))
    if (selectedDocumentIdRef.current !== documentId) return
    resetConversationState()
    const nextId = chooseChatDocumentId(remaining, null)
    selectedDocumentIdRef.current = nextId
    setSelectedDocumentId(nextId)
    if (nextId) navigateToChatSelection(nextId, null, { replace: true })
    else navigate('/chat', { replace: true })
  }, [navigate, navigateToChatSelection, resetConversationState])

  const removeDeletedSession = useCallback((sessionId) => {
    setSessions((current) => current.filter((session) => session.id !== sessionId))
    setSessionTotal((current) => Math.max(0, current - 1))
    if (selectedSessionIdRef.current !== sessionId) return
    conversationVersion.current += 1
    messageRequest.current.version += 1
    messageRequest.current.controller?.abort()
    selectedSessionIdRef.current = null
    setSelectedSessionId(null)
    setMessages([])
    setMessageCursor({ hasMore: false, nextBeforeSequenceNo: null })
    setMessagesState({ loading: false, loadingMore: false, error: null })
    pendingScrollRestore.current = null
    closeCitationPanel()
    if (selectedDocumentIdRef.current) {
      navigateToChatSelection(
        selectedDocumentIdRef.current,
        null,
        { replace: true },
      )
    }
  }, [closeCitationPanel, navigateToChatSelection])

  useEffect(() => {
    if (!isSidebarOpen) return undefined
    const handleKeyDown = (event) => event.key === 'Escape' && onCloseSidebar()
    document.addEventListener('keydown', handleKeyDown)
    document.body.classList.add('sidebar-visible')
    return () => {
      document.removeEventListener('keydown', handleKeyDown)
      document.body.classList.remove('sidebar-visible')
    }
  }, [isSidebarOpen, onCloseSidebar])

  const loadDocumentPage = useCallback(async (requestedPage, append = false) => {
    const requestVersion = documentRequest.current.version + 1
    documentRequest.current.controller?.abort()
    const controller = new AbortController()
    documentRequest.current = { version: requestVersion, controller }

    setDocumentsState((current) => ({
      ...current,
      loading: !append,
      loadingMore: append,
      error: append ? current.error : null,
      loadMoreError: null,
      ...(append ? {} : { deletedCount: 0 }),
    }))

    try {
      const page = await getDocuments({
        accessToken,
        page: requestedPage,
        pageSize: DOCUMENT_PAGE_SIZE,
        signal: controller.signal,
      })
      if (
        !page
        || !Array.isArray(page.items)
        || page.page !== requestedPage
        || !Number.isInteger(page.total_pages)
        || page.total_pages < 0
        || !Number.isInteger(page.total)
        || page.total < 0
      ) {
        throw new TypeError('Phản hồi danh sách tài liệu không hợp lệ.')
      }
      const results = await mapWithConcurrency(
        page.items,
        MAX_CONCURRENT_STATUS_REQUESTS,
        async (document) => {
          try {
            const rag = await getDocumentRagStatus(document.id, {
              accessToken,
              signal: controller.signal,
            })
            return classifyDocumentForChat(document, rag)
          } catch (error) {
            if (error?.name === 'AbortError') throw error
            const kind = getRagStatusFailureKind(error)
            if (kind === 'unauthorized') throw error
            return {
              kind,
              document: kind === 'unavailable'
                ? unavailableChatDocument(document)
                : document,
            }
          }
        },
      )
      if (controller.signal.aborted || documentRequest.current.version !== requestVersion) return

      const pageDocuments = results
        .filter((result) => result.kind !== 'deleted')
        .map((result) => result.document)
      const merged = append
        ? mergeUniqueById(documentsRef.current, pageDocuments)
        : pageDocuments
      documentsRef.current = merged
      setDocuments(merged)

      const currentId = selectedDocumentIdRef.current
      const nextId = chooseChatDocumentId(merged, currentId)
      if (nextId !== currentId) resetConversationState()
      selectedDocumentIdRef.current = nextId
      setSelectedDocumentId(nextId)
      setDocumentsState((current) => ({
        ...current,
        loading: false,
        loadingMore: false,
        error: null,
        loadMoreError: null,
        page: requestedPage,
        totalPages: page.total_pages,
        total: page.total,
        deletedCount: (append ? current.deletedCount : 0)
          + results.filter((result) => result.kind === 'deleted').length,
      }))
    } catch (error) {
      if (error?.name === 'AbortError') return
      if (documentRequest.current.version !== requestVersion) return
      const message = handleRequestError(error)
      if (append) {
        setDocumentsState((current) => ({
          ...current,
          loadingMore: false,
          loadMoreError: message,
        }))
        return
      }
      documentsRef.current = []
      setDocuments([])
      selectedDocumentIdRef.current = null
      setSelectedDocumentId(null)
      setDocumentsState((current) => ({
        ...current,
        loading: false,
        loadingMore: false,
        error: message,
      }))
    }
  }, [accessToken, handleRequestError, resetConversationState])

  useEffect(() => {
    if (deepLink.kind !== 'none') return undefined
    const timer = window.setTimeout(() => loadDocumentPage(1), 0)
    return () => {
      window.clearTimeout(timer)
      documentRequest.current.controller?.abort()
    }
  }, [deepLink.kind, loadDocumentPage])

  const loadSessions = useCallback(async (documentId, offset = 0, append = false) => {
    const version = sessionRequest.current.version + 1
    sessionRequest.current.controller?.abort()
    const controller = new AbortController()
    sessionRequest.current = { version, controller }
    setSessionsState({ loading: true, error: null })
    try {
      const response = validatePage(
        await getChatSessions(documentId, SESSION_PAGE_SIZE, offset, {
          accessToken,
          signal: controller.signal,
        }),
        SESSION_PAGE_SIZE,
        offset,
      )
      if (
        controller.signal.aborted
        || sessionRequest.current.version !== version
        || selectedDocumentIdRef.current !== documentId
      ) return
      setSessions((current) => append ? mergeUniqueById(current, response.items) : response.items)
      setSessionTotal(response.total)
      setSessionFetchedCount((current) => append ? current + response.items.length : response.items.length)
      setSessionsState({ loading: false, error: null })
    } catch (error) {
      if (error?.name === 'AbortError') return
      if (sessionRequest.current.version !== version) return
      if (error instanceof ApiHttpError && error.status === 404) {
        removeDeletedDocument(documentId)
      }
      setSessionsState({ loading: false, error: handleRequestError(error) })
    }
  }, [accessToken, handleRequestError, removeDeletedDocument])

  const loadMessages = useCallback(async (
    sessionId,
    beforeSequenceNo = null,
    prepend = false,
  ) => {
    if (prepend && messageRequest.current.loadingMore) return
    const version = messageRequest.current.version + 1
    messageRequest.current.controller?.abort()
    const controller = new AbortController()
    messageRequest.current = { version, controller, loadingMore: prepend }
    setMessagesState({
      loading: !prepend,
      loadingMore: prepend,
      error: null,
    })
    try {
      const response = validateChatMessageCursorPage(
        await getChatMessagesCursor(sessionId, beforeSequenceNo, MESSAGE_PAGE_SIZE, {
          accessToken,
          signal: controller.signal,
        }),
        sessionId,
        MESSAGE_PAGE_SIZE,
      )
      if (
        controller.signal.aborted
        || !isChatResponseCurrent({
          requestVersion: version,
          currentRequestVersion: messageRequest.current.version,
          sessionId,
          currentSessionId: selectedSessionIdRef.current,
        })
      ) return

      if (prepend && threadRef.current) {
        pendingScrollRestore.current = {
          sessionId,
          previousScrollTop: threadRef.current.scrollTop,
          previousScrollHeight: threadRef.current.scrollHeight,
        }
        shouldAutoScroll.current = false
      }
      setMessages((current) => prepend
        ? mergeChatMessages(response.items, current)
        : mergeChatMessages([], response.items))
      setMessageCursor({
        hasMore: response.has_more,
        nextBeforeSequenceNo: response.next_before_sequence_no,
      })
      setMessagesState({ loading: false, loadingMore: false, error: null })
    } catch (error) {
      if (error?.name === 'AbortError') return
      if (messageRequest.current.version !== version) return
      if (error instanceof ApiHttpError && error.status === 404) {
        removeDeletedSession(sessionId)
      }
      setMessagesState({
        loading: false,
        loadingMore: false,
        error: handleRequestError(error),
      })
    } finally {
      if (messageRequest.current.version === version) {
        messageRequest.current.loadingMore = false
      }
    }
  }, [accessToken, handleRequestError, removeDeletedSession])

  const restoreDeepLinkedConversation = useCallback(async (target) => {
    const version = deepLinkRequest.current.version + 1
    deepLinkRequest.current.controller?.abort()
    documentRequest.current.version += 1
    documentRequest.current.controller?.abort()
    sessionRequest.current.version += 1
    sessionRequest.current.controller?.abort()
    const controller = new AbortController()
    deepLinkRequest.current = { version, controller }

    resetConversationState()
    selectedDocumentIdRef.current = null
    setSelectedDocumentId(null)
    setDeepLinkState((current) => ({
      ...current,
      loading: true,
      error: null,
    }))
    setDocumentsState((current) => ({
      ...current,
      loading: true,
      loadingMore: false,
      error: null,
      loadMoreError: null,
    }))

    const requestIsCurrent = () => isChatDeepLinkRequestCurrent({
      requestVersion: version,
      currentRequestVersion: deepLinkRequest.current.version,
      aborted: controller.signal.aborted,
    })

    try {
      const [documentPage, documentDetail] = await Promise.all([
        getDocuments({
          accessToken,
          page: 1,
          pageSize: DOCUMENT_PAGE_SIZE,
          signal: controller.signal,
        }),
        getDocumentDetail(target.documentId, {
          accessToken,
          signal: controller.signal,
        }),
      ])
      if (
        !documentPage
        || !Array.isArray(documentPage.items)
        || documentPage.page !== 1
        || !Number.isInteger(documentPage.total_pages)
        || documentPage.total_pages < 0
        || !Number.isInteger(documentPage.total)
        || documentPage.total < 0
        || documentDetail?.id !== target.documentId
      ) {
        throw new TypeError('Phản hồi tài liệu không hợp lệ.')
      }

      const candidateDocuments = mergeDeepLinkedDocument(
        documentPage.items,
        documentDetail,
      )
      const statusResults = await mapWithConcurrency(
        candidateDocuments,
        MAX_CONCURRENT_STATUS_REQUESTS,
        async (document) => {
          try {
            const rag = await getDocumentRagStatus(document.id, {
              accessToken,
              signal: controller.signal,
            })
            return classifyDocumentForChat(document, rag)
          } catch (error) {
            if (error?.name === 'AbortError') throw error
            const kind = getRagStatusFailureKind(error)
            if (kind === 'unauthorized') throw error
            return {
              kind,
              document: kind === 'unavailable'
                ? unavailableChatDocument(document)
                : document,
            }
          }
        },
      )
      if (!requestIsCurrent()) return

      const resolvedDocuments = statusResults
        .filter((result) => result.kind !== 'deleted')
        .map((result) => result.document)
      const targetDocument = resolvedDocuments.find(
        (document) => document.id === target.documentId,
      )
      if (!isChatReadyDocument(targetDocument)) {
        throw new ChatDeepLinkError(
          'Tài liệu chưa sẵn sàng hỏi đáp, không còn tồn tại hoặc đang được xóa.',
          'document_unavailable',
        )
      }

      const sessionPages = new Map()
      const fetchSessionPage = async (offset) => {
        if (sessionPages.has(offset)) return sessionPages.get(offset)
        const page = validatePage(
          await getChatSessions(target.documentId, SESSION_PAGE_SIZE, offset, {
            accessToken,
            signal: controller.signal,
          }),
          SESSION_PAGE_SIZE,
          offset,
        )
        sessionPages.set(offset, page)
        return page
      }

      let resolvedSessions
      let selectedSession = null
      let resolvedSessionTotal
      let resolvedSessionFetchedCount
      if (target.sessionId) {
        const resolution = await findSessionAcrossPages({
          targetSessionId: target.sessionId,
          pageSize: SESSION_PAGE_SIZE,
          fetchPage: fetchSessionPage,
        })
        resolvedSessions = resolution.items
        selectedSession = resolution.target
        resolvedSessionTotal = resolution.total
        resolvedSessionFetchedCount = resolution.fetchedCount
      } else {
        const firstPage = await fetchSessionPage(0)
        resolvedSessions = firstPage.items
        resolvedSessionTotal = firstPage.total
        resolvedSessionFetchedCount = firstPage.items.length
      }
      if (!requestIsCurrent()) return

      documentsRef.current = resolvedDocuments
      setDocuments(resolvedDocuments)
      selectedDocumentIdRef.current = target.documentId
      setSelectedDocumentId(target.documentId)
      setDocumentsState({
        loading: false,
        loadingMore: false,
        error: null,
        loadMoreError: null,
        page: 1,
        totalPages: documentPage.total_pages,
        total: documentPage.total,
        deletedCount: statusResults.filter((result) => result.kind === 'deleted').length,
      })
      setSessions(resolvedSessions)
      setSessionTotal(resolvedSessionTotal)
      setSessionFetchedCount(resolvedSessionFetchedCount)
      setSessionsState({ loading: false, error: null })
      skipNextSessionLoad.current = target.documentId

      if (selectedSession) {
        selectedSessionIdRef.current = selectedSession.id
        setSelectedSessionId(selectedSession.id)
        shouldAutoScroll.current = true
        loadMessages(selectedSession.id)
      }
      setDeepLinkState((current) => ({ ...current, loading: false, error: null }))
    } catch (error) {
      if (error?.name === 'AbortError' || !requestIsCurrent()) return
      const message = error instanceof ChatDeepLinkError
        ? error.message
        : handleRequestError(error)
      selectedDocumentIdRef.current = null
      selectedSessionIdRef.current = null
      setSelectedDocumentId(null)
      setSelectedSessionId(null)
      setSessions([])
      setSessionTotal(0)
      setSessionFetchedCount(0)
      setDocumentsState((current) => ({
        ...current,
        loading: false,
        loadingMore: false,
        error: message,
      }))
      setDeepLinkState((current) => ({ ...current, loading: false, error: message }))
    }
  }, [
    accessToken,
    handleRequestError,
    loadMessages,
    resetConversationState,
  ])

  useEffect(() => {
    if (deepLink.kind === 'none') {
      // URL removal resets only deep-link diagnostics; data loading is handled separately.
      // oxlint-disable-next-line react/set-state-in-effect
      setDeepLinkState((current) => (
        current.loading || current.error
          ? { ...current, loading: false, error: null }
          : current
      ))
      return undefined
    }
    if (skipDeepLinkSearch.current === currentSearch) {
      skipDeepLinkSearch.current = null
      return undefined
    }
    if (deepLink.kind === 'invalid') {
      deepLinkRequest.current.version += 1
      deepLinkRequest.current.controller?.abort()
      resetConversationState()
      selectedDocumentIdRef.current = null
      setSelectedDocumentId(null)
      const message = 'Liên kết cuộc trò chuyện không hợp lệ.'
      setDocumentsState((current) => ({
        ...current,
        loading: false,
        loadingMore: false,
        error: message,
      }))
      setDeepLinkState((current) => ({ ...current, loading: false, error: message }))
      return undefined
    }

    // Restoring URL state coordinates several authenticated API reads.
    // oxlint-disable-next-line react/set-state-in-effect
    restoreDeepLinkedConversation(deepLink)
    return () => deepLinkRequest.current.controller?.abort()
  }, [
    currentSearch,
    deepLink,
    deepLinkState.retryVersion,
    resetConversationState,
    restoreDeepLinkedConversation,
  ])

  useEffect(() => {
    if (!selectedDocumentId) return undefined
    if (skipNextSessionLoad.current === selectedDocumentId) {
      skipNextSessionLoad.current = null
      return undefined
    }
    const timer = window.setTimeout(() => loadSessions(selectedDocumentId), 0)
    return () => window.clearTimeout(timer)
  }, [loadSessions, selectedDocumentId])

  useEffect(() => () => {
    deepLinkRequest.current.controller?.abort()
    documentRequest.current.controller?.abort()
    sessionRequest.current.controller?.abort()
    messageRequest.current.controller?.abort()
    sendRequest.current.controller?.abort()
    citationRequest.current.controller?.abort()
    window.clearTimeout(copyTimer.current)
  }, [])

  useEffect(() => {
    if (!citationState.open) return undefined
    const handleKeyDown = (event) => {
      if (event.key === 'Escape') closeCitationPanel()
    }
    document.addEventListener('keydown', handleKeyDown)
    document.body.classList.add('chat-citation-modal-open')
    return () => {
      document.removeEventListener('keydown', handleKeyDown)
      document.body.classList.remove('chat-citation-modal-open')
    }
  }, [citationState.open, closeCitationPanel])

  useLayoutEffect(() => {
    const pending = pendingScrollRestore.current
    const thread = threadRef.current
    if (
      !pending
      || !thread
      || pending.sessionId !== selectedSessionIdRef.current
    ) return
    thread.scrollTop = getPrependedScrollTop({
      previousScrollTop: pending.previousScrollTop,
      previousScrollHeight: pending.previousScrollHeight,
      nextScrollHeight: thread.scrollHeight,
    })
    pendingScrollRestore.current = null
  }, [messages])

  useEffect(() => {
    if (shouldAutoScroll.current) {
      conversationEnd.current?.scrollIntoView({ block: 'end', behavior: 'smooth' })
    }
  }, [isAnswering, messages])

  const changeDocument = (event) => {
    const id = Number(event.target.value)
    const document = documentsRef.current.find((item) => item.id === id)
    if (
      !Number.isInteger(id)
      || !isChatReadyDocument(document)
      || id === selectedDocumentIdRef.current
    ) return
    resetConversationState()
    selectedDocumentIdRef.current = id
    shouldAutoScroll.current = true
    setSelectedDocumentId(id)
    navigateToChatSelection(id)
  }

  const startNewConversation = () => {
    closeCitationPanel()
    conversationVersion.current += 1
    sendRequest.current.version += 1
    sendRequest.current.controller?.abort()
    sendRequest.current.active = false
    messageRequest.current.version += 1
    messageRequest.current.controller?.abort()
    selectedSessionIdRef.current = null
    setSelectedSessionId(null)
    setMessages([])
    setMessageCursor({ hasMore: false, nextBeforeSequenceNo: null })
    setMessagesState({ loading: false, loadingMore: false, error: null })
    pendingScrollRestore.current = null
    setQuestion('')
    setSendError(null)
    setIsAnswering(false)
    shouldAutoScroll.current = true
    if (selectedDocumentIdRef.current) {
      navigateToChatSelection(selectedDocumentIdRef.current)
    }
    inputRef.current?.focus()
  }

  const selectSession = (sessionId) => {
    if (sessionId === selectedSessionIdRef.current || isAnswering) return
    closeCitationPanel()
    conversationVersion.current += 1
    messageRequest.current.version += 1
    messageRequest.current.controller?.abort()
    selectedSessionIdRef.current = sessionId
    setSelectedSessionId(sessionId)
    setMessages([])
    setMessageCursor({ hasMore: false, nextBeforeSequenceNo: null })
    pendingScrollRestore.current = null
    setSendError(null)
    shouldAutoScroll.current = true
    loadMessages(sessionId)
    navigateToChatSelection(selectedDocumentIdRef.current, sessionId)
  }

  const openCitation = async (message, citation) => {
    const sessionId = message.session_id
    const messageId = message.id
    const documentId = selectedDocumentIdRef.current
    if (
      !Number.isInteger(sessionId)
      || !Number.isInteger(messageId)
      || !Number.isInteger(citation?.chunk_id)
      || !Number.isInteger(documentId)
    ) return

    const requestVersion = citationRequest.current.version + 1
    const requestConversationVersion = conversationVersion.current
    citationRequest.current.controller?.abort()
    const controller = new AbortController()
    citationRequest.current = { version: requestVersion, controller }
    setCitationState({ open: true, loading: true, error: null, data: null })

    const requestIsCurrent = () => isCitationRequestCurrent({
      requestVersion,
      currentRequestVersion: citationRequest.current.version,
      conversationVersion: requestConversationVersion,
      currentConversationVersion: conversationVersion.current,
      documentId,
      currentDocumentId: selectedDocumentIdRef.current,
      sessionId,
      currentSessionId: selectedSessionIdRef.current,
    })

    try {
      const response = validateCitationDetail(
        await getChatCitation(citation.chunk_id, sessionId, messageId, {
          accessToken,
          signal: controller.signal,
        }),
        { chunkId: citation.chunk_id, documentId },
      )
      if (!requestIsCurrent()) return
      setCitationState({ open: true, loading: false, error: null, data: response })
    } catch (error) {
      if (error?.name === 'AbortError' || !requestIsCurrent()) return
      setCitationState({
        open: true,
        loading: false,
        error: handleRequestError(error),
        data: null,
      })
    }
  }

  const sendQuestion = async () => {
    if (
      sendRequest.current.active
      || isAnswering
      || messagesState.loading
      || messagesState.loadingMore
      || !canAsk
    ) return
    const validationMessage = getQuestionValidationMessage(question)
    if (validationMessage) {
      setSendError(validationMessage)
      return
    }
    const cleanQuestion = question.trim()
    const documentId = selectedDocument.id
    const sessionId = selectedSessionIdRef.current
    const requestConversationVersion = conversationVersion.current
    const requestVersion = sendRequest.current.version + 1
    const controller = new AbortController()
    const pendingId = `pending-${requestVersion}`
    sendRequest.current = { version: requestVersion, controller, active: true }
    messageRequest.current.version += 1
    messageRequest.current.controller?.abort()
    setMessages((current) => [
      ...current,
      { id: pendingId, role: 'USER', content: cleanQuestion, citations: [] },
    ])
    setQuestion('')
    setSendError(null)
    setIsAnswering(true)
    shouldAutoScroll.current = true

    try {
      const response = validateAskResponse(await askDocument(
        documentId,
        cleanQuestion,
        sessionId,
        { accessToken, signal: controller.signal },
      ))
      if (
        controller.signal.aborted
        || sendRequest.current.version !== requestVersion
        || conversationVersion.current !== requestConversationVersion
        || selectedDocumentIdRef.current !== documentId
      ) return

      selectedSessionIdRef.current = response.session_id
      setSelectedSessionId(response.session_id)
      navigateToChatSelection(documentId, response.session_id, { replace: true })
      setMessages((current) => [
        ...current.map((message) => message.id === pendingId ? {
          id: response.user_message_id,
          session_id: response.session_id,
          role: 'USER',
          content: cleanQuestion,
          citations: [],
        } : message),
        {
          id: response.assistant_message_id,
          session_id: response.session_id,
          role: 'ASSISTANT',
          content: response.answer_text,
          model_name: response.model_name,
          citations: response.citations,
        },
      ])
      loadSessions(documentId)
    } catch (error) {
      if (error?.name === 'AbortError') return
      if (
        sendRequest.current.version !== requestVersion
        || conversationVersion.current !== requestConversationVersion
      ) return
      if (error instanceof ApiHttpError && error.status === 404) {
        if (sessionId) removeDeletedSession(sessionId)
        else removeDeletedDocument(documentId)
      }
      setMessages((current) => current.filter((message) => message.id !== pendingId))
      setQuestion(cleanQuestion)
      setSendError(handleRequestError(error))
    } finally {
      if (sendRequest.current.version === requestVersion) {
        sendRequest.current.active = false
        setIsAnswering(false)
      }
    }
  }

  const handleComposerKeyDown = (event) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      sendQuestion()
    }
  }

  const copyAnswer = async (message) => {
    try {
      await navigator.clipboard.writeText(message.content)
    } catch {
      const textArea = document.createElement('textarea')
      textArea.value = message.content
      textArea.style.position = 'fixed'
      textArea.style.opacity = '0'
      document.body.appendChild(textArea)
      textArea.select()
      document.execCommand('copy')
      textArea.remove()
    }
    setCopiedId(message.id)
    window.clearTimeout(copyTimer.current)
    copyTimer.current = window.setTimeout(() => setCopiedId(null), 1800)
  }

  const handleThreadScroll = () => {
    const thread = threadRef.current
    if (!thread) return
    shouldAutoScroll.current = (
      thread.scrollHeight - thread.scrollTop - thread.clientHeight < 90
    )
  }

  const currentQuestionLength = question.length
  const questionInvalid = Boolean(getQuestionValidationMessage(question))
  const hasMoreSessions = sessionFetchedCount < sessionTotal
  const hasMoreMessages = messageCursor.hasMore
    && Number.isInteger(messageCursor.nextBeforeSequenceNo)
  const hasMoreDocuments = documentsState.page < documentsState.totalPages

  return (
    <div className="app-shell">
      <Sidebar isOpen={isSidebarOpen} onClose={onCloseSidebar} />
      <button
        className={`sidebar-overlay ${isSidebarOpen ? 'sidebar-overlay--visible' : ''}`}
        type="button"
        onClick={onCloseSidebar}
        aria-label="Đóng thanh điều hướng"
        tabIndex={isSidebarOpen ? 0 : -1}
      />

      <div className="app-main">
        <Header title="Hỏi đáp AI" onOpenSidebar={onOpenSidebar} />
        <main className="main-content chat-page">
          <div className="chat-page__heading">
            <p>Trò chuyện với tài liệu</p>
            <h1>Hỏi đáp AI</h1>
            <span>Đặt câu hỏi và nhận câu trả lời có trích dẫn từ tài liệu học tập đã lập chỉ mục.</span>
          </div>

          <div className="chat-workspace">
            <aside className="chat-sidebar-panel" aria-label="Tài liệu và lịch sử hội thoại">
              <div className="chat-panel-heading">
                <div className="chat-panel-heading__icon"><Icon name="documents" size={20} /></div>
                <div><h2>Tài liệu tham chiếu</h2><p>Kiểm tra trạng thái theo từng trang, 20 tài liệu mỗi lần.</p></div>
              </div>

              {documentsState.loading ? (
                <div className="chat-panel-state" role="status"><span className="chat-spinner" />Đang tải tài liệu...</div>
              ) : documentsState.error ? (
                <div className="chat-panel-state chat-panel-state--error" role="alert">
                  <span>{documentsState.error}</span>
                  <button
                    type="button"
                    onClick={() => {
                      if (deepLink.kind === 'valid') {
                        setDeepLinkState((current) => ({
                          ...current,
                          retryVersion: current.retryVersion + 1,
                        }))
                      } else if (deepLink.kind === 'invalid') {
                        navigate('/chat')
                      } else {
                        loadDocumentPage(1)
                      }
                    }}
                  >
                    {deepLink.kind === 'invalid' ? 'Mở trang Chat' : 'Thử lại'}
                  </button>
                </div>
              ) : documents.length === 0 && !hasMoreDocuments ? (
                <div className="chat-panel-state">
                  <Icon name="library" size={24} />
                  <strong>Chưa có tài liệu sẵn sàng</strong>
                  <span>Hãy xử lý và lập chỉ mục AI cho tài liệu trước.</span>
                  <a href="/documents">Đến trang Tài liệu</a>
                </div>
              ) : (
                <>
                  <label className="chat-document-select">
                    <span>Chọn tài liệu</span>
                    <div>
                      <select value={selectedDocumentId ?? ''} onChange={changeDocument}>
                        {!selectedDocumentId && <option value="">Chưa có tài liệu sẵn sàng</option>}
                        {documents.map((document) => (
                          <option
                            value={document.id}
                            disabled={!isChatReadyDocument(document)}
                            key={document.id}
                          >{document.title} — {getChatDocumentStatusLabel(document)}</option>
                        ))}
                      </select>
                      <Icon name="chevronDown" size={17} />
                    </div>
                  </label>

                  {selectedDocument && (
                    <div className="chat-selected-document">
                      <div className={`chat-selected-document__file chat-selected-document__file--${selectedDocument.file_type?.toLowerCase()}`}>
                        <Icon name="file" size={25} /><span>{selectedDocument.file_type}</span>
                      </div>
                      <div className="chat-selected-document__copy">
                        <h3>{selectedDocument.title}</h3>
                        <p>{selectedDocument.original_filename}</p>
                        <span><i />Sẵn sàng hỏi đáp · {selectedDocument.chunk_count} đoạn</span>
                      </div>
                    </div>
                  )}

                  {documentStatusMessages.length > 0 && (
                    <div className="chat-document-notices" role="status" aria-live="polite">
                      {documentStatusMessages.map((message) => <p key={message}>{message}</p>)}
                    </div>
                  )}

                  {documentsState.loadMoreError && (
                    <p className="chat-inline-error chat-document-load-error" role="alert">
                      {documentsState.loadMoreError}
                    </p>
                  )}

                  {hasMoreDocuments && (
                    <button
                      className="chat-load-more chat-load-more--documents"
                      type="button"
                      onClick={() => loadDocumentPage(documentsState.page + 1, true)}
                      disabled={documentsState.loadingMore || isAnswering}
                    >
                      {documentsState.loadingMore ? 'Đang tải thêm...' : 'Tải thêm tài liệu'}
                    </button>
                  )}

                  {documentsState.total > 0 && (
                    <p className="chat-document-page-info">
                      Đã kiểm tra {Math.min(documentsState.page * DOCUMENT_PAGE_SIZE, documentsState.total).toLocaleString('vi-VN')} / {documentsState.total.toLocaleString('vi-VN')} tài liệu
                    </p>
                  )}
                </>
              )}

              <div className="chat-history-heading">
                <div><h2>Lịch sử hội thoại</h2><span>{sessionTotal} cuộc trò chuyện</span></div>
                <button type="button" onClick={startNewConversation} disabled={!selectedDocument || isAnswering}>
                  <Icon name="chat" size={15} />Cuộc trò chuyện mới
                </button>
              </div>

              <div className="chat-session-list">
                {sessionsState.error && <p className="chat-inline-error" role="alert">{sessionsState.error}</p>}
                {!sessionsState.loading && !sessionsState.error && sessions.length === 0 && selectedDocument && (
                  <p className="chat-session-empty">Chưa có cuộc trò chuyện nào với tài liệu này.</p>
                )}
                {sessions.map((session) => (
                  <button
                    className={`chat-session-item ${selectedSessionId === session.id ? 'chat-session-item--active' : ''}`}
                    type="button"
                    onClick={() => selectSession(session.id)}
                    disabled={isAnswering}
                    key={session.id}
                  >
                    <Icon name="chat" size={16} />
                    <span><strong>{session.title}</strong><small>{formatDateTime(session.updated_at)}</small></span>
                  </button>
                ))}
                {sessionsState.loading && <div className="chat-list-loading" role="status"><span className="chat-spinner" />Đang tải lịch sử...</div>}
                {hasMoreSessions && !sessionsState.loading && (
                  <button
                    className="chat-load-more"
                    type="button"
                    onClick={() => loadSessions(selectedDocumentId, sessionFetchedCount, true)}
                  >Tải thêm cuộc trò chuyện</button>
                )}
              </div>
            </aside>

            <section className="chat-conversation" aria-label="Cuộc trò chuyện với AI">
              <div className="chat-conversation__topbar">
                <div className="chat-ai-mark"><Icon name="bot" size={21} /></div>
                <div>
                  <strong>Trợ lý StudyMate</strong>
                  <span><i />{canAsk ? `Đang hỏi: ${selectedDocument.title}` : 'Chọn tài liệu để bắt đầu'}</span>
                </div>
                <span className="chat-conversation__mode">RAG · Có trích dẫn</span>
              </div>

              <div
                className={`chat-thread ${messages.length === 0 ? 'chat-thread--empty' : ''}`}
                ref={threadRef}
                onScroll={handleThreadScroll}
              >
                {messagesState.loading && messages.length === 0 ? (
                  <div className="chat-thread-state" role="status"><span className="chat-spinner" />Đang tải tin nhắn...</div>
                ) : messagesState.error && messages.length === 0 ? (
                  <div className="chat-thread-state chat-thread-state--error" role="alert">
                    <Icon name="refresh" size={24} />
                    <strong>Không thể tải cuộc trò chuyện</strong>
                    <span>{messagesState.error}</span>
                    <button type="button" onClick={() => loadMessages(selectedSessionId)}>Thử lại</button>
                  </div>
                ) : messages.length === 0 ? (
                  <div className="chat-welcome">
                    <div className="chat-welcome__icon"><Icon name="sparkle" size={28} /></div>
                    <h2>{canAsk ? 'Bạn muốn tìm hiểu điều gì từ tài liệu này?' : 'Chưa có tài liệu sẵn sàng hỏi đáp'}</h2>
                    <p>{canAsk ? 'Hãy đặt câu hỏi hoặc chọn một gợi ý để bắt đầu cuộc trò chuyện.' : 'Xử lý và lập chỉ mục AI cho tài liệu tại trang Tài liệu trước khi đặt câu hỏi.'}</p>
                    {canAsk && (
                      <div className="chat-suggestions">
                        {suggestions.map((suggestion) => (
                          <button type="button" key={suggestion} onClick={() => { setQuestion(suggestion); inputRef.current?.focus() }}>
                            {suggestion}<Icon name="arrow" size={15} />
                          </button>
                        ))}
                      </div>
                    )}
                  </div>
                ) : (
                  <div className="chat-messages">
                    {messagesState.error && (
                      <p className="chat-inline-error chat-message-load-error" role="alert">
                        {messagesState.error}
                      </p>
                    )}
                    {hasMoreMessages && (
                      <button
                        className="chat-load-more chat-load-more--messages"
                        type="button"
                        onClick={() => loadMessages(
                          selectedSessionId,
                          messageCursor.nextBeforeSequenceNo,
                          true,
                        )}
                        disabled={messagesState.loadingMore || isAnswering}
                      >{messagesState.loadingMore ? 'Đang tải...' : 'Tải tin nhắn cũ hơn'}</button>
                    )}
                    {messages.map((message) => (
                      <ChatMessage
                        message={message}
                        onCopy={copyAnswer}
                        onCitationSelect={openCitation}
                        copied={copiedId === message.id}
                        userInitials={userInitials}
                        key={message.id}
                      />
                    ))}
                    {isAnswering && <TypingIndicator />}
                    <div ref={conversationEnd} />
                  </div>
                )}
              </div>

              <div className="chat-composer-wrap">
                {sendError && <p className="chat-send-error" role="alert" aria-live="assertive">{sendError}</p>}
                <div className={`chat-composer ${currentQuestionLength > MAX_CHAT_QUESTION_LENGTH ? 'chat-composer--invalid' : ''}`}>
                  <textarea
                    ref={inputRef}
                    value={question}
                    onChange={(event) => { setQuestion(event.target.value); setSendError(null) }}
                    onKeyDown={handleComposerKeyDown}
                    rows="1"
                    maxLength={MAX_CHAT_QUESTION_LENGTH}
                    placeholder={canAsk ? 'Nhập câu hỏi về tài liệu...' : 'Chọn tài liệu sẵn sàng để đặt câu hỏi'}
                    aria-label="Câu hỏi dành cho AI"
                    disabled={
                      !canAsk
                      || isAnswering
                      || messagesState.loading
                      || messagesState.loadingMore
                    }
                  />
                  <button
                    type="button"
                    onClick={sendQuestion}
                    disabled={
                      !canAsk
                      || questionInvalid
                      || isAnswering
                      || messagesState.loading
                      || messagesState.loadingMore
                    }
                    aria-label="Gửi câu hỏi"
                  >
                    <Icon name="send" size={18} /><span>{isAnswering ? 'Đang gửi' : 'Gửi'}</span>
                  </button>
                </div>
                <div className="chat-composer-meta">
                  <span>Enter để gửi · Shift + Enter để xuống dòng</span>
                  <span className={currentQuestionLength > 1800 ? 'chat-composer-count--warning' : ''}>{currentQuestionLength.toLocaleString('vi-VN')} / 2.000</span>
                </div>
              </div>
            </section>
          </div>
        </main>
      </div>
      <CitationDetailPanel state={citationState} onClose={closeCitationPanel} />
    </div>
  )
}

export default Chat
