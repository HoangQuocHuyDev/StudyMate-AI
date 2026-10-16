import {
  useCallback,
  useEffect,
  useId,
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
  previewDocumentDocx,
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
import {
  getDocxPreviewErrorMessage,
  validateDocxPreviewResponse,
} from './documentPreviewUi'
import {
  clearDocxPreview,
  getFormattedDocxErrorMessage,
  renderDocxPreview,
  validateDocxRenderBlob,
} from './docxFormattedPreview'
import {
  createDocumentAutoUploadController,
  getSingleDocumentUploadFile,
} from './documentUploadUi'
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

const MAX_TITLE_LENGTH = 255
const DOCUMENT_PAGE_SIZE = 10
const SEARCH_DEBOUNCE_MS = 350
const MAX_CONCURRENT_STATUS_REQUESTS = 3

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

function getUploadErrorMessage(error) {
  if (error instanceof ApiNetworkError) {
    return 'Không thể kết nối đến hệ thống. Vui lòng kiểm tra mạng và thử lại.'
  }

  if (error instanceof ApiConfigurationError) {
    return 'Ứng dụng chưa được cấu hình đầy đủ. Vui lòng liên hệ quản trị viên.'
  }

  if (error instanceof ApiHttpError) {
    const messages = {
      400: 'File hoặc thông tin tài liệu không hợp lệ. Chỉ hỗ trợ PDF và DOCX.',
      401: 'Phiên đăng nhập không hợp lệ hoặc đã hết hạn. Vui lòng đăng nhập lại.',
      413: 'File vượt quá giới hạn dung lượng cho phép.',
      415: 'Định dạng file không được hỗ trợ.',
      422: 'Thông tin tải lên bị thiếu hoặc không đúng định dạng.',
      500: 'Hệ thống đang gặp lỗi. Vui lòng thử lại sau.',
    }

    if (messages[error.status]) return messages[error.status]
    if (error.status >= 500) return messages[500]
    return 'Không thể tải tài liệu lên lúc này. Vui lòng thử lại.'
  }

  return 'Không thể tải tài liệu lên lúc này. Vui lòng thử lại.'
}

function getDocumentListErrorMessage(error) {
  if (error instanceof ApiNetworkError) {
    return 'Không thể tải danh sách tài liệu. Vui lòng kiểm tra mạng và thử lại.'
  }

  if (error instanceof ApiConfigurationError) {
    return 'Ứng dụng chưa được cấu hình đầy đủ. Vui lòng liên hệ quản trị viên.'
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
    return 'Không thể xử lý tài liệu. Vui lòng kiểm tra mạng và thử lại.'
  }
  if (error instanceof ApiConfigurationError) {
    return 'Ứng dụng chưa được cấu hình đầy đủ. Vui lòng liên hệ quản trị viên.'
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
    return `Không thể ${verb} tài liệu. Vui lòng kiểm tra mạng và thử lại.`
  }
  if (error instanceof ApiConfigurationError) {
    return 'Ứng dụng chưa được cấu hình đầy đủ. Vui lòng liên hệ quản trị viên.'
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

function FormattedDocxPreview({ blob, title }) {
  const containerRef = useRef(null)
  const [renderState, setRenderState] = useState({ state: 'loading', error: '' })

  useEffect(() => {
    const container = containerRef.current
    let isActive = true

    renderDocxPreview(blob, container)
      .then(() => {
        if (isActive) setRenderState({ state: 'ready', error: '' })
      })
      .catch((error) => {
        if (!isActive) return
        clearDocxPreview(container)
        setRenderState({
          state: 'error',
          error: getFormattedDocxErrorMessage(error),
        })
      })

    return () => {
      isActive = false
      clearDocxPreview(container)
    }
  }, [blob])

  return (
    <div className="document-viewer__docx document-viewer__docx--formatted" tabIndex="0" aria-label={`Nội dung định dạng Word của ${title}`}>
      {renderState.state === 'loading' && (
        <div className="document-viewer__state document-viewer__state--overlay" role="status" aria-live="polite">
          <span className="documents-list-spinner" aria-hidden="true" />
          <strong>Đang dựng định dạng tài liệu Word...</strong>
        </div>
      )}
      {renderState.state === 'error' && (
        <div className="document-viewer__state document-viewer__state--error" role="alert">
          <Icon name="file" size={28} />
          <strong>Không thể hiển thị định dạng Word</strong>
          <p>{renderState.error}</p>
          <p>Hãy chọn “Xem dạng văn bản” ở phía trên.</p>
        </div>
      )}
      <div
        className="document-viewer__docx-render"
        ref={containerRef}
        hidden={renderState.state === 'error'}
      />
    </div>
  )
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
                  ? `Chuẩn bị cho AI ${formatCreatedAt(document.indexed_at)}`
                  : 'Chưa có thời điểm chuẩn bị cho AI'}
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
          {['PDF', 'DOCX'].includes(document.file_type) && (
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
              {isIndexing ? 'Đang chuẩn bị...' : document.rag_status === 'FAILED' ? 'Thử chuẩn bị lại' : 'Chuẩn bị cho AI'}
            </button>
          )}
          {!canProcess && document.status === 'PROCESSING' && (
            <span className="document-card__action-note"><Icon name="lock" size={14} />Tác vụ đang chạy</span>
          )}
          {!canIndex && document.rag_status === 'INDEXING' && (
            <span className="document-card__action-note"><Icon name="lock" size={14} />Đang chuẩn bị cho AI</span>
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
  const { accessToken } = useAuth()
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
  const [loadedListScope, setLoadedListScope] = useState(null)
  const [listStatus, setListStatus] = useState('loading')
  const [listError, setListError] = useState('')
  const [listRefreshVersion, setListRefreshVersion] = useState(0)
  const [documentOperations, setDocumentOperations] = useState({})
  const [fileOperations, setFileOperations] = useState({})
  const [documentViewer, setDocumentViewer] = useState(null)
  const [deletionState, dispatchDeletion] = useReducer(
    documentDeletionUiReducer,
    initialDocumentDeletionUiState,
  )
  const deletionDialog = deletionState.document ? deletionState : null
  const deletionDocumentId = deletionState.document?.id ?? null
  const [deletionNotice, setDeletionNotice] = useState(null)
  const [selectedFile, setSelectedFile] = useState(null)
  const [uploadState, setUploadState] = useState('idle')
  const [uploadMessage, setUploadMessage] = useState('')
  const [isDragging, setIsDragging] = useState(false)
  const inputId = useId()
  const fileInputRef = useRef(null)
  const uploadRequestRef = useRef({ id: 0, controller: null })
  const listRequestRef = useRef({ id: 0, controller: null })
  const processingRequestsRef = useRef(new Map())
  const processingInFlightRef = useRef(new Set())
  const indexingRequestsRef = useRef(new Map())
  const indexingInFlightRef = useRef(new Set())
  const fileRequestsRef = useRef(new Map())
  const fileActionsInFlightRef = useRef(new Set())
  const viewerRequestRef = useRef({ id: 0, documentId: null, controller: null })
  const viewerPanelRef = useRef(null)
  const viewerCloseRef = useRef(null)
  const deletionRequestRef = useRef({ id: 0, documentId: null, controller: null })
  const deletionGuardRef = useRef(createDocumentDeletionGuard())
  const autoUploadControllerRef = useRef(createDocumentAutoUploadController())
  const deletionDialogRef = useRef(null)
  const deletionCancelRef = useRef(null)
  const isMountedRef = useRef(true)
  const currentLocationKey = `${currentPath}${currentSearch}${currentHash}`
  const currentLocationKeyRef = useRef(currentLocationKey)

  const isUploading = uploadState === 'uploading'
  const isViewerOpen = documentViewer !== null
  const uploadPrimaryText = isUploading
    ? 'Đang tải tài liệu lên...'
    : uploadMessage || 'Chọn tài liệu hoặc kéo thả vào đây'
  const uploadSecondaryText = selectedFile
    ? `${selectedFile.name} · ${formatFileSize(selectedFile.size)}`
    : uploadState === 'success'
      ? 'Danh sách tài liệu đã được cập nhật. Bạn có thể tiếp tục tải file khác.'
      : 'PDF hoặc DOCX · tối đa 10 MiB · mỗi lần một file · tự động tải lên'

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
    const autoUploadController = autoUploadControllerRef.current
    isMountedRef.current = true

    return () => {
      isMountedRef.current = false
      autoUploadController.invalidate()
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
      viewerRequestRef.current.controller?.abort()
      viewerRequestRef.current = {
        id: viewerRequestRef.current.id + 1,
        documentId: null,
        controller: null,
      }
      deletionRequest.id += 1
      deletionRequest.controller?.abort()
      Object.assign(deletionRequest, { documentId: null, controller: null })
      deletionGuard.clear()
    }
  }, [])

  useEffect(() => {
    if (!documentViewer?.url) return undefined
    const objectUrl = documentViewer.url
    return () => revokeDocumentObjectUrl(objectUrl)
  }, [documentViewer?.url])

  useEffect(() => {
    if (!isViewerOpen) return undefined
    const previouslyFocused = document.activeElement
    viewerCloseRef.current?.focus()
    const handleKeyDown = (event) => {
      if (event.key === 'Escape') {
        const active = viewerRequestRef.current
        active.controller?.abort()
        viewerRequestRef.current = {
          id: active.id + 1,
          documentId: null,
          controller: null,
        }
        if (active.controller && active.documentId) {
          fileRequestsRef.current.delete(active.documentId)
          fileActionsInFlightRef.current.delete(active.documentId)
          setFileOperations((current) => {
            const next = { ...current }
            delete next[active.documentId]
            return next
          })
        }
        setDocumentViewer(null)
        return
      }
      if (event.key !== 'Tab') return

      const focusable = Array.from(
        viewerPanelRef.current?.querySelectorAll(
          'button:not(:disabled), iframe, [href], [tabindex]:not([tabindex="-1"])',
        ) ?? [],
      )
      if (!focusable.length) return
      const first = focusable[0]
      const last = focusable[focusable.length - 1]
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault()
        first.focus()
      }
    }
    document.addEventListener('keydown', handleKeyDown)
    return () => {
      document.removeEventListener('keydown', handleKeyDown)
      if (previouslyFocused instanceof HTMLElement && previouslyFocused.isConnected) {
        previouslyFocused.focus()
      }
    }
  }, [isViewerOpen])

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
    const viewerRequest = viewerRequestRef.current
    viewerRequest.controller?.abort()
    viewerRequestRef.current = {
      id: viewerRequest.id + 1,
      documentId: null,
      controller: null,
    }
    setDocumentViewer(null)
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
      setLoadedListScope({
        search: debouncedSearch,
        fileType: activeFilter,
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

  const startAutoUpload = async (files) => {
    if (autoUploadControllerRef.current.isBusy()) return

    const selection = getSingleDocumentUploadFile(files)
    if (!selection.file && !selection.error) return
    if (selection.error) {
      setSelectedFile(selection.file)
      setUploadState('error')
      setUploadMessage(selection.error)
      return
    }

    await autoUploadControllerRef.current.submit(selection.file, {
      upload: async (file) => {
        const requestId = uploadRequestRef.current.id + 1
        const controller = new AbortController()
        uploadRequestRef.current.controller?.abort()
        uploadRequestRef.current = { id: requestId, controller }

        try {
          return await uploadDocument({
            file,
            accessToken,
            signal: controller.signal,
          })
        } finally {
          if (uploadRequestRef.current.id === requestId) {
            uploadRequestRef.current.controller = null
          }
        }
      },
      onStart: (file) => {
        setSelectedFile(file)
        setUploadState('uploading')
        setUploadMessage('Đang tải lên...')
      },
      onSuccess: (response, file) => {
        if (!isMountedRef.current) return
        const uploadedTitle = typeof response?.title === 'string' && response.title.trim()
          ? response.title.trim()
          : file.name
        setSelectedFile(null)
        setUploadState('success')
        setUploadMessage(`Đã tải lên thành công “${uploadedTitle}”.`)
        setQuery('')
        setDebouncedSearch('')
        setActiveFilter('Tất cả')
        setPage(1)
        setListRefreshVersion((version) => version + 1)
      },
      onError: (error) => {
        if (error?.name === 'AbortError' || !isMountedRef.current) return
        setUploadState('error')
        setUploadMessage(getUploadErrorMessage(error))
      },
      onSettled: () => {
        if (!isMountedRef.current) return
        setIsDragging(false)
        if (fileInputRef.current) fileInputRef.current.value = ''
      },
    })
  }

  const handleFileChange = (event) => {
    const files = Array.from(event.target.files ?? [])
    event.target.value = ''
    void startAutoUpload(files)
  }

  const handleDrop = (event) => {
    event.preventDefault()
    setIsDragging(false)
    if (autoUploadControllerRef.current.isBusy()) return
    void startAutoUpload(event.dataTransfer.files)
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
      [documentId]: { state: 'indexing', message: 'Đang chuẩn bị tài liệu cho AI...' },
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
            message: 'Đã chuẩn bị tài liệu cho AI nhưng chưa thể làm mới trạng thái chi tiết.',
          },
        }))
        return
      }

      if (!isCurrentRequest()) return
      setDocumentOperations((current) => ({
        ...current,
        [documentId]: {
          state: 'success',
          message: 'Đã chuẩn bị tài liệu cho AI. Tài liệu đã sẵn sàng hỏi đáp.',
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

  const closeDocumentViewer = () => {
    const active = viewerRequestRef.current
    active.controller?.abort()
    viewerRequestRef.current = {
      id: active.id + 1,
      documentId: null,
      controller: null,
    }
    if (active.controller && active.documentId) {
      fileRequestsRef.current.delete(active.documentId)
      fileActionsInFlightRef.current.delete(active.documentId)
      setFileOperations((current) => {
        const next = { ...current }
        delete next[active.documentId]
        return next
      })
    }
    setDocumentViewer(null)
  }

  const handleViewDocument = async (document) => {
    if (!['PDF', 'DOCX'].includes(document.file_type)) return

    const previousViewerRequest = viewerRequestRef.current
    previousViewerRequest.controller?.abort()
    if (previousViewerRequest.controller && previousViewerRequest.documentId) {
      fileRequestsRef.current.delete(previousViewerRequest.documentId)
      fileActionsInFlightRef.current.delete(previousViewerRequest.documentId)
      setFileOperations((current) => {
        const next = { ...current }
        delete next[previousViewerRequest.documentId]
        return next
      })
    }

    const action = beginFileAction(document.id, 'viewing')
    if (!action) return
    const { requestId, controller, listRequestId } = action
    const viewerRequestId = previousViewerRequest.id + 1
    viewerRequestRef.current = {
      id: viewerRequestId,
      documentId: document.id,
      controller,
    }
    setDocumentViewer({
      document,
      kind: document.file_type,
      state: 'loading',
      viewMode: document.file_type === 'DOCX' ? 'formatted' : null,
      blob: null,
      content: '',
      url: null,
      error: '',
    })

    const isCurrentViewerRequest = () => (
      viewerRequestRef.current.id === viewerRequestId
      && viewerRequestRef.current.documentId === document.id
      && isCurrentFileAction(document.id, requestId, listRequestId)
    )

    try {
      if (document.file_type === 'PDF') {
        const [detail, blob] = await Promise.all([
          getDocumentDetail(document.id, { accessToken, signal: controller.signal }),
          viewDocumentPdf(document.id, { accessToken, signal: controller.signal }),
        ])
        const objectUrl = createDocumentObjectUrl(blob)
        if (!isCurrentViewerRequest()) {
          revokeDocumentObjectUrl(objectUrl)
          return
        }
        setDocumentViewer({
          document: detail,
          kind: 'PDF',
          state: 'ready',
          viewMode: null,
          blob: null,
          content: '',
          url: objectUrl,
          error: '',
        })
      } else {
        const blob = validateDocxRenderBlob(await downloadDocument(document.id, {
          accessToken,
          signal: controller.signal,
        }))
        if (!isCurrentViewerRequest()) return
        setDocumentViewer({
          document,
          kind: 'DOCX',
          state: 'ready',
          viewMode: 'formatted',
          blob,
          content: '',
          url: null,
          error: '',
        })
      }
      setFileOperations((current) => {
        const next = { ...current }
        delete next[document.id]
        return next
      })
    } catch (error) {
      if (error?.name === 'AbortError' || !isCurrentViewerRequest()) return
      const message = document.file_type === 'DOCX'
        ? getFormattedDocxErrorMessage(error)
        : getFileActionErrorMessage(error, 'view')
      setDocumentViewer((current) => (
        current?.document.id === document.id
          ? { ...current, state: 'error', error: message }
          : current
      ))
      setFileOperations((current) => ({
        ...current,
        [document.id]: { state: 'error', message },
      }))
    } finally {
      finishFileAction(document.id, requestId)
      if (viewerRequestRef.current.id === viewerRequestId) {
        viewerRequestRef.current = {
          id: viewerRequestId,
          documentId: document.id,
          controller: null,
        }
      }
    }
  }

  const handleLoadDocxTextPreview = async () => {
    const currentViewer = documentViewer
    const document = currentViewer?.document
    if (currentViewer?.kind !== 'DOCX' || !document) return

    const previousViewerRequest = viewerRequestRef.current
    previousViewerRequest.controller?.abort()
    const action = beginFileAction(document.id, 'viewing')
    if (!action) return
    const { requestId, controller, listRequestId } = action
    const viewerRequestId = previousViewerRequest.id + 1
    viewerRequestRef.current = {
      id: viewerRequestId,
      documentId: document.id,
      controller,
    }
    setDocumentViewer((viewer) => (
      viewer?.document.id === document.id
        ? { ...viewer, state: 'loading', viewMode: 'text', error: '' }
        : viewer
    ))

    const isCurrentViewerRequest = () => (
      viewerRequestRef.current.id === viewerRequestId
      && viewerRequestRef.current.documentId === document.id
      && isCurrentFileAction(document.id, requestId, listRequestId)
    )

    try {
      const preview = validateDocxPreviewResponse(
        await previewDocumentDocx(document.id, {
          accessToken,
          signal: controller.signal,
        }),
        document.id,
      )
      if (!isCurrentViewerRequest()) return
      setDocumentViewer((viewer) => (
        viewer?.document.id === document.id
          ? {
              ...viewer,
              document: { ...viewer.document, ...preview, id: preview.document_id },
              state: 'ready',
              viewMode: 'text',
              content: preview.content,
              error: '',
            }
          : viewer
      ))
      setFileOperations((current) => {
        const next = { ...current }
        delete next[document.id]
        return next
      })
    } catch (error) {
      if (error?.name === 'AbortError' || !isCurrentViewerRequest()) return
      const message = getDocxPreviewErrorMessage(error)
      setDocumentViewer((viewer) => (
        viewer?.document.id === document.id
          ? { ...viewer, state: 'error', viewMode: 'text', error: message }
          : viewer
      ))
      setFileOperations((current) => ({
        ...current,
        [document.id]: { state: 'error', message },
      }))
    } finally {
      finishFileAction(document.id, requestId)
      if (viewerRequestRef.current.id === viewerRequestId) {
        viewerRequestRef.current = {
          id: viewerRequestId,
          documentId: document.id,
          controller: null,
        }
      }
    }
  }

  const handleShowFormattedDocx = () => {
    setDocumentViewer((viewer) => (
      viewer?.kind === 'DOCX' && viewer.blob
        ? { ...viewer, state: 'ready', viewMode: 'formatted', error: '' }
        : viewer
    ))
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
    setDocumentViewer((current) => {
      if (current?.document.id !== documentId) return current
      const active = viewerRequestRef.current
      active.controller?.abort()
      viewerRequestRef.current = {
        id: active.id + 1,
        documentId: null,
        controller: null,
      }
      return null
    })
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
      if (error instanceof ApiHttpError && error.status === 401) return
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
  const isLibraryEmpty = Boolean(
    listStatus === 'success'
    && documents.length === 0
    && pagination.total === 0
    && !hasActiveFilters
    && loadedListScope?.search === ''
    && loadedListScope?.fileType === 'Tất cả',
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
          </section>

          <section className="document-upload-panel" aria-labelledby="document-upload-title">
            <div className="document-upload-panel__heading">
              <div>
                <p>Tải tài liệu</p>
                <h2 id="document-upload-title">Thêm tài liệu mới</h2>
              </div>
              <span>PDF, DOCX · tối đa 10 MiB</span>
            </div>

            <div className="document-upload-form">
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
                className={`document-dropzone ${isDragging ? 'document-dropzone--dragging' : ''} ${isUploading ? 'document-dropzone--disabled document-dropzone--uploading' : ''} ${uploadState === 'success' ? 'document-dropzone--success' : ''} ${uploadState === 'error' ? 'document-dropzone--error' : ''}`}
                htmlFor={inputId}
                tabIndex={isUploading ? -1 : 0}
                aria-disabled={isUploading}
                aria-busy={isUploading}
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
                <span className="document-dropzone__icon">
                  {isUploading
                    ? <span className="document-upload-spinner document-upload-spinner--inline" aria-hidden="true" />
                    : <Icon name={uploadState === 'success' ? 'check' : 'upload'} size={25} />}
                </span>
                <span
                  className="document-dropzone__copy"
                  role={uploadState === 'error' ? 'alert' : 'status'}
                  aria-live="polite"
                >
                  <strong>{uploadPrimaryText}</strong>
                  <small>{uploadSecondaryText}</small>
                </span>
              </label>
            </div>
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
              <>
                <div className="documents-empty">
                  <div className="documents-empty__icon"><Icon name="library" size={28} /></div>
                  <h3>{hasActiveFilters ? 'Không tìm thấy tài liệu' : 'Chưa có tài liệu'}</h3>
                  <p>{hasActiveFilters ? 'Không có tài liệu phù hợp với từ khóa hoặc định dạng bạn đang chọn.' : 'Tài liệu bạn tải lên sẽ xuất hiện tại đây.'}</p>
                  {hasActiveFilters && (
                    <div className="documents-empty__actions">
                      <button className="documents-empty__reset" type="button" onClick={resetFilters}>Xóa bộ lọc</button>
                    </div>
                  )}
                </div>

                {isLibraryEmpty && (
                  <section className="documents-getting-started" aria-labelledby="documents-getting-started-title">
                    <div className="documents-getting-started__heading">
                      <p>Quy trình đơn giản</p>
                      <h3 id="documents-getting-started-title">Bắt đầu học cùng StudyMate AI</h3>
                    </div>
                    <ol className="documents-getting-started__steps">
                      <li>
                        <span className="documents-getting-started__icon"><Icon name="upload" size={21} /></span>
                        <div><span>Bước 1</span><h4>Tải tài liệu</h4><p>Chọn PDF hoặc DOCX để bắt đầu.</p></div>
                      </li>
                      <li>
                        <span className="documents-getting-started__icon"><Icon name="summary" size={21} /></span>
                        <div><span>Bước 2</span><h4>Tóm tắt AI</h4><p>Nắm nhanh nội dung quan trọng.</p></div>
                      </li>
                      <li>
                        <span className="documents-getting-started__icon"><Icon name="chat" size={21} /></span>
                        <div><span>Bước 3</span><h4>Hỏi đáp AI</h4><p>Đặt câu hỏi dựa trên tài liệu.</p></div>
                      </li>
                    </ol>
                  </section>
                )}
              </>
            )}
          </section>
        </main>
      </div>

      {documentViewer && (
        <div className="document-viewer" role="dialog" aria-modal="true" aria-labelledby="document-viewer-title">
          <button className="document-viewer__backdrop" type="button" aria-label="Đóng trình xem tài liệu" onClick={closeDocumentViewer} />
          <section className="document-viewer__panel" ref={viewerPanelRef} aria-busy={documentViewer.state === 'loading'}>
            <header>
              <div className="document-viewer__heading">
                <span>{documentViewer.kind === 'PDF' ? 'Xem tài liệu PDF' : 'Xem trước tài liệu DOCX'}</span>
                <h2 id="document-viewer-title">{documentViewer.document.title}</h2>
                <p>{documentViewer.document.original_filename} · {formatFileSize(documentViewer.document.file_size)}</p>
              </div>
              <div className="document-viewer__actions">
                {documentViewer.kind === 'DOCX' && (
                  <button
                    className="document-viewer__mode"
                    type="button"
                    onClick={documentViewer.viewMode === 'text'
                      ? handleShowFormattedDocx
                      : handleLoadDocxTextPreview}
                    disabled={
                      documentViewer.state === 'loading'
                      || (documentViewer.viewMode === 'text' && !documentViewer.blob)
                    }
                  >
                    <Icon name="file" size={16} />
                    {documentViewer.viewMode === 'text' ? 'Xem định dạng Word' : 'Xem dạng văn bản'}
                  </button>
                )}
                {documentViewer.kind === 'DOCX' && (
                  <button
                    className="document-viewer__download"
                    type="button"
                    onClick={() => handleDownloadDocument(documentViewer.document)}
                    disabled={documentViewer.state === 'loading' || fileOperations[documentViewer.document.id]?.state === 'downloading'}
                  >
                    {fileOperations[documentViewer.document.id]?.state === 'downloading'
                      ? <span className="document-file-action-spinner" aria-hidden="true" />
                      : <Icon name="download" size={16} />}
                    {fileOperations[documentViewer.document.id]?.state === 'downloading' ? 'Đang tải...' : 'Tải xuống bản gốc'}
                  </button>
                )}
                <button ref={viewerCloseRef} type="button" onClick={closeDocumentViewer} aria-label="Đóng"><Icon name="close" size={19} /></button>
              </div>
            </header>
            {documentViewer.state === 'loading' && (
              <div className="document-viewer__state" role="status" aria-live="polite">
                <span className="documents-list-spinner" aria-hidden="true" />
                <strong>Đang tải nội dung xem trước...</strong>
              </div>
            )}
            {documentViewer.state === 'error' && (
              <div className="document-viewer__state document-viewer__state--error" role="alert">
                <Icon name="file" size={28} />
                <strong>Không thể xem trước tài liệu</strong>
                <p>{documentViewer.error}</p>
              </div>
            )}
            {documentViewer.state === 'ready' && documentViewer.kind === 'PDF' && (
              <iframe src={documentViewer.url} title={`Nội dung ${documentViewer.document.title}`} />
            )}
            {documentViewer.state === 'ready'
              && documentViewer.kind === 'DOCX'
              && documentViewer.viewMode === 'formatted'
              && (
                <FormattedDocxPreview
                  key={documentViewer.document.id}
                  blob={documentViewer.blob}
                  title={documentViewer.document.title}
                />
              )}
            {documentViewer.state === 'ready'
              && documentViewer.kind === 'DOCX'
              && documentViewer.viewMode === 'text'
              && (
              <div className="document-viewer__docx" tabIndex="0" aria-label={`Nội dung văn bản của ${documentViewer.document.title}`}>
                {documentViewer.content
                  ? <div className="document-viewer__docx-content">{documentViewer.content}</div>
                  : (
                    <div className="document-viewer__state document-viewer__state--empty">
                      <Icon name="file" size={30} />
                      <strong>Tài liệu này chưa có nội dung văn bản để xem trước.</strong>
                    </div>
                  )}
              </div>
              )}
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
