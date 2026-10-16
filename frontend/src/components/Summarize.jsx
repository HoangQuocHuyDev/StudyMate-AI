import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react'
import { useAuth } from '../contexts/AuthContext'
import { ApiHttpError } from '../services/apiClient'
import { getDocuments, getDocumentStatus } from '../services/documentService'
import {
  generateSummary,
  getDocumentSummaries,
} from '../services/summaryService'
import { AssistantMarkdown } from './chatMarkdown'
import Header from './Header'
import Icon from './Icons'
import Sidebar from './Sidebar'
import {
  canGenerateSummary,
  buildDocumentStatusMessages,
  chooseSelectedDocumentId,
  classifyDocumentForSummary,
  copySummaryContent,
  DEFAULT_SUMMARY_TYPE,
  getSummaryErrorMessage,
  getDocumentStatusFailureKind,
  indexDocumentSummaries,
  isSummaryReadyDocument,
  isSummaryResponseCurrent,
  mergeDocumentsById,
  removeDocumentAndChooseSelection,
  SUMMARY_TYPE_OPTIONS,
  validateGeneratedSummary,
} from './summaryUi'
import './Summarize.css'

const DOCUMENT_PAGE_SIZE = 20
const MAX_CONCURRENT_STATUS_REQUESTS = 4

const EMPTY_STATUS_COUNTS = Object.freeze({
  notReady: 0,
  noChunks: 0,
  unavailable: 0,
  deleted: 0,
})

async function mapWithConcurrency(items, limit, mapper) {
  const output = new Array(items.length)
  let nextIndex = 0
  const worker = async () => {
    while (nextIndex < items.length) {
      const index = nextIndex
      nextIndex += 1
      output[index] = await mapper(items[index])
    }
  }
  const workerCount = Math.min(limit, items.length)
  await Promise.all(Array.from({ length: workerCount }, () => worker()))
  return output
}

function formatDateTime(value) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return 'Không rõ thời gian'
  return new Intl.DateTimeFormat('vi-VN', {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(date)
}

function DocumentSelector({
  disabled,
  documents,
  onChange,
  onLoadMore,
  selectedDocument,
  selectedId,
  state,
}) {
  const statusMessages = buildDocumentStatusMessages(state.statusCounts)
  const hasMore = state.page < state.totalPages

  return (
    <div className="summary-control-group">
      <div className="summary-control-heading">
        <span>01</span>
        <div><h3>Chọn tài liệu</h3><p>Chỉ tài liệu đã xử lý và có nội dung mới có thể tóm tắt.</p></div>
      </div>

      {state.loading ? (
        <div className="summary-inline-state" role="status"><i />Đang tải tài liệu...</div>
      ) : state.error ? (
        <div className="summary-inline-state summary-inline-state--error" role="alert">{state.error}</div>
      ) : (
        <>
          {documents.length === 0 ? (
            <div className="summary-inline-state summary-inline-state--empty">
              <strong>Chưa có tài liệu sẵn sàng trong các trang đã tải</strong>
              <span>Hãy xử lý tài liệu tại trang Tài liệu hoặc tải thêm để kiểm tra trang tiếp theo.</span>
              <a href="/documents">Đến trang Tài liệu</a>
            </div>
          ) : (
            <label className="summary-select">
              <Icon name="documents" size={20} />
              <select value={selectedId ?? ''} onChange={(event) => onChange(Number(event.target.value))} aria-label="Chọn tài liệu cần tóm tắt" disabled={disabled}>
                {documents.map((document) => <option value={document.id} key={document.id}>{document.title}</option>)}
              </select>
              <Icon name="chevronDown" size={18} />
            </label>
          )}

          {selectedDocument && (
            <div className="selected-document">
              <div className={`selected-document__icon selected-document__icon--${selectedDocument.file_type?.toLowerCase()}`}><Icon name="file" size={22} /></div>
              <div><strong>{selectedDocument.title}</strong><span>{selectedDocument.file_type} · {selectedDocument.chunk_count.toLocaleString('vi-VN')} đoạn</span></div>
              <span className="selected-document__ready"><i />Sẵn sàng</span>
            </div>
          )}

          {statusMessages.length > 0 && (
            <div className="summary-status-notice" role="status" aria-live="polite">
              {statusMessages.map((message) => <p key={message}>{message}</p>)}
            </div>
          )}

          {state.loadMoreError && (
            <div className="summary-inline-state summary-inline-state--error summary-load-more__error" role="alert">{state.loadMoreError}</div>
          )}

          {hasMore && (
            <button className="summary-load-more" type="button" onClick={onLoadMore} disabled={disabled || state.loadingMore}>
              {state.loadingMore ? <><i aria-hidden="true" />Đang tải thêm...</> : 'Tải thêm tài liệu'}
            </button>
          )}

          {state.total > 0 && (
            <p className="summary-page-info">Đã kiểm tra {Math.min(state.page * DOCUMENT_PAGE_SIZE, state.total).toLocaleString('vi-VN')} / {state.total.toLocaleString('vi-VN')} tài liệu</p>
          )}
        </>
      )}
    </div>
  )
}

function LengthSelector({ value, onChange, disabled, summaries }) {
  return (
    <div className="summary-control-group">
      <div className="summary-control-heading">
        <span>02</span>
        <div><h3>Độ dài bản tóm tắt</h3><p>Chọn mức độ chi tiết phù hợp với nhu cầu học tập.</p></div>
      </div>
      <div className="summary-length-options">
        {SUMMARY_TYPE_OPTIONS.map((option) => (
          <label className={value === option.id ? 'summary-length--active' : ''} key={option.id}>
            <input type="radio" name="summaryLength" value={option.id} checked={value === option.id} onChange={() => onChange(option.id)} disabled={disabled} />
            <span className="summary-length__radio" aria-hidden="true"><i /></span>
            <span className="summary-length__copy"><strong>{option.label}</strong><small>{option.description}</small><em>{summaries[option.id] ? 'Đã lưu' : option.estimate}</em></span>
          </label>
        ))}
      </div>
    </div>
  )
}

function SummaryResult({ copied, documentName, error, isGenerating, isLoading, onCopy, result, summaryType }) {
  const typeLabel = SUMMARY_TYPE_OPTIONS.find((option) => option.id === summaryType)?.label

  if (isGenerating) {
    return (
      <div className="summary-placeholder summary-placeholder--loading" role="status" aria-live="polite">
        <div className="summary-loader"><span /><span /><span /></div>
        <h3>AI đang tóm tắt tài liệu...</h3>
        <p>StudyMate AI đang phân tích nội dung. Vui lòng giữ trang này mở cho đến khi hoàn tất.</p>
        <div className="summary-progress"><span /></div>
      </div>
    )
  }

  if (isLoading) {
    return (
      <div className="summary-placeholder" role="status">
        <div className="summary-loader summary-loader--subtle"><span /><span /><span /></div>
        <h3>Đang tải bản tóm tắt đã lưu...</h3>
      </div>
    )
  }

  if (error) {
    return (
      <div className="summary-placeholder summary-placeholder--error" role="alert">
        <div className="summary-placeholder__icon"><Icon name="refresh" size={27} /></div>
        <h3>Chưa thể hoàn tất yêu cầu</h3><p>{error}</p>
      </div>
    )
  }

  if (!result) {
    return (
      <div className="summary-placeholder">
        <div className="summary-placeholder__icon"><Icon name="sparkle" size={29} /></div>
        <h3>{documentName ? `Chưa có bản ${typeLabel.toLocaleLowerCase('vi-VN')}` : 'Chưa có bản tóm tắt'}</h3>
        <p>{documentName ? 'Chọn “Tạo bản tóm tắt” để AI tạo nội dung từ tài liệu này.' : 'Chọn một tài liệu đã xử lý để xem hoặc tạo bản tóm tắt.'}</p>
      </div>
    )
  }

  return (
    <div className="summary-result">
      <div className={`summary-result__notice ${result.from_cache ? 'summary-result__notice--cache' : 'summary-result__notice--new'}`} role="status" aria-live="polite">
        <Icon name={result.from_cache ? 'history' : 'sparkle'} size={16} />
        <strong>{result.from_cache ? 'Đã tải bản tóm tắt đã lưu' : 'Đã tạo bản tóm tắt mới'}</strong>
      </div>
      <div className="summary-result__header">
        <div><p>Bản tóm tắt</p><h3>{documentName}</h3></div><span>{typeLabel}</span>
      </div>
      <div className="summary-result__meta">
        {result.model_name && <span>Mô hình AI: <strong>{result.model_name}</strong></span>}
        {result.created_at && <span>Tạo lúc: <strong>{formatDateTime(result.created_at)}</strong></span>}
      </div>
      <div className="summary-result__content chat-markdown"><AssistantMarkdown content={result.content} /></div>
      <div className="summary-result__actions">
        <button type="button" onClick={onCopy}><Icon name={copied ? 'check' : 'copy'} size={17} />{copied ? 'Đã sao chép' : 'Sao chép'}</button>
      </div>
    </div>
  )
}

function Summarize({ isSidebarOpen, onOpenSidebar, onCloseSidebar }) {
  const { accessToken } = useAuth()
  const [documents, setDocuments] = useState([])
  const [documentsState, setDocumentsState] = useState({
    loading: true,
    loadingMore: false,
    error: null,
    loadMoreError: null,
    page: 0,
    totalPages: 0,
    total: 0,
    statusCounts: { ...EMPTY_STATUS_COUNTS },
  })
  const [selectedDocumentId, setSelectedDocumentId] = useState(null)
  const [summaryType, setSummaryType] = useState(DEFAULT_SUMMARY_TYPE)
  const [summaries, setSummaries] = useState({})
  const [summaryState, setSummaryState] = useState({ loading: false, error: null })
  const [isGenerating, setIsGenerating] = useState(false)
  const [copied, setCopied] = useState(false)

  const documentRequest = useRef({ version: 0, controller: null })
  const summaryRequest = useRef({ version: 0, controller: null })
  const generateRequest = useRef({ version: 0, controller: null, active: false })
  const documentsRef = useRef([])
  const selectedDocumentIdRef = useRef(null)
  const copyTimer = useRef(null)

  const selectedDocument = useMemo(() => documents.find((document) => document.id === selectedDocumentId) ?? null, [documents, selectedDocumentId])
  const currentSummary = summaries[summaryType] ?? null

  const handleRequestError = useCallback((error) => {
    return getSummaryErrorMessage(error)
  }, [])

  const removeUnavailableDocument = useCallback((documentId) => {
    const currentId = selectedDocumentIdRef.current
    const result = removeDocumentAndChooseSelection(
      documentsRef.current,
      documentId,
      currentId,
    )
    documentsRef.current = result.documents
    setDocuments(result.documents)
    if (currentId !== documentId) return

    const nextId = result.selectedDocumentId
    selectedDocumentIdRef.current = nextId
    setSelectedDocumentId(nextId)
    setSummaryType(DEFAULT_SUMMARY_TYPE)
    setSummaries({})
    setSummaryState({ loading: Boolean(nextId), error: nextId ? null : 'Tài liệu đã bị xóa hoặc bạn không còn quyền truy cập.' })
    setCopied(false)
  }, [])

  const loadDocumentPage = useCallback(async (page, append = false) => {
    const version = documentRequest.current.version + 1
    documentRequest.current.controller?.abort()
    const controller = new AbortController()
    documentRequest.current = { version, controller }

    setDocumentsState((current) => ({
      ...current,
      loading: !append,
      loadingMore: append,
      error: append ? current.error : null,
      loadMoreError: null,
      ...(append ? {} : { statusCounts: { ...EMPTY_STATUS_COUNTS } }),
    }))

    try {
      const response = await getDocuments({
        accessToken,
        page,
        pageSize: DOCUMENT_PAGE_SIZE,
        signal: controller.signal,
      })
      if (
        !response
        || !Array.isArray(response.items)
        || response.page !== page
        || !Number.isInteger(response.total_pages)
        || response.total_pages < 0
        || !Number.isInteger(response.total)
        || response.total < 0
      ) {
        throw new TypeError('Phản hồi danh sách tài liệu không hợp lệ.')
      }

      const results = await mapWithConcurrency(
        response.items,
        MAX_CONCURRENT_STATUS_REQUESTS,
        async (document) => {
          try {
            const status = await getDocumentStatus(document.id, {
              accessToken,
              signal: controller.signal,
            })
            return classifyDocumentForSummary(document, status)
          } catch (error) {
            if (error?.name === 'AbortError') throw error
            const failureKind = getDocumentStatusFailureKind(error)
            if (failureKind === 'unauthorized') throw error
            return {
              kind: failureKind,
              document,
            }
          }
        },
      )
      if (controller.signal.aborted || documentRequest.current.version !== version) return

      const readyDocuments = results
        .filter((result) => result.kind === 'ready')
        .map((result) => result.document)
      const counts = { ...EMPTY_STATUS_COUNTS }
      for (const result of results) {
        if (result.kind === 'not_ready') counts.notReady += 1
        if (result.kind === 'no_chunks') counts.noChunks += 1
        if (result.kind === 'unavailable') counts.unavailable += 1
        if (result.kind === 'deleted') counts.deleted += 1
      }

      const mergedDocuments = append
        ? mergeDocumentsById(documentsRef.current, readyDocuments)
        : readyDocuments
      documentsRef.current = mergedDocuments
      setDocuments(mergedDocuments)

      const currentId = selectedDocumentIdRef.current
      const nextId = chooseSelectedDocumentId(mergedDocuments, currentId)
      if (nextId !== currentId) {
        setSummaries({})
        setSummaryState({ loading: Boolean(nextId), error: null })
        setSummaryType(DEFAULT_SUMMARY_TYPE)
        setCopied(false)
      }
      selectedDocumentIdRef.current = nextId
      setSelectedDocumentId(nextId)
      setDocumentsState((current) => ({
        loading: false,
        loadingMore: false,
        error: null,
        loadMoreError: null,
        page: response.page,
        totalPages: response.total_pages,
        total: response.total,
        statusCounts: append
          ? {
              notReady: current.statusCounts.notReady + counts.notReady,
              noChunks: current.statusCounts.noChunks + counts.noChunks,
              unavailable: current.statusCounts.unavailable + counts.unavailable,
              deleted: current.statusCounts.deleted + counts.deleted,
            }
          : counts,
      }))
    } catch (error) {
      if (error?.name === 'AbortError' || documentRequest.current.version !== version) return
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
  }, [accessToken, handleRequestError])

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
    let active = true
    queueMicrotask(() => {
      if (active) loadDocumentPage(1)
    })
    return () => {
      active = false
      documentRequest.current.controller?.abort()
    }
  }, [loadDocumentPage])

  useEffect(() => {
    summaryRequest.current.version += 1
    summaryRequest.current.controller?.abort()
    if (!selectedDocumentId) return undefined

    const version = summaryRequest.current.version
    const controller = new AbortController()
    summaryRequest.current.controller = controller

    async function loadSummaries() {
      setSummaryState({ loading: true, error: null })
      try {
        const response = await getDocumentSummaries(selectedDocumentId, { accessToken, signal: controller.signal })
        if (controller.signal.aborted || !isSummaryResponseCurrent({ requestVersion: version, currentRequestVersion: summaryRequest.current.version, documentId: selectedDocumentId, currentDocumentId: selectedDocumentIdRef.current })) return
        setSummaries(indexDocumentSummaries(response, selectedDocumentId))
        setSummaryState({ loading: false, error: null })
      } catch (error) {
        if (error?.name === 'AbortError' || !isSummaryResponseCurrent({ requestVersion: version, currentRequestVersion: summaryRequest.current.version, documentId: selectedDocumentId, currentDocumentId: selectedDocumentIdRef.current })) return
        if (error instanceof ApiHttpError && error.status === 404) {
          removeUnavailableDocument(selectedDocumentId)
          return
        }
        setSummaryState({ loading: false, error: handleRequestError(error) })
      }
    }
    loadSummaries()
    return () => controller.abort()
  }, [accessToken, handleRequestError, removeUnavailableDocument, selectedDocumentId])

  useEffect(() => () => {
    documentRequest.current.controller?.abort()
    summaryRequest.current.controller?.abort()
    generateRequest.current.controller?.abort()
    window.clearTimeout(copyTimer.current)
  }, [])

  const changeDocument = (documentId) => {
    if (documentId === selectedDocumentIdRef.current) return
    generateRequest.current.version += 1
    generateRequest.current.controller?.abort()
    generateRequest.current.active = false
    setIsGenerating(false)
    selectedDocumentIdRef.current = documentId
    setSelectedDocumentId(documentId)
    setSummaryType(DEFAULT_SUMMARY_TYPE)
    setSummaries({})
    setSummaryState({ loading: true, error: null })
    setCopied(false)
  }

  const changeSummaryType = (nextType) => {
    setSummaryType(nextType)
    setSummaryState((current) => ({ ...current, error: null }))
    setCopied(false)
  }

  const submitSummary = async () => {
    if (generateRequest.current.active || isGenerating || !isSummaryReadyDocument(selectedDocument) || currentSummary) return
    const documentId = selectedDocument.id
    const requestedType = summaryType
    const version = generateRequest.current.version + 1
    const controller = new AbortController()
    generateRequest.current = { version, controller, active: true }
    setSummaryState({ loading: false, error: null })
    setIsGenerating(true)
    setCopied(false)

    try {
      const response = validateGeneratedSummary(await generateSummary(documentId, requestedType, { accessToken, signal: controller.signal }), documentId, requestedType)
      if (controller.signal.aborted || !isSummaryResponseCurrent({ requestVersion: version, currentRequestVersion: generateRequest.current.version, documentId, currentDocumentId: selectedDocumentIdRef.current })) return
      setSummaries((current) => ({ ...current, [requestedType]: response }))
    } catch (error) {
      if (error?.name === 'AbortError' || !isSummaryResponseCurrent({ requestVersion: version, currentRequestVersion: generateRequest.current.version, documentId, currentDocumentId: selectedDocumentIdRef.current })) return
      if (error instanceof ApiHttpError && error.status === 404) {
        removeUnavailableDocument(documentId)
        return
      }
      setSummaryState({ loading: false, error: handleRequestError(error) })
    } finally {
      if (generateRequest.current.version === version) {
        generateRequest.current.active = false
        setIsGenerating(false)
      }
    }
  }

  const copySummary = async () => {
    if (!currentSummary) return
    try {
      await copySummaryContent(currentSummary.content)
      setCopied(true)
      window.clearTimeout(copyTimer.current)
      copyTimer.current = window.setTimeout(() => setCopied(false), 1800)
    } catch {
      setSummaryState({ loading: false, error: 'Trình duyệt không thể sao chép tự động. Vui lòng chọn và sao chép nội dung thủ công.' })
    }
  }

  const canGenerate = canGenerateSummary({
    document: selectedDocument,
    existingSummary: currentSummary,
    isLoading: summaryState.loading,
    requestActive: isGenerating,
  })

  return (
    <div className="app-shell">
      <Sidebar isOpen={isSidebarOpen} onClose={onCloseSidebar} />
      <button className={`sidebar-overlay ${isSidebarOpen ? 'sidebar-overlay--visible' : ''}`} type="button" onClick={onCloseSidebar} aria-label="Đóng thanh điều hướng" tabIndex={isSidebarOpen ? 0 : -1} />
      <div className="app-main">
        <Header title="Tóm tắt tài liệu" onOpenSidebar={onOpenSidebar} />
        <main className="main-content summarize-page">
          <section className="summarize-hero" aria-labelledby="summarize-title">
            <p>Trợ lý tóm tắt AI</p><h2 id="summarize-title">Tóm tắt tài liệu</h2>
            <span>Biến tài liệu dài thành kiến thức ngắn gọn, dễ hiểu với StudyMate AI.</span>
          </section>
          <div className="summarize-workspace">
            <section className="summary-settings" aria-label="Thiết lập bản tóm tắt">
              <DocumentSelector
                disabled={isGenerating}
                documents={documents}
                onChange={changeDocument}
                onLoadMore={() => loadDocumentPage(documentsState.page + 1, true)}
                selectedDocument={selectedDocument}
                selectedId={selectedDocumentId}
                state={documentsState}
              />
              <LengthSelector value={summaryType} onChange={changeSummaryType} disabled={!selectedDocument || isGenerating} summaries={summaries} />
              <button className="summary-generate" type="button" onClick={submitSummary} disabled={!canGenerate}>
                <Icon name={currentSummary ? 'check' : 'sparkle'} size={19} />
                {isGenerating ? 'Đang tóm tắt...' : currentSummary ? 'Bản tóm tắt đã có' : 'Tạo bản tóm tắt'}
              </button>
              <p className="summary-settings__note">Nội dung tài liệu sẽ được gửi tới Gemini để tạo bản tóm tắt. Mỗi chế độ có tối đa một bản được lưu.</p>
            </section>
            <section className="summary-output" aria-label="Kết quả tóm tắt">
              <SummaryResult copied={copied} documentName={selectedDocument?.title} error={summaryState.error} isGenerating={isGenerating} isLoading={summaryState.loading} onCopy={copySummary} result={currentSummary} summaryType={summaryType} />
            </section>
          </div>
        </main>
      </div>
    </div>
  )
}

export default Summarize
