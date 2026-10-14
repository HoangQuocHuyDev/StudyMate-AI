import {
  useCallback,
  useEffect,
  useId,
  useMemo,
  useReducer,
  useRef,
  useState,
} from 'react'
import { useAuth } from '../contexts/AuthContext'
import { useNavigation } from '../navigation/NavigationContext'
import {
  ApiConfigurationError,
  ApiHttpError,
  ApiNetworkError,
} from '../services/apiClient'
import {
  deleteDocument,
  downloadDocument,
  getDocumentDetail,
  getDocumentRagStatus,
  getDocumentStatus,
  getDocuments,
  indexDocument,
  processDocument,
  uploadDocument,
  viewDocumentPdf,
} from '../services/documentService'
import {
  createDocumentDeletionGuard,
  decrementDocumentPagination,
  documentDeletionUiReducer,
  getDocumentDeletionErrorMessage,
  initialDocumentDeletionUiState,
  removeDocumentFromPage,
} from './documentDeletionUi'
import {
  canIndexDocument,
  getIndexingErrorMessage,
  getRagStatusPresentation,
} from './documentRagUi'
import {
  createDocumentObjectUrl,
  revokeDocumentObjectUrl,
  triggerDocumentDownload,
} from './documentFileUi'
import Header from './Header'
import Icon from './Icons'
import Sidebar from './Sidebar'
import {
  buildDocumentSearchUrl,
  getInitialDocumentSearchState,
  normalizeDocumentSearchTerm,
  parseDocumentSearch,
  shouldCommitDocumentSearch,
} from './documentSearchUrl'
import './Documents.css'

const MAX_FILE_SIZE = 10 * 1024 * 1024
const MAX_TITLE_LENGTH = 255
const DOCUMENT_PAGE_SIZE = 10
const SEARCH_DEBOUNCE_MS = 350
const MAX_CONCURRENT_STATUS_REQUESTS = 3
const ALLOWED_EXTENSIONS = new Set(['pdf', 'docx'])

const filters = ['Tất cả', 'PDF', 'DOCX']
const documentStatuses = {
  UPLOADED: { label: 'Chưa xử lý', className: 'uploaded' },
  PROCESSING: { label: 'Đang xử lý', className: 'processing' },
  READY: { label: 'Đã xử lý', className: 'complete' },
  FAILED: { label: 'Xử lý thất bại', className: 'failed' },
}

function formatFileSize(bytes) {
  if (!Number.isFinite(bytes) || bytes < 0) return 'Không rõ dung lượng'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function formatCreatedAt(value) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return 'Không rõ thời gian'

  return new Intl.DateTimeFormat('vi-VN', {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(date)
}

function formatMetric(value, unit) {
  if (!Number.isInteger(value) || value < 0) return 'Chưa có'
  return `${new Intl.NumberFormat('vi-VN').format(value)} ${unit}`
}

function getFileValidationMessage(file) {
  if (!file) return null

  const extension = file.name.split('.').pop()?.toLocaleLowerCase('en')
  if (!extension || !ALLOWED_EXTENSIONS.has(extension)) {
    return 'Định dạng không được hỗ trợ. Vui lòng chọn file PDF hoặc DOCX.'
  }

  if (file.size === 0) {
    return 'File đã chọn đang rỗng. Vui lòng chọn một file có nội dung.'
  }

  if (file.size > MAX_FILE_SIZE) {
    return 'File vượt quá giới hạn 10 MiB của giao diện. Backend vẫn sẽ kiểm tra giới hạn cuối cùng.'
  }

  return null
}

function getUploadErrorMessage(error) {
  if (error instanceof ApiNetworkError) {
    return 'Không thể kết nối đến Backend. Vui lòng kiểm tra kết nối và thử lại.'
  }

  if (error instanceof ApiConfigurationError) {
    return 'Frontend chưa được cấu hình địa chỉ Backend hợp lệ.'
  }

  if (error instanceof ApiHttpError) {
    const messages = {
      400: 'File hoặc thông tin tài liệu không hợp lệ. Chỉ hỗ trợ PDF và DOCX.',
      401: 'Phiên đăng nhập không hợp lệ hoặc đã hết hạn. Vui lòng đăng nhập lại.',
      413: 'File vượt quá giới hạn dung lượng mà Backend cho phép.',
      415: 'Định dạng file không được Backend hỗ trợ.',
      422: 'Thông tin tải lên bị thiếu hoặc không đúng định dạng.',
      500: 'Hệ thống đang gặp lỗi. Vui lòng thử lại sau.',
    }

    if (messages[error.status]) return messages[error.status]
    if (error.status >= 500) return messages[500]
    return `Không thể tải tài liệu lên (HTTP ${error.status}).`
  }

  return 'Không thể tải tài liệu lên lúc này. Vui lòng thử lại.'
}

function getDocumentListErrorMessage(error) {
  if (error instanceof ApiNetworkError) {
    return 'Không thể kết nối đến Backend để tải danh sách tài liệu.'
  }

  if (error instanceof ApiConfigurationError) {
    return 'Frontend chưa được cấu hình địa chỉ Backend hợp lệ.'
  }

  if (error instanceof ApiHttpError) {
    if (error.status === 401) {
      return 'Phiên đăng nhập không hợp lệ hoặc đã hết hạn. Vui lòng đăng nhập lại.'
    }
    if (error.status === 422) {
      return 'Thông tin tìm kiếm hoặc phân trang không hợp lệ.'
    }
    if (error.status >= 500) {
      return 'Hệ thống đang gặp lỗi khi tải danh sách. Vui lòng thử lại sau.'
    }
  }

  return 'Không thể tải danh sách tài liệu lúc này.'
}

function getProcessingErrorMessage(error) {
  if (error instanceof ApiNetworkError) {
    return 'Không thể kết nối đến Backend để xử lý tài liệu.'
  }
  if (error instanceof ApiConfigurationError) {
    return 'Frontend chưa được cấu hình địa chỉ Backend hợp lệ.'
  }
  if (error instanceof ApiHttpError) {
    const messages = {
      401: 'Phiên đăng nhập không hợp lệ hoặc đã hết hạn. Vui lòng đăng nhập lại.',
      404: 'Tài liệu không tồn tại hoặc bạn không có quyền truy cập.',
      409: 'Tài liệu đang được xử lý hoặc không thể xử lý lại.',
      422: 'Không thể trích xuất nội dung tài liệu này.',
      500: 'Hệ thống đang gặp lỗi khi xử lý tài liệu. Vui lòng thử lại sau.',
    }
    if (messages[error.status]) return messages[error.status]
    if (error.status >= 500) return messages[500]
  }
  return 'Không thể xử lý tài liệu lúc này.'
}

function getStatusErrorMessage(error) {
  if (error instanceof ApiHttpError && error.status === 401) {
    return 'Phiên đăng nhập không hợp lệ hoặc đã hết hạn.'
  }
  if (error instanceof ApiHttpError && error.status === 404) {
    return 'Tài liệu không còn tồn tại hoặc bạn không có quyền truy cập.'
  }
  if (error instanceof ApiNetworkError) {
    return 'Không thể kết nối để cập nhật trạng thái.'
  }
  return 'Chưa thể tải trạng thái xử lý chi tiết.'
}

function getFileActionErrorMessage(error, action) {
  const verb = action === 'view' ? 'xem' : 'tải xuống'
  if (error instanceof ApiNetworkError) {
    return `Không thể kết nối đến Backend để ${verb} tài liệu.`
  }
  if (error instanceof ApiConfigurationError) {
    return 'Frontend chưa được cấu hình địa chỉ Backend hợp lệ.'
  }
  if (error instanceof ApiHttpError) {
    if (error.status === 401) return 'Phiên đăng nhập không hợp lệ hoặc đã hết hạn.'
    if (error.status === 404) return 'Tài liệu không tồn tại hoặc bạn không có quyền truy cập.'
    if (error.status === 400) return action === 'view'
      ? 'Chỉ tài liệu PDF mới có thể xem trực tiếp.'
      : 'Chỉ hỗ trợ tải xuống tài liệu PDF hoặc DOCX.'
    if (error.status >= 500) return 'Không thể đọc tệp tài liệu lúc này. Vui lòng thử lại sau.'
  }
  return `Không thể ${verb} tài liệu lúc này.`
}

function validateDocumentListResponse(response) {
  if (
    !response
    || !Array.isArray(response.items)
    || !Number.isInteger(response.page)
    || response.page < 1
    || !Number.isInteger(response.page_size)
    || response.page_size < 1
    || !Number.isInteger(response.total)
    || response.total < 0
    || !Number.isInteger(response.total_pages)
    || response.total_pages < 0
  ) {
    throw new TypeError('Phản hồi danh sách tài liệu không hợp lệ.')
  }

  return response
}

function validateDocumentStatusResponse(response, documentId) {
  if (
    !response
    || response.document_id !== documentId
    || typeof response.status !== 'string'
    || typeof response.rag_status !== 'string'
    || !Number.isInteger(response.chunk_count)
    || response.chunk_count < 0
  ) {
    throw new TypeError('Phản hồi trạng thái tài liệu không hợp lệ.')
  }
  return response
}

function validateDocumentRagStatusResponse(response, documentId) {
  if (
    !response
    || response.document_id !== documentId
    || typeof response.status !== 'string'
    || typeof response.rag_status !== 'string'
    || !Number.isInteger(response.chunk_count)
    || response.chunk_count < 0
    || typeof response.can_index !== 'boolean'
  ) {
    throw new TypeError('Phản hồi trạng thái lập chỉ mục không hợp lệ.')
  }
  return response
}

function validateDocumentIndexingResponse(response, documentId) {
  if (
    !response
    || response.document_id !== documentId
    || response.rag_status !== 'READY'
    || !Number.isInteger(response.vector_count)
    || response.vector_count < 1
    || typeof response.indexed_at !== 'string'
  ) {
    throw new TypeError('Phản hồi lập chỉ mục tài liệu không hợp lệ.')
  }
  return response
}

async function hydrateDocumentStatuses(documents, { accessToken, signal }) {
  const hydrated = [...documents]
  let nextIndex = 0

  const worker = async () => {
    while (nextIndex < documents.length) {
      const index = nextIndex
      nextIndex += 1
      const document = documents[index]
      let hydratedDocument = { ...document }
      const detailErrors = []
      try {
        const status = validateDocumentStatusResponse(await getDocumentStatus(
          document.id,
          { accessToken, signal },
        ), document.id)
        hydratedDocument = { ...hydratedDocument, ...status }
      } catch (error) {
        if (error?.name === 'AbortError') throw error
        if (error instanceof ApiHttpError && error.status === 401) throw error
        detailErrors.push(getStatusErrorMessage(error))
      }

      try {
        const ragStatus = validateDocumentRagStatusResponse(
          await getDocumentRagStatus(document.id, { accessToken, signal }),
          document.id,
        )
        hydratedDocument = { ...hydratedDocument, ...ragStatus }
      } catch (error) {
        if (error?.name === 'AbortError') throw error
        if (error instanceof ApiHttpError && error.status === 401) throw error
        detailErrors.push(getStatusErrorMessage(error))
      }
      hydrated[index] = {
        ...hydratedDocument,
        status_details_error: [...new Set(detailErrors)].join(' '),
      }
    }
  }

  const workerCount = Math.min(MAX_CONCURRENT_STATUS_REQUESTS, documents.length)
  await Promise.all(Array.from({ length: workerCount }, () => worker()))
  return hydrated
}

function DocumentCard({
  deletionPending,
  document,
  fileOperation,
  onDelete,
  onDownload,
  operation,
  onIndex,
  onProcess,
  onRefreshStatus,
  onView,
}) {
  const fileType = ['PDF', 'DOCX'].includes(document.file_type)
    ? document.file_type
    : 'FILE'
  const status = documentStatuses[document.status] ?? {
    label: 'Không xác định',
    className: 'waiting',
  }
  const hasStatusDetails = Number.isInteger(document.chunk_count)
    && document.chunk_count >= 0
  const canProcess = hasStatusDetails
    && document.chunk_count === 0
    && ['UPLOADED', 'FAILED', 'READY'].includes(document.status)
  const isProcessing = operation?.state === 'processing'
  const isIndexing = operation?.state === 'indexing'
  const isViewing = fileOperation?.state === 'viewing'
  const isDownloading = fileOperation?.state === 'downloading'
  const isFileBusy = isViewing || isDownloading
  const isBusy = isFileBusy || isProcessing || isIndexing || deletionPending
  const canIndex = canIndexDocument(document)
  const ragStatus = getRagStatusPresentation(document.rag_status)
  const processLabel = document.status === 'FAILED'
    ? 'Thử xử lý lại'
    : document.status === 'READY'
      ? 'Xử lý lại tài liệu'
      : 'Xử lý tài liệu'

  return (
    <article className="document-card">
      <div className={`document-card__file document-card__file--${fileType.toLowerCase()}`}>
        <Icon name="file" size={25} />
        <span>{fileType}</span>
      </div>

      <div className="document-card__body">
        <div className="document-card__heading">
          <div>
            <h3 title={document.title}>{document.title}</h3>
            <p title={document.original_filename}>{document.original_filename}</p>
            <p>{formatFileSize(document.file_size)} · Tải lên {formatCreatedAt(document.created_at)}</p>
          </div>
          <span className={`document-status document-status--${status.className}`}><i />{status.label}</span>
        </div>

        {hasStatusDetails && (
          <>
            <div className="document-card__rag">
              <span className={`document-rag-status document-rag-status--${ragStatus.className}`}>
                <i />AI: {ragStatus.label}
              </span>
              <span>
                {document.indexed_at
                  ? `Lập chỉ mục ${formatCreatedAt(document.indexed_at)}`
                  : 'Chưa có thời điểm lập chỉ mục'}
              </span>
            </div>
            <dl className="document-card__metrics">
              <div><dt>Chunks</dt><dd>{formatMetric(document.chunk_count, 'đoạn')}</dd></div>
              <div><dt>Ký tự</dt><dd>{formatMetric(document.character_count, 'ký tự')}</dd></div>
              <div><dt>Số trang</dt><dd>{formatMetric(document.page_count, 'trang')}</dd></div>
              <div><dt>Xử lý lúc</dt><dd>{document.processed_at ? formatCreatedAt(document.processed_at) : 'Chưa có'}</dd></div>
            </dl>
          </>
        )}

        <div className="document-card__actions">
          {document.file_type === 'PDF' && (
            <button
              type="button"
              onClick={() => onView(document)}
              disabled={isBusy}
            >
              {isViewing ? <span className="document-file-action-spinner" aria-hidden="true" /> : <Icon name="eye" size={15} />}
              {isViewing ? 'Đang mở...' : 'Xem'}
            </button>
          )}
          <button
            type="button"
            onClick={() => onDownload(document)}
            disabled={isBusy}
          >
            {isDownloading ? <span className="document-file-action-spinner" aria-hidden="true" /> : <Icon name="download" size={15} />}
            {isDownloading ? 'Đang tải...' : 'Tải xuống'}
          </button>
          {canProcess && (
            <button
              className="document-action--process"
              type="button"
              onClick={() => onProcess(document)}
              disabled={isBusy}
            >
              {isProcessing ? <span className="document-action-spinner" aria-hidden="true" /> : <Icon name="sparkle" size={15} />}
              {isProcessing ? 'Đang xử lý...' : processLabel}
            </button>
          )}
          {canIndex && (
            <button
              className="document-action--index"
              type="button"
              onClick={() => onIndex(document)}
              disabled={isBusy}
            >
              {isIndexing ? <span className="document-action-spinner" aria-hidden="true" /> : <Icon name="sparkle" size={15} />}
              {isIndexing ? 'Đang lập chỉ mục...' : document.rag_status === 'FAILED' ? 'Thử lập chỉ mục lại' : 'Lập chỉ mục AI'}
            </button>
          )}
          {!canProcess && document.status === 'PROCESSING' && (
            <span className="document-card__action-note"><Icon name="lock" size={14} />Tác vụ đang chạy</span>
          )}
          {!canIndex && document.rag_status === 'INDEXING' && (
            <span className="document-card__action-note"><Icon name="lock" size={14} />Đang lập chỉ mục AI</span>
          )}
          {!canIndex && document.rag_status === 'READY' && (
            <span className="document-card__action-note document-card__action-note--ready"><Icon name="check" size={14} />Sẵn sàng hỏi đáp</span>
          )}
          {document.status_details_error && (
            <button type="button" onClick={onRefreshStatus}>Làm mới trạng thái</button>
          )}
          <button
            className="document-action--delete"
            type="button"
            onClick={() => onDelete(document)}
            disabled={isBusy}
            aria-label={`Xóa tài liệu ${document.title}`}
          >
            <Icon name="trash" size={15} />
            Xóa
          </button>
        </div>

        {(document.status_details_error || operation?.message || fileOperation?.message) && (
          <p
            className={`document-card__notice ${operation?.state === 'error' || fileOperation?.state === 'error' || document.status_details_error ? 'document-card__notice--error' : 'document-card__notice--success'}`}
            role={operation?.state === 'error' || fileOperation?.state === 'error' || document.status_details_error ? 'alert' : 'status'}
            aria-live="polite"
          >
            {fileOperation?.message || operation?.message || document.status_details_error}
          </p>
        )}
      </div>
    </article>
  )
}

function Documents({ isSidebarOpen, onOpenSidebar, onCloseSidebar }) {
  const { accessToken, logout } = useAuth()
  const {
    currentHash,
    currentPath,
    currentSearch,
    navigate,
  } = useNavigation()
  const initialSearchState = getInitialDocumentSearchState(currentSearch)
  const [query, setQuery] = useState(initialSearchState.query)
  const [debouncedSearch, setDebouncedSearch] = useState(initialSearchState.debouncedSearch)
  const [activeFilter, setActiveFilter] = useState('Tất cả')
  const [documents, setDocuments] = useState([])
  const [page, setPage] = useState(1)
  const [pagination, setPagination] = useState({
    page: 1,
    pageSize: DOCUMENT_PAGE_SIZE,
    total: 0,
    totalPages: 0,
  })
  const [listStatus, setListStatus] = useState('loading')
  const [listError, setListError] = useState('')
  const [listRefreshVersion, setListRefreshVersion] = useState(0)
  const [documentOperations, setDocumentOperations] = useState({})
  const [fileOperations, setFileOperations] = useState({})
  const [pdfViewer, setPdfViewer] = useState(null)
  const [deletionState, dispatchDeletion] = useReducer(
    documentDeletionUiReducer,
    initialDocumentDeletionUiState,
  )
  const deletionDialog = deletionState.document ? deletionState : null
  const deletionDocumentId = deletionState.document?.id ?? null
  const [deletionNotice, setDeletionNotice] = useState(null)
  const [selectedFile, setSelectedFile] = useState(null)
  const [title, setTitle] = useState('')
  const [uploadState, setUploadState] = useState('idle')
  const [uploadMessage, setUploadMessage] = useState('')
  const [isDragging, setIsDragging] = useState(false)
  const inputId = useId()
  const fileInputRef = useRef(null)
  const uploadSectionRef = useRef(null)
  const uploadRequestRef = useRef({ id: 0, controller: null })
  const listRequestRef = useRef({ id: 0, controller: null })
  const processingRequestsRef = useRef(new Map())
  const processingInFlightRef = useRef(new Set())
  const indexingRequestsRef = useRef(new Map())
  const indexingInFlightRef = useRef(new Set())
  const fileRequestsRef = useRef(new Map())
  const fileActionsInFlightRef = useRef(new Set())
  const deletionRequestRef = useRef({ id: 0, documentId: null, controller: null })
  const deletionGuardRef = useRef(createDocumentDeletionGuard())
  const deletionDialogRef = useRef(null)
  const deletionCancelRef = useRef(null)
  const uploadInFlightRef = useRef(false)
  const isMountedRef = useRef(true)
  const currentLocationKey = `${currentPath}${currentSearch}${currentHash}`
  const currentLocationKeyRef = useRef(currentLocationKey)

  const fileValidationMessage = useMemo(
    () => getFileValidationMessage(selectedFile),
    [selectedFile],
  )
  const titleValidationMessage = title.length > MAX_TITLE_LENGTH
    ? `Tiêu đề không được vượt quá ${MAX_TITLE_LENGTH} ký tự.`
    : null
  const validationMessage = fileValidationMessage || titleValidationMessage
  const isUploading = uploadState === 'uploading'

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
    const processingRequests = processingRequestsRef.current
    const processingInFlight = processingInFlightRef.current
    const indexingRequests = indexingRequestsRef.current
    const indexingInFlight = indexingInFlightRef.current
    const fileRequests = fileRequestsRef.current
    const fileActionsInFlight = fileActionsInFlightRef.current
    const deletionRequest = deletionRequestRef.current
    const deletionGuard = deletionGuardRef.current
    isMountedRef.current = true

    return () => {
      isMountedRef.current = false
      uploadRequestRef.current.id += 1
      uploadRequestRef.current.controller?.abort()
      listRequestRef.current.id += 1
      listRequestRef.current.controller?.abort()
      for (const request of processingRequests.values()) {
        request.controller.abort()
      }
      processingRequests.clear()
      processingInFlight.clear()
      for (const request of indexingRequests.values()) {
        request.controller.abort()
      }
      indexingRequests.clear()
      indexingInFlight.clear()
      for (const request of fileRequests.values()) {
        request.controller.abort()
      }
      fileRequests.clear()
      fileActionsInFlight.clear()
      deletionRequest.id += 1
      deletionRequest.controller?.abort()
      Object.assign(deletionRequest, { documentId: null, controller: null })
      deletionGuard.clear()
      uploadInFlightRef.current = false
    }
  }, [])

  useEffect(() => {
    if (!pdfViewer?.url) return undefined
    const objectUrl = pdfViewer.url
    return () => revokeDocumentObjectUrl(objectUrl)
  }, [pdfViewer?.url])

  useEffect(() => {
    if (!pdfViewer) return undefined
    const handleKeyDown = (event) => {
      if (event.key === 'Escape') setPdfViewer(null)
    }
    document.addEventListener('keydown', handleKeyDown)
    return () => document.removeEventListener('keydown', handleKeyDown)
  }, [pdfViewer])

  useEffect(() => {
    if (!deletionDocumentId) return undefined

    const previouslyFocused = document.activeElement
    deletionCancelRef.current?.focus()
    const handleDialogKeyDown = (event) => {
      const documentId = deletionDocumentId
      if (event.key === 'Escape') {
        if (!deletionGuardRef.current.isActive(documentId)) {
          dispatchDeletion({ type: 'close' })
        }
        return
      }
      if (event.key !== 'Tab') return

      const buttons = Array.from(
        deletionDialogRef.current?.querySelectorAll('button:not(:disabled)') ?? [],
      )
      if (!buttons.length) return
      const first = buttons[0]
      const last = buttons[buttons.length - 1]
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault()
        first.focus()
      }
    }

    document.addEventListener('keydown', handleDialogKeyDown)
    return () => {
      document.removeEventListener('keydown', handleDialogKeyDown)
      if (previouslyFocused instanceof HTMLElement && previouslyFocused.isConnected) {
        previouslyFocused.focus()
      }
    }
  }, [deletionDocumentId])

  useEffect(() => {
    currentLocationKeyRef.current = currentLocationKey
  }, [currentLocationKey])

  useEffect(() => {
    const urlSearch = parseDocumentSearch(currentSearch)
    // URL changes are an external navigation source (Header, Back/Forward, or reload).
    // oxlint-disable-next-line react/set-state-in-effect
    setQuery(urlSearch)
    setDebouncedSearch(urlSearch)
    setPage(1)
  }, [currentSearch])

  useEffect(() => {
    const normalizedQuery = normalizeDocumentSearchTerm(query)
    const urlSearch = parseDocumentSearch(currentSearch)

    if (normalizedQuery === urlSearch) return undefined

    const scheduledLocationKey = currentLocationKey
    const timeoutId = window.setTimeout(() => {
      if (!shouldCommitDocumentSearch({
        query,
        urlSearch: currentSearch,
        scheduledLocationKey,
        currentLocationKey: currentLocationKeyRef.current,
      })) return

      setQuery(normalizedQuery)
      setDebouncedSearch(normalizedQuery)
      setPage(1)
      navigate(buildDocumentSearchUrl({
        keyword: normalizedQuery,
        currentPath,
        currentSearch,
        currentHash,
      }), { replace: true })
    }, SEARCH_DEBOUNCE_MS)

    return () => window.clearTimeout(timeoutId)
  }, [
    currentHash,
    currentLocationKey,
    currentPath,
    currentSearch,
    navigate,
    query,
  ])

  const loadDocuments = useCallback(async () => {
    for (const request of fileRequestsRef.current.values()) {
      request.controller.abort()
    }
    fileRequestsRef.current.clear()
    fileActionsInFlightRef.current.clear()
    setFileOperations({})
    setPdfViewer(null)
    const requestId = listRequestRef.current.id + 1
    const controller = new AbortController()
    listRequestRef.current.controller?.abort()
    listRequestRef.current = { id: requestId, controller }
    setListStatus('loading')
    setListError('')

    try {
      const response = validateDocumentListResponse(await getDocuments({
        accessToken,
        page,
        pageSize: DOCUMENT_PAGE_SIZE,
        search: debouncedSearch,
        fileType: activeFilter === 'Tất cả' ? '' : activeFilter,
        signal: controller.signal,
      }))

      if (!isMountedRef.current || listRequestRef.current.id !== requestId) return

      const hydratedDocuments = await hydrateDocumentStatuses(response.items, {
        accessToken,
        signal: controller.signal,
      })

      if (!isMountedRef.current || listRequestRef.current.id !== requestId) return

      setDocuments(hydratedDocuments)
      setPagination({
        page: response.page,
        pageSize: response.page_size,
        total: response.total,
        totalPages: response.total_pages,
      })
      setListStatus('success')
    } catch (error) {
      if (
        error?.name === 'AbortError'
        || !isMountedRef.current
        || listRequestRef.current.id !== requestId
      ) return

      setDocuments([])
      setPagination({
        page,
        pageSize: DOCUMENT_PAGE_SIZE,
        total: 0,
        totalPages: 0,
      })
      setListStatus('error')
      setListError(getDocumentListErrorMessage(error))
    } finally {
      if (listRequestRef.current.id === requestId) {
        listRequestRef.current.controller = null
      }
    }
  }, [accessToken, activeFilter, debouncedSearch, page])

  useEffect(() => {
    const timeoutId = window.setTimeout(loadDocuments, 0)

    return () => {
      window.clearTimeout(timeoutId)
      listRequestRef.current.controller?.abort()
    }
  }, [listRefreshVersion, loadDocuments])

  const resetFilters = () => {
    setQuery('')
    setDebouncedSearch('')
    setActiveFilter('Tất cả')
    setPage(1)
  }

  const handleFilterChange = (filter) => {
    setActiveFilter(filter)
    setDebouncedSearch(query.trim())
    setPage(1)
  }

  const clearSearch = () => {
    setQuery('')
    setDebouncedSearch('')
    setPage(1)
  }

  const selectFile = (file) => {
    if (isUploading) return

    uploadRequestRef.current.id += 1
    uploadRequestRef.current.controller?.abort()
    uploadRequestRef.current.controller = null
    setSelectedFile(file ?? null)
    setTitle('')
    setUploadMessage('')
    setUploadState(file ? 'selected' : 'idle')
  }

  const handleFileChange = (event) => {
    selectFile(event.target.files?.[0])
    event.target.value = ''
  }

  const handleDrop = (event) => {
    event.preventDefault()
    setIsDragging(false)
    if (isUploading) return

    const droppedFiles = Array.from(event.dataTransfer.files ?? [])
    if (droppedFiles.length > 1) {
      setSelectedFile(null)
      setTitle('')
      setUploadState('error')
      setUploadMessage('Mỗi lần chỉ có thể tải lên một file.')
      return
    }

    selectFile(droppedFiles[0])
  }

  const openFilePicker = () => {
    uploadSectionRef.current?.scrollIntoView({ behavior: 'smooth', block: 'center' })
    fileInputRef.current?.click()
  }

  const handleTitleChange = (event) => {
    setTitle(event.target.value)
    if (uploadState === 'success' || uploadState === 'error') {
      setUploadState(selectedFile ? 'selected' : 'idle')
      setUploadMessage('')
    }
  }

  const handleUpload = async (event) => {
    event.preventDefault()

    if (uploadInFlightRef.current) return
    if (!selectedFile) {
      setUploadState('error')
      setUploadMessage('Vui lòng chọn một file trước khi tải lên.')
      return
    }
    if (validationMessage) return

    const requestId = uploadRequestRef.current.id + 1
    const controller = new AbortController()
    uploadRequestRef.current = { id: requestId, controller }
    uploadInFlightRef.current = true
    setUploadState('uploading')
    setUploadMessage('Đang tải tài liệu lên...')

    try {
      const response = await uploadDocument({
        file: selectedFile,
        title,
        accessToken,
        signal: controller.signal,
      })

      if (!isMountedRef.current || uploadRequestRef.current.id !== requestId) return

      const uploadedTitle = typeof response?.title === 'string' && response.title.trim()
        ? response.title.trim()
        : title.trim() || selectedFile.name
      setUploadState('success')
      setUploadMessage(`Đã tải lên thành công “${uploadedTitle}”.`)
      setQuery('')
      setDebouncedSearch('')
      setActiveFilter('Tất cả')
      setPage(1)
      setListRefreshVersion((version) => version + 1)
    } catch (error) {
      if (
        error?.name === 'AbortError'
        || !isMountedRef.current
        || uploadRequestRef.current.id !== requestId
      ) return

      setUploadState('error')
      setUploadMessage(getUploadErrorMessage(error))
    } finally {
      if (uploadRequestRef.current.id === requestId) {
        uploadRequestRef.current.controller = null
        uploadInFlightRef.current = false
        if (isMountedRef.current) setIsDragging(false)
      }
    }
  }

  const handleProcessDocument = async (document) => {
    const documentId = document.id
    if (processingInFlightRef.current.has(documentId)) return

    const previousRequest = processingRequestsRef.current.get(documentId)
    const requestId = (previousRequest?.id ?? 0) + 1
    const controller = new AbortController()
    const listRequestId = listRequestRef.current.id
    previousRequest?.controller.abort()
    processingRequestsRef.current.set(documentId, { id: requestId, controller })
    processingInFlightRef.current.add(documentId)
    setDocumentOperations((current) => ({
      ...current,
      [documentId]: { state: 'processing', message: 'Đang xử lý nội dung tài liệu...' },
    }))

    const isCurrentRequest = () => (
      isMountedRef.current
      && processingRequestsRef.current.get(documentId)?.id === requestId
    )
    const updateVisibleDocument = (statusResponse) => {
      if (!isCurrentRequest() || listRequestRef.current.id !== listRequestId) return
      setDocuments((current) => current.map((item) => (
        item.id === documentId
          ? { ...item, ...statusResponse, status_details_error: '' }
          : item
      )))
    }

    try {
      const processedStatus = validateDocumentStatusResponse(await processDocument(
        documentId,
        { accessToken, signal: controller.signal },
      ), documentId)
      updateVisibleDocument(processedStatus)

      try {
        const latestStatus = validateDocumentStatusResponse(await getDocumentStatus(
          documentId,
          { accessToken, signal: controller.signal },
        ), documentId)
        updateVisibleDocument(latestStatus)
        const latestRagStatus = validateDocumentRagStatusResponse(
          await getDocumentRagStatus(documentId, {
            accessToken,
            signal: controller.signal,
          }),
          documentId,
        )
        updateVisibleDocument(latestRagStatus)
      } catch (statusError) {
        if (statusError?.name === 'AbortError') throw statusError
        if (!isCurrentRequest()) return
        setDocumentOperations((current) => ({
          ...current,
          [documentId]: {
            state: 'success',
            message: 'Đã xử lý thành công nhưng chưa thể làm mới trạng thái chi tiết.',
          },
        }))
        return
      }

      if (!isCurrentRequest()) return
      setDocumentOperations((current) => ({
        ...current,
        [documentId]: { state: 'success', message: 'Xử lý tài liệu thành công.' },
      }))
    } catch (error) {
      if (error?.name === 'AbortError' || !isCurrentRequest()) return

      try {
        const latestStatus = validateDocumentStatusResponse(await getDocumentStatus(
          documentId,
          { accessToken, signal: controller.signal },
        ), documentId)
        updateVisibleDocument(latestStatus)
      } catch (statusError) {
        if (statusError?.name === 'AbortError') return
      }

      if (!isCurrentRequest()) return
      setDocumentOperations((current) => ({
        ...current,
        [documentId]: { state: 'error', message: getProcessingErrorMessage(error) },
      }))
    } finally {
      if (processingRequestsRef.current.get(documentId)?.id === requestId) {
        processingRequestsRef.current.delete(documentId)
        processingInFlightRef.current.delete(documentId)
      }
    }
  }

  const handleIndexDocument = async (document) => {
    const documentId = document.id
    if (indexingInFlightRef.current.has(documentId)) return

    const previousRequest = indexingRequestsRef.current.get(documentId)
    const requestId = (previousRequest?.id ?? 0) + 1
    const controller = new AbortController()
    const listRequestId = listRequestRef.current.id
    previousRequest?.controller.abort()
    indexingRequestsRef.current.set(documentId, { id: requestId, controller })
    indexingInFlightRef.current.add(documentId)
    setDocumentOperations((current) => ({
      ...current,
      [documentId]: { state: 'indexing', message: 'Đang lập chỉ mục AI...' },
    }))

    const isCurrentRequest = () => (
      isMountedRef.current
      && indexingRequestsRef.current.get(documentId)?.id === requestId
    )
    const updateVisibleDocument = (statusResponse) => {
      if (!isCurrentRequest() || listRequestRef.current.id !== listRequestId) return
      setDocuments((current) => current.map((item) => (
        item.id === documentId
          ? { ...item, ...statusResponse, status_details_error: '' }
          : item
      )))
    }

    try {
      const indexed = validateDocumentIndexingResponse(
        await indexDocument(documentId, {
          accessToken,
          signal: controller.signal,
        }),
        documentId,
      )
      updateVisibleDocument({
        rag_status: indexed.rag_status,
        indexed_at: indexed.indexed_at,
        can_index: false,
      })

      try {
        const latestStatus = validateDocumentRagStatusResponse(
          await getDocumentRagStatus(documentId, {
            accessToken,
            signal: controller.signal,
          }),
          documentId,
        )
        updateVisibleDocument(latestStatus)
      } catch (statusError) {
        if (statusError?.name === 'AbortError') throw statusError
        if (!isCurrentRequest()) return
        setDocumentOperations((current) => ({
          ...current,
          [documentId]: {
            state: 'success',
            message: 'Lập chỉ mục AI thành công nhưng chưa thể làm mới trạng thái chi tiết.',
          },
        }))
        return
      }

      if (!isCurrentRequest()) return
      setDocumentOperations((current) => ({
        ...current,
        [documentId]: {
          state: 'success',
          message: 'Lập chỉ mục AI thành công. Tài liệu đã sẵn sàng hỏi đáp.',
        },
      }))
    } catch (error) {
      if (error?.name === 'AbortError' || !isCurrentRequest()) return

      try {
        const latestStatus = validateDocumentRagStatusResponse(
          await getDocumentRagStatus(documentId, {
            accessToken,
            signal: controller.signal,
          }),
          documentId,
        )
        updateVisibleDocument(latestStatus)
      } catch (statusError) {
        if (statusError?.name === 'AbortError') return
      }

      if (!isCurrentRequest()) return
      setDocumentOperations((current) => ({
        ...current,
        [documentId]: { state: 'error', message: getIndexingErrorMessage(error) },
      }))
    } finally {
      if (indexingRequestsRef.current.get(documentId)?.id === requestId) {
        indexingRequestsRef.current.delete(documentId)
        indexingInFlightRef.current.delete(documentId)
      }
    }
  }

  const beginFileAction = (documentId, state) => {
    if (fileActionsInFlightRef.current.has(documentId)) return null
    const previousRequest = fileRequestsRef.current.get(documentId)
    const requestId = (previousRequest?.id ?? 0) + 1
    const controller = new AbortController()
    previousRequest?.controller.abort()
    fileRequestsRef.current.set(documentId, { id: requestId, controller })
    fileActionsInFlightRef.current.add(documentId)
    setFileOperations((current) => ({
      ...current,
      [documentId]: { state, message: '' },
    }))
    return { requestId, controller, listRequestId: listRequestRef.current.id }
  }

  const isCurrentFileAction = (documentId, requestId, listRequestId) => (
    isMountedRef.current
    && fileRequestsRef.current.get(documentId)?.id === requestId
    && listRequestRef.current.id === listRequestId
  )

  const finishFileAction = (documentId, requestId) => {
    if (fileRequestsRef.current.get(documentId)?.id !== requestId) return
    fileRequestsRef.current.delete(documentId)
    fileActionsInFlightRef.current.delete(documentId)
  }

  const handleViewDocument = async (document) => {
    if (document.file_type !== 'PDF') return
    const action = beginFileAction(document.id, 'viewing')
    if (!action) return
    const { requestId, controller, listRequestId } = action

    try {
      const [detail, blob] = await Promise.all([
        getDocumentDetail(document.id, { accessToken, signal: controller.signal }),
        viewDocumentPdf(document.id, { accessToken, signal: controller.signal }),
      ])
      const objectUrl = createDocumentObjectUrl(blob)
      if (!isCurrentFileAction(document.id, requestId, listRequestId)) {
        revokeDocumentObjectUrl(objectUrl)
        return
      }
      setPdfViewer({ document: detail, url: objectUrl })
      setFileOperations((current) => {
        const next = { ...current }
        delete next[document.id]
        return next
      })
    } catch (error) {
      if (error?.name === 'AbortError' || !isCurrentFileAction(document.id, requestId, listRequestId)) return
      setFileOperations((current) => ({
        ...current,
        [document.id]: { state: 'error', message: getFileActionErrorMessage(error, 'view') },
      }))
    } finally {
      finishFileAction(document.id, requestId)
    }
  }

  const handleDownloadDocument = async (document) => {
    const action = beginFileAction(document.id, 'downloading')
    if (!action) return
    const { requestId, controller, listRequestId } = action

    try {
      const blob = await downloadDocument(document.id, {
        accessToken,
        signal: controller.signal,
      })
      if (!isCurrentFileAction(document.id, requestId, listRequestId)) return
      triggerDocumentDownload(blob, document.original_filename)
      setFileOperations((current) => ({
        ...current,
        [document.id]: { state: 'success', message: 'Đã bắt đầu tải tài liệu xuống.' },
      }))
    } catch (error) {
      if (error?.name === 'AbortError' || !isCurrentFileAction(document.id, requestId, listRequestId)) return
      setFileOperations((current) => ({
        ...current,
        [document.id]: { state: 'error', message: getFileActionErrorMessage(error, 'download') },
      }))
    } finally {
      finishFileAction(document.id, requestId)
    }
  }

  const openDeletionDialog = (document) => {
    if (deletionGuardRef.current.isActive(document.id)) return
    setDeletionNotice(null)
    dispatchDeletion({ type: 'open', document })
  }

  const closeDeletionDialog = () => {
    const documentId = deletionDialog?.document.id
    if (documentId && deletionGuardRef.current.isActive(documentId)) return
    dispatchDeletion({ type: 'close' })
  }

  const synchronizeDeletedDocument = (documentId, message) => {
    const shouldMoveToPreviousPage = documents.length === 1 && page > 1
    setDocuments((current) => removeDocumentFromPage(current, documentId))
    setPagination((current) => decrementDocumentPagination(current))
    setDocumentOperations((current) => {
      const next = { ...current }
      delete next[documentId]
      return next
    })
    setFileOperations((current) => {
      const next = { ...current }
      delete next[documentId]
      return next
    })
    setPdfViewer((current) => (
      current?.document.id === documentId ? null : current
    ))
    dispatchDeletion({ type: 'complete' })
    setDeletionNotice({ type: 'success', message })
    if (shouldMoveToPreviousPage) {
      setPage((current) => Math.max(1, current - 1))
    } else {
      setListRefreshVersion((version) => version + 1)
    }
  }

  const handleConfirmDeletion = async () => {
    const target = deletionDialog?.document
    if (!target || !deletionGuardRef.current.tryStart(target.id)) return

    const requestId = deletionRequestRef.current.id + 1
    const controller = new AbortController()
    deletionRequestRef.current.controller?.abort()
    Object.assign(deletionRequestRef.current, {
      id: requestId,
      documentId: target.id,
      controller,
    })
    dispatchDeletion({
      type: 'start',
      message: 'Đang xóa tài liệu và dữ liệu liên quan...',
    })

    const isCurrentRequest = () => (
      isMountedRef.current
      && deletionRequestRef.current.id === requestId
      && deletionRequestRef.current.documentId === target.id
    )

    try {
      await deleteDocument(target.id, {
        accessToken,
        signal: controller.signal,
      })
      if (!isCurrentRequest()) return
      synchronizeDeletedDocument(
        target.id,
        `Đã xóa tài liệu “${target.title}” cùng dữ liệu liên quan.`,
      )
    } catch (error) {
      if (error?.name === 'AbortError' || !isCurrentRequest()) return

      if (error instanceof ApiHttpError && error.status === 404) {
        synchronizeDeletedDocument(
          target.id,
          `Tài liệu “${target.title}” không còn trong danh sách.`,
        )
        return
      }

      const message = getDocumentDeletionErrorMessage(error)
      dispatchDeletion({ type: 'error', message })
      if (error instanceof ApiHttpError && error.status === 401) {
        logout()
        return
      }
      if (error instanceof ApiNetworkError || (error instanceof ApiHttpError && error.status >= 500)) {
        setListRefreshVersion((version) => version + 1)
      }
    } finally {
      if (deletionRequestRef.current.id === requestId) {
        Object.assign(deletionRequestRef.current, {
          documentId: null,
          controller: null,
        })
      }
      deletionGuardRef.current.finish(target.id)
    }
  }

  const hasActiveFilters = Boolean(
    query.trim() || activeFilter !== 'Tất cả',
  )

  return (
    <div className="app-shell">
      <Sidebar isOpen={isSidebarOpen} onClose={onCloseSidebar} />
      <button className={`sidebar-overlay ${isSidebarOpen ? 'sidebar-overlay--visible' : ''}`} type="button" onClick={onCloseSidebar} aria-label="Đóng thanh điều hướng" tabIndex={isSidebarOpen ? 0 : -1} />

      <div className="app-main">
        <Header title="Tài liệu của tôi" onOpenSidebar={onOpenSidebar} />
        <main className="main-content documents-page">
          <section className="documents-hero" aria-labelledby="documents-title">
            <div>
              <p className="documents-eyebrow">Thư viện học tập</p>
              <h2 id="documents-title">Tài liệu của tôi</h2>
              <p>Quản lý, tìm kiếm và khai thác kiến thức từ tất cả tài liệu học tập của bạn.</p>
            </div>
            <button className="documents-upload" type="button" onClick={openFilePicker} disabled={isUploading}><Icon name="upload" size={18} />Tải tài liệu lên</button>
          </section>

          <section className="document-upload-panel" aria-labelledby="document-upload-title" ref={uploadSectionRef}>
            <div className="document-upload-panel__heading">
              <div>
                <p>Tải lên Backend</p>
                <h2 id="document-upload-title">Thêm tài liệu mới</h2>
              </div>
              <span>PDF, DOCX · tối đa 10 MiB trên giao diện</span>
            </div>

            <form className="document-upload-form" onSubmit={handleUpload} noValidate>
              <input
                id={inputId}
                className="document-file-input"
                type="file"
                accept=".pdf,.docx"
                onChange={handleFileChange}
                ref={fileInputRef}
                disabled={isUploading}
              />
              <label
                className={`document-dropzone ${isDragging ? 'document-dropzone--dragging' : ''} ${isUploading ? 'document-dropzone--disabled' : ''}`}
                htmlFor={inputId}
                tabIndex={isUploading ? -1 : 0}
                onKeyDown={(event) => {
                  if ((event.key === 'Enter' || event.key === ' ') && !isUploading) {
                    event.preventDefault()
                    fileInputRef.current?.click()
                  }
                }}
                onDragEnter={(event) => {
                  event.preventDefault()
                  if (!isUploading) setIsDragging(true)
                }}
                onDragOver={(event) => event.preventDefault()}
                onDragLeave={(event) => {
                  if (!event.currentTarget.contains(event.relatedTarget)) setIsDragging(false)
                }}
                onDrop={handleDrop}
              >
                <span className="document-dropzone__icon"><Icon name="upload" size={23} /></span>
                <span className="document-dropzone__copy">
                  <strong>{selectedFile ? 'Chọn file khác' : 'Chọn một file hoặc kéo thả vào đây'}</strong>
                  <small>Chỉ tải một file mỗi lần. Backend là nơi kiểm tra bảo mật và giới hạn cuối cùng.</small>
                </span>
              </label>

              <div className="document-upload-details">
                <div className={`document-selected-file ${selectedFile ? 'document-selected-file--ready' : ''}`}>
                  <span className="document-selected-file__icon"><Icon name="file" size={21} /></span>
                  <span>
                    <strong>{selectedFile?.name ?? 'Chưa chọn file'}</strong>
                    <small>{selectedFile ? formatFileSize(selectedFile.size) : 'PDF hoặc DOCX'}</small>
                  </span>
                </div>

                <label className="document-title-field" htmlFor={`${inputId}-title`}>
                  <span>Tiêu đề <small>(không bắt buộc)</small></span>
                  <input
                    id={`${inputId}-title`}
                    type="text"
                    value={title}
                    onChange={handleTitleChange}
                    placeholder="Nếu để trống, Backend sẽ dùng tên file"
                    disabled={isUploading}
                    aria-invalid={Boolean(titleValidationMessage)}
                  />
                  <small className={titleValidationMessage ? 'document-title-field__count--error' : ''}>{title.length}/{MAX_TITLE_LENGTH} ký tự</small>
                </label>

                <button
                  className="document-upload-submit"
                  type="submit"
                  disabled={!selectedFile || Boolean(validationMessage) || isUploading}
                >
                  {isUploading ? <span className="document-upload-spinner" aria-hidden="true" /> : <Icon name="upload" size={18} />}
                  {isUploading ? 'Đang tải lên...' : 'Tải lên'}
                </button>
              </div>

              <div
                className={`document-upload-notice ${validationMessage || uploadState === 'error' ? 'document-upload-notice--error' : ''} ${uploadState === 'success' ? 'document-upload-notice--success' : ''}`}
                role={validationMessage || uploadState === 'error' ? 'alert' : 'status'}
                aria-live="polite"
              >
                {(validationMessage || uploadMessage) && (
                  <><Icon name={uploadState === 'success' ? 'check' : 'file'} size={17} /><span>{validationMessage || uploadMessage}</span></>
                )}
              </div>
            </form>
          </section>

          <section className="documents-toolbar" aria-label="Tìm kiếm và lọc tài liệu">
            <label className="documents-search">
              <Icon name="search" size={19} />
              <input type="search" value={query} maxLength={MAX_TITLE_LENGTH} onChange={(event) => setQuery(event.target.value)} placeholder="Tìm kiếm theo tiêu đề..." aria-label="Tìm kiếm theo tiêu đề tài liệu" />
              {query && <button type="button" onClick={clearSearch} aria-label="Xóa nội dung tìm kiếm"><Icon name="close" size={16} /></button>}
            </label>
            <div className="document-filters" aria-label="Lọc theo định dạng">
              {filters.map((filter) => (
                <button className={activeFilter === filter ? 'document-filter--active' : ''} type="button" key={filter} onClick={() => handleFilterChange(filter)} aria-pressed={activeFilter === filter}>{filter}</button>
              ))}
            </div>
          </section>

          <section className="documents-list" aria-labelledby="documents-list-title" aria-busy={listStatus === 'loading'}>
            <div className="documents-list__heading">
              <h2 id="documents-list-title">Danh sách tài liệu</h2>
              <span>{pagination.total} tài liệu</span>
            </div>

            {deletionNotice && (
              <p
                className={`document-deletion-notice document-deletion-notice--${deletionNotice.type}`}
                role="status"
                aria-live="polite"
              >
                <Icon name="check" size={16} />
                {deletionNotice.message}
              </p>
            )}

            {listStatus === 'loading' && (
              <div className="documents-list-state" role="status" aria-live="polite">
                <span className="documents-list-spinner" aria-hidden="true" />
                <h3>Đang tải tài liệu</h3>
                <p>Danh sách đang được đồng bộ từ hệ thống.</p>
              </div>
            )}

            {listStatus === 'error' && (
              <div className="documents-list-state documents-list-state--error" role="alert">
                <div className="documents-empty__icon"><Icon name="documents" size={28} /></div>
                <h3>Không thể tải danh sách</h3>
                <p>{listError}</p>
                <button className="documents-empty__reset" type="button" onClick={loadDocuments}>Thử lại</button>
              </div>
            )}

            {listStatus === 'success' && documents.length > 0 && (
              <>
                <div className="documents-grid">
                  {documents.map((document) => (
                    <DocumentCard
                      deletionPending={deletionDialog?.document.id === document.id && deletionState.state === 'deleting'}
                      document={document}
                      fileOperation={fileOperations[document.id]}
                      onDelete={openDeletionDialog}
                      onDownload={handleDownloadDocument}
                      operation={documentOperations[document.id]}
                      onIndex={handleIndexDocument}
                      onProcess={handleProcessDocument}
                      onRefreshStatus={() => setListRefreshVersion((version) => version + 1)}
                      onView={handleViewDocument}
                      key={document.id}
                    />
                  ))}
                </div>

                <nav className="documents-pagination" aria-label="Phân trang tài liệu">
                  <button type="button" onClick={() => setPage((currentPage) => Math.max(1, currentPage - 1))} disabled={page <= 1}>Trang trước</button>
                  <span>Trang <strong>{pagination.page}</strong> / {pagination.totalPages}</span>
                  <button type="button" onClick={() => setPage((currentPage) => Math.min(pagination.totalPages, currentPage + 1))} disabled={page >= pagination.totalPages}>Trang sau</button>
                </nav>
              </>
            )}

            {listStatus === 'success' && documents.length === 0 && (
              <div className="documents-empty">
                <div className="documents-empty__icon"><Icon name="documents" size={28} /></div>
                <h3>{hasActiveFilters ? 'Không tìm thấy tài liệu' : 'Chưa có tài liệu'}</h3>
                <p>{hasActiveFilters ? 'Không có tài liệu phù hợp với từ khóa hoặc định dạng bạn đang chọn.' : 'Hãy tải tài liệu đầu tiên để bắt đầu xây dựng thư viện học tập.'}</p>
                <div>
                  {hasActiveFilters && <button className="documents-empty__reset" type="button" onClick={resetFilters}>Xóa bộ lọc</button>}
                  {!hasActiveFilters && <button className="documents-upload" type="button" onClick={openFilePicker} disabled={isUploading}><Icon name="upload" size={17} />Tải tài liệu lên</button>}
                </div>
              </div>
            )}
          </section>
        </main>
      </div>

      {pdfViewer && (
        <div className="document-viewer" role="dialog" aria-modal="true" aria-labelledby="document-viewer-title">
          <button className="document-viewer__backdrop" type="button" aria-label="Đóng trình xem tài liệu" onClick={() => setPdfViewer(null)} />
          <section className="document-viewer__panel">
            <header>
              <div>
                <span>Xem tài liệu PDF</span>
                <h2 id="document-viewer-title">{pdfViewer.document.title}</h2>
                <p>{pdfViewer.document.original_filename} · {formatFileSize(pdfViewer.document.file_size)}</p>
              </div>
              <button type="button" onClick={() => setPdfViewer(null)} aria-label="Đóng"><Icon name="close" size={19} /></button>
            </header>
            <iframe src={pdfViewer.url} title={`Nội dung ${pdfViewer.document.title}`} />
          </section>
        </div>
      )}

      {deletionDialog && (
        <div className="document-delete-dialog" role="presentation">
          <button
            className="document-delete-dialog__backdrop"
            type="button"
            aria-label="Đóng hộp thoại xóa tài liệu"
            onClick={closeDeletionDialog}
            disabled={deletionState.state === 'deleting'}
          />
          <section
            className="document-delete-dialog__panel"
            role="alertdialog"
            aria-modal="true"
            aria-labelledby="document-delete-title"
            aria-describedby="document-delete-description"
            aria-busy={deletionState.state === 'deleting'}
            ref={deletionDialogRef}
          >
            <div className="document-delete-dialog__icon" aria-hidden="true">
              <Icon name="trash" size={24} />
            </div>
            <div>
              <p className="document-delete-dialog__eyebrow">Xác nhận xóa</p>
              <h2 id="document-delete-title">Xóa tài liệu này?</h2>
              <p id="document-delete-description">
                Tài liệu <strong>“{deletionDialog.document.title}”</strong>, các đoạn nội dung,
                bản tóm tắt và lịch sử hỏi đáp liên quan sẽ bị xóa.
              </p>
            </div>

            {deletionState.message && (
              <p
                className={`document-delete-dialog__message ${deletionState.state === 'error' ? 'document-delete-dialog__message--error' : ''}`}
                role={deletionState.state === 'error' ? 'alert' : 'status'}
                aria-live="assertive"
              >
                {deletionState.message}
              </p>
            )}

            <div className="document-delete-dialog__actions">
              <button
                className="document-delete-dialog__cancel"
                type="button"
                onClick={closeDeletionDialog}
                disabled={deletionState.state === 'deleting'}
                ref={deletionCancelRef}
              >
                Hủy
              </button>
              <button
                className="document-delete-dialog__confirm"
                type="button"
                onClick={handleConfirmDeletion}
                disabled={deletionState.state === 'deleting'}
              >
                {deletionState.state === 'deleting'
                  ? <span className="document-delete-spinner" aria-hidden="true" />
                  : <Icon name="trash" size={16} />}
                {deletionState.state === 'deleting' ? 'Đang xóa...' : 'Xóa tài liệu'}
              </button>
            </div>
          </section>
        </div>
      )}
    </div>
  )
}

export default Documents
