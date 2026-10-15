import { useCallback, useEffect, useRef, useState } from 'react'
import { useAuth } from '../contexts/AuthContext'
import { useNavigation } from '../navigation/NavigationContext'
import { ApiHttpError } from '../services/apiClient'
import { getChatHistory } from '../services/chatService'
import Header from './Header'
import { buildChatDeepLinkUrl } from './chatDeepLink'
import {
  formatHistoryDateTime,
  getHistoryErrorMessage,
  getHistoryPreview,
  getHistoryViewState,
  HISTORY_PAGE_SIZE,
  HISTORY_SEARCH_MAX_LENGTH,
  isHistoryResponseCurrent,
  mergeHistorySessions,
  validateHistoryResponse,
} from './historyUi'
import Icon from './Icons'
import Sidebar from './Sidebar'
import './History.css'

const timeFilters = [
  { id: '', label: 'Tất cả' },
  { id: 'today', label: 'Hôm nay' },
  { id: 'week', label: '7 ngày qua' },
  { id: 'month', label: '30 ngày qua' },
]

function HistoryItem({ conversation, onOpen }) {
  return (
    <article className="history-item" onClick={() => onOpen(conversation)}>
      <div className="history-item__icon" aria-hidden="true">
        <Icon name="chat" size={21} />
      </div>
      <div className="history-item__content">
        <div className="history-item__heading">
          <h3>{conversation.title}</h3>
          <time dateTime={conversation.updated_at}>
            {formatHistoryDateTime(conversation.updated_at)}
          </time>
        </div>
        <div className="history-item__document">
          <Icon name="file" size={14} />
          <span>{conversation.document_title}</span>
          <i>{conversation.file_type}</i>
        </div>
        <p className={conversation.last_message_preview ? '' : 'history-item__preview--empty'}>
          {getHistoryPreview(conversation.last_message_preview)}
        </p>
      </div>
      <button
        className="history-item__open"
        type="button"
        onClick={(event) => {
          event.stopPropagation()
          onOpen(conversation)
        }}
        aria-label={`Mở cuộc trò chuyện ${conversation.title}`}
      >
        Mở cuộc hội thoại <Icon name="arrow" size={15} />
      </button>
    </article>
  )
}

function History({ isSidebarOpen, onOpenSidebar, onCloseSidebar }) {
  const { accessToken, logout } = useAuth()
  const { navigate } = useNavigation()
  const [query, setQuery] = useState('')
  const [debouncedQuery, setDebouncedQuery] = useState('')
  const [period, setPeriod] = useState('')
  const [conversations, setConversations] = useState([])
  const [total, setTotal] = useState(0)
  const [fetchedCount, setFetchedCount] = useState(0)
  const [loading, setLoading] = useState(true)
  const [loadingMore, setLoadingMore] = useState(false)
  const [error, setError] = useState('')
  const [loadMoreError, setLoadMoreError] = useState('')
  const requestRef = useRef({ controller: null, id: 0 })
  const criteriaRef = useRef('')
  const loadMoreInFlightRef = useRef(false)

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

  useEffect(() => {
    const timer = window.setTimeout(() => setDebouncedQuery(query.trim()), 350)
    return () => window.clearTimeout(timer)
  }, [query])

  const loadHistory = useCallback(async ({ offset = 0, append = false } = {}) => {
    if (append && loadMoreInFlightRef.current) return
    loadMoreInFlightRef.current = append
    const requestCriteria = `${debouncedQuery}\u0000${period}`
    const requestId = requestRef.current.id + 1
    requestRef.current.controller?.abort()
    const controller = new AbortController()
    requestRef.current = { controller, id: requestId }
    criteriaRef.current = requestCriteria

    if (append) {
      setLoadingMore(true)
      setLoadMoreError('')
    } else {
      setLoading(true)
      setLoadingMore(false)
      setError('')
      setLoadMoreError('')
    }

    try {
      const response = await getChatHistory({
        limit: HISTORY_PAGE_SIZE,
        offset,
        search: debouncedQuery,
        period,
      }, {
        accessToken,
        signal: controller.signal,
      })
      const page = validateHistoryResponse(response, HISTORY_PAGE_SIZE, offset)
      if (!isHistoryResponseCurrent(
        requestId,
        requestRef.current.id,
        requestCriteria,
        criteriaRef.current,
      )) return

      setConversations((current) => (
        append ? mergeHistorySessions(current, page.items) : page.items
      ))
      setFetchedCount((current) => (
        append ? current + page.items.length : page.items.length
      ))
      setTotal(page.total)
      setError('')
      setLoadMoreError('')
    } catch (requestError) {
      if (requestError?.name === 'AbortError') return
      if (!isHistoryResponseCurrent(
        requestId,
        requestRef.current.id,
        requestCriteria,
        criteriaRef.current,
      )) return

      const message = getHistoryErrorMessage(requestError)
      if (append) setLoadMoreError(message)
      else setError(message)
      if (requestError instanceof ApiHttpError && requestError.status === 401) logout()
    } finally {
      if (append && requestRef.current.id === requestId) {
        loadMoreInFlightRef.current = false
      }
      if (isHistoryResponseCurrent(
        requestId,
        requestRef.current.id,
        requestCriteria,
        criteriaRef.current,
      )) {
        if (append) setLoadingMore(false)
        else setLoading(false)
      }
    }
  }, [accessToken, debouncedQuery, logout, period])

  useEffect(() => {
    // Fetching is the external synchronization performed by this effect.
    // oxlint-disable-next-line react/set-state-in-effect
    loadHistory()
    return () => requestRef.current.controller?.abort()
  }, [loadHistory])

  const hasFilters = Boolean(debouncedQuery || period)
  const viewState = getHistoryViewState({
    itemCount: conversations.length,
    loading,
    error,
    hasFilters,
  })
  const hasMore = fetchedCount < total

  const invalidatePendingRequest = () => {
    requestRef.current.controller?.abort()
    requestRef.current = {
      controller: null,
      id: requestRef.current.id + 1,
    }
    criteriaRef.current = 'pending'
    loadMoreInFlightRef.current = false
    setLoadingMore(false)
  }

  const handleQueryChange = (event) => {
    invalidatePendingRequest()
    setQuery(event.target.value.slice(0, HISTORY_SEARCH_MAX_LENGTH))
  }

  const handlePeriodChange = (nextPeriod) => {
    if (nextPeriod === period) return
    invalidatePendingRequest()
    setPeriod(nextPeriod)
  }

  const resetFilters = () => {
    invalidatePendingRequest()
    setQuery('')
    setDebouncedQuery('')
    setPeriod('')
  }

  const openConversation = (conversation) => {
    navigate(buildChatDeepLinkUrl(
      conversation.document_id,
      conversation.session_id,
    ))
  }

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
        <Header title="Lịch sử trò chuyện" onOpenSidebar={onOpenSidebar} />
        <main className="main-content history-page">
          <section className="history-hero" aria-labelledby="history-title">
            <p>Kho kiến thức đã khám phá</p>
            <h1 id="history-title">Lịch sử trò chuyện</h1>
            <span>Xem lại các cuộc trò chuyện thật đã được lưu cùng tài liệu của bạn.</span>
          </section>

          <section className="history-toolbar" aria-label="Tìm kiếm và lọc lịch sử">
            <label className="history-search">
              <Icon name="search" size={19} />
              <input
                type="search"
                value={query}
                maxLength={HISTORY_SEARCH_MAX_LENGTH}
                onChange={handleQueryChange}
                placeholder="Tìm theo cuộc trò chuyện hoặc tài liệu..."
                aria-label="Tìm kiếm theo tiêu đề cuộc trò chuyện hoặc tài liệu"
              />
              {query && (
                <button type="button" onClick={() => {
                  invalidatePendingRequest()
                  setQuery('')
                }} aria-label="Xóa nội dung tìm kiếm">
                  <Icon name="close" size={16} />
                </button>
              )}
            </label>
            <div className="history-filters" aria-label="Lọc theo thời gian">
              {timeFilters.map((filter) => (
                <button
                  className={period === filter.id ? 'history-filter--active' : ''}
                  type="button"
                  key={filter.id || 'all'}
                  onClick={() => handlePeriodChange(filter.id)}
                  aria-pressed={period === filter.id}
                >
                  {filter.label}
                </button>
              ))}
            </div>
          </section>

          <section className="history-list" aria-labelledby="history-list-title" aria-busy={loading || loadingMore}>
            <div className="history-list__heading">
              <h2 id="history-list-title">Các cuộc trò chuyện</h2>
              <span>{total} phiên</span>
            </div>

            {error && conversations.length > 0 && (
              <div className="history-inline-error" role="alert">
                <span>{error}</span>
                <button type="button" onClick={() => loadHistory()}>Thử lại</button>
              </div>
            )}

            {viewState === 'loading' && (
              <div className="history-state" role="status">
                <span className="history-spinner" aria-hidden="true" />
                <p>Đang tải lịch sử trò chuyện...</p>
              </div>
            )}

            {viewState === 'error' && (
              <div className="history-state history-state--error" role="alert">
                <div><Icon name="history" size={28} /></div>
                <h3>Không thể tải lịch sử</h3>
                <p>{error}</p>
                <button type="button" onClick={() => loadHistory()}>Thử lại</button>
              </div>
            )}

            {(viewState === 'empty' || viewState === 'filtered-empty') && (
              <div className="history-empty">
                <div><Icon name="history" size={29} /></div>
                <h3>
                  {viewState === 'filtered-empty'
                    ? 'Không tìm thấy cuộc trò chuyện phù hợp'
                    : 'Bạn chưa có lịch sử trò chuyện'}
                </h3>
                <p>
                  {viewState === 'filtered-empty'
                    ? 'Hãy thử từ khóa khác hoặc thay đổi khoảng thời gian.'
                    : 'Các phiên hỏi đáp với tài liệu sẽ xuất hiện tại đây sau khi được lưu.'}
                </p>
                {viewState === 'filtered-empty' && (
                  <button type="button" onClick={resetFilters}>Xóa bộ lọc</button>
                )}
              </div>
            )}

            {viewState === 'ready' && (
              <>
                <div className="history-list__items">
                  {conversations.map((conversation) => (
                    <HistoryItem
                      conversation={conversation}
                      onOpen={openConversation}
                      key={conversation.session_id}
                    />
                  ))}
                </div>
                {loadMoreError && (
                  <div className="history-load-more-error" role="alert">
                    <span>{loadMoreError}</span>
                    <button
                      type="button"
                      onClick={() => loadHistory({ offset: fetchedCount, append: true })}
                    >
                      Thử tải lại
                    </button>
                  </div>
                )}
                {hasMore && !loadMoreError && (
                  <div className="history-load-more">
                    <button
                      type="button"
                      disabled={loadingMore}
                      onClick={() => loadHistory({ offset: fetchedCount, append: true })}
                    >
                      {loadingMore ? 'Đang tải thêm...' : 'Tải thêm'}
                    </button>
                  </div>
                )}
              </>
            )}
          </section>
        </main>
      </div>
    </div>
  )
}

export default History
