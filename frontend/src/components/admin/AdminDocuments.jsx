import {
  useCallback,
  useEffect,
  useReducer,
  useRef,
  useState,
} from 'react'
import { useAuth } from '../../contexts/AuthContext'
import { ApiHttpError } from '../../services/apiClient'
import {
  getAdminDocumentDetail,
  getAdminDocuments,
} from '../../services/adminDocumentsService'
import Icon from '../Icons'
import AdminModal from './AdminModal'
import {
  ADMIN_DOCUMENTS_PAGE_SIZE,
  adminDocumentsReducer,
  formatAdminDocumentDate,
  formatAdminDocumentSize,
  getAdminDocumentsAdjustedOffset,
  getAdminDocumentsErrorMessage,
  getAdminDocumentsPageInfo,
  getDocumentStatusPresentation,
  getRagStatusPresentation,
  initialAdminDocumentsState,
  validateAdminDocumentDetailResponse,
  validateAdminDocumentListResponse,
} from './adminDocumentsUi'


function TableSkeleton() {
  return (
    <div className="admin-documents-skeleton" aria-label="Đang tải danh sách tài liệu" aria-busy="true">
      {Array.from({ length: 6 }, (_, index) => (
        <span key={index}><i /><i /><i /><i /><i /></span>
      ))}
    </div>
  )
}

function StatusBadge({ presentation }) {
  return <span className={`admin-status admin-status--${presentation.tone}`}><i />{presentation.label}</span>
}

function DetailRow({ label, children }) {
  return <div><dt>{label}</dt><dd>{children}</dd></div>
}

function AdminDocuments() {
  const { accessToken } = useAuth()
  const [state, dispatch] = useReducer(adminDocumentsReducer, initialAdminDocumentsState)
  const [searchInput, setSearchInput] = useState('')
  const [search, setSearch] = useState('')
  const [fileType, setFileType] = useState('all')
  const [statusFilter, setStatusFilter] = useState('all')
  const [ragStatusFilter, setRagStatusFilter] = useState('all')
  const [offset, setOffset] = useState(0)
  const [detailState, setDetailState] = useState(null)
  const listRequestRef = useRef({ id: 0, controller: null })
  const detailRequestRef = useRef({ id: 0, controller: null })
  const searchRef = useRef('')
  const isMountedRef = useRef(true)

  const loadDocuments = useCallback(async () => {
    const requestId = listRequestRef.current.id + 1
    const controller = new AbortController()
    listRequestRef.current.controller?.abort()
    listRequestRef.current = { id: requestId, controller }
    dispatch({ type: 'request-started', requestId })
    try {
      const response = await getAdminDocuments({
        accessToken,
        limit: ADMIN_DOCUMENTS_PAGE_SIZE,
        offset,
        search,
        fileType: fileType === 'all' ? null : fileType,
        status: statusFilter === 'all' ? null : statusFilter,
        ragStatus: ragStatusFilter === 'all' ? null : ragStatusFilter,
        signal: controller.signal,
      })
      const data = validateAdminDocumentListResponse(response)
      if (!isMountedRef.current || listRequestRef.current.id !== requestId) return
      const adjustedOffset = getAdminDocumentsAdjustedOffset(data)
      if (adjustedOffset !== offset) {
        setOffset(adjustedOffset)
        return
      }
      dispatch({ type: 'request-succeeded', requestId, data })
    } catch (error) {
      if (error?.name === 'AbortError' || !isMountedRef.current || listRequestRef.current.id !== requestId) return
      dispatch({ type: 'request-failed', requestId, error: getAdminDocumentsErrorMessage(error) })
    } finally {
      if (listRequestRef.current.id === requestId) listRequestRef.current.controller = null
    }
  }, [accessToken, fileType, offset, ragStatusFilter, search, statusFilter])

  useEffect(() => {
    const timer = window.setTimeout(() => {
      const normalized = searchInput.trim()
      if (searchRef.current !== normalized) {
        searchRef.current = normalized
        setOffset(0)
        setSearch(normalized)
      }
    }, 350)
    return () => window.clearTimeout(timer)
  }, [searchInput])

  useEffect(() => {
    const timer = window.setTimeout(loadDocuments, 0)
    return () => {
      window.clearTimeout(timer)
      listRequestRef.current.controller?.abort()
    }
  }, [loadDocuments])

  useEffect(() => {
    isMountedRef.current = true
    return () => {
      isMountedRef.current = false
      listRequestRef.current.id += 1
      detailRequestRef.current.id += 1
      listRequestRef.current.controller?.abort()
      detailRequestRef.current.controller?.abort()
    }
  }, [])

  const closeDetail = useCallback(() => {
    detailRequestRef.current.id += 1
    detailRequestRef.current.controller?.abort()
    detailRequestRef.current.controller = null
    setDetailState(null)
  }, [])

  const openDetail = async (document) => {
    const requestId = detailRequestRef.current.id + 1
    const controller = new AbortController()
    detailRequestRef.current.controller?.abort()
    detailRequestRef.current = { id: requestId, controller }
    setDetailState({ status: 'loading', document, detail: null, error: null })
    try {
      const response = await getAdminDocumentDetail(document.id, { accessToken, signal: controller.signal })
      const detail = validateAdminDocumentDetailResponse(response)
      if (!isMountedRef.current || detailRequestRef.current.id !== requestId) return
      setDetailState({ status: 'ready', document, detail, error: null })
    } catch (error) {
      if (error?.name === 'AbortError' || !isMountedRef.current || detailRequestRef.current.id !== requestId) return
      setDetailState({ status: 'error', document, detail: null, error: getAdminDocumentsErrorMessage(error, 'detail') })
      if (error instanceof ApiHttpError && error.status === 404) loadDocuments()
    } finally {
      if (detailRequestRef.current.id === requestId) detailRequestRef.current.controller = null
    }
  }

  const data = state.data
  const documents = data?.items ?? []
  const pageInfo = data ? getAdminDocumentsPageInfo(data) : null
  const hasFilters = Boolean(search || fileType !== 'all' || statusFilter !== 'all' || ragStatusFilter !== 'all')

  return (
    <section className="admin-management" aria-labelledby="admin-documents-title">
      <div className="admin-section-heading">
        <div><p>Kho tài liệu hệ thống</p><h2 id="admin-documents-title">Danh sách tài liệu</h2><span>Xem thông tin tài liệu toàn hệ thống mà không truy cập nội dung riêng tư.</span></div>
        <strong>{data ? `${data.total} tài liệu` : 'Đang đồng bộ'}</strong>
      </div>

      <div className="admin-toolbar admin-documents-toolbar" aria-label="Bộ lọc tài liệu">
        <label className="admin-search">
          <Icon name="search" size={18} /><span className="sr-only">Tìm theo tên tài liệu hoặc tên file</span>
          <input type="search" value={searchInput} maxLength={255} placeholder="Tìm tên tài liệu hoặc tên file..." onChange={(event) => setSearchInput(event.target.value)} />
          {searchInput && <button type="button" onClick={() => setSearchInput('')} aria-label="Xóa từ khóa tìm kiếm"><Icon name="close" size={15} /></button>}
        </label>
        <label className="admin-filter"><span>Loại</span><select value={fileType} onChange={(event) => { setFileType(event.target.value); setOffset(0) }}><option value="all">Tất cả</option><option value="PDF">PDF</option><option value="DOCX">DOCX</option></select><Icon name="chevronDown" size={15} /></label>
        <label className="admin-filter"><span>Xử lý</span><select value={statusFilter} onChange={(event) => { setStatusFilter(event.target.value); setOffset(0) }}><option value="all">Tất cả</option><option value="UPLOADED">Chưa xử lý</option><option value="PROCESSING">Đang xử lý</option><option value="READY">Đã xử lý</option><option value="FAILED">Thất bại</option></select><Icon name="chevronDown" size={15} /></label>
        <label className="admin-filter"><span>Hỏi đáp AI</span><select value={ragStatusFilter} onChange={(event) => { setRagStatusFilter(event.target.value); setOffset(0) }}><option value="all">Tất cả</option><option value="PENDING">Chưa sẵn sàng</option><option value="INDEXING">Đang chuẩn bị</option><option value="READY">Sẵn sàng</option><option value="FAILED">Chuẩn bị thất bại</option></select><Icon name="chevronDown" size={15} /></label>
      </div>

      {state.status === 'error' && data && <div className="admin-refresh-error" role="alert"><span>{state.error} Dữ liệu trước đó vẫn được giữ nguyên.</span><button type="button" onClick={loadDocuments}>Thử lại</button></div>}
      {state.status === 'loading' && !data && <TableSkeleton />}
      {state.status === 'error' && !data && <div className="admin-empty admin-empty--error" role="alert"><div><Icon name="refresh" size={27} /></div><h3>Chưa thể tải danh sách tài liệu</h3><p>{state.error}</p><button type="button" onClick={loadDocuments}>Thử lại</button></div>}
      {data && documents.length === 0 && <div className="admin-empty" role="status"><div><Icon name="documents" size={27} /></div><h3>{hasFilters ? 'Không tìm thấy tài liệu phù hợp' : 'Chưa có tài liệu nào'}</h3><p>{hasFilters ? 'Hãy thử thay đổi từ khóa hoặc bộ lọc.' : 'Tài liệu được tải lên sẽ xuất hiện tại đây.'}</p></div>}

      {data && documents.length > 0 && (
        <>
          <div className="admin-table-wrap" aria-busy={state.status === 'loading'}>
            <table className="admin-table admin-documents-table">
              <thead><tr><th>ID</th><th>Tài liệu</th><th>Loại</th><th>Dung lượng</th><th>Chủ sở hữu</th><th>Xử lý</th><th>Hỏi đáp AI</th><th>Ngày tải</th><th>Thao tác</th></tr></thead>
              <tbody>{documents.map((document) => (
                <tr key={document.id}>
                  <td data-label="ID"><span className="admin-user-id">#{document.id}</span></td>
                  <td data-label="Tài liệu"><div className="admin-document-cell"><span className={`admin-document-cell__icon admin-document-cell__icon--${document.file_type.toLowerCase()}`}><Icon name="file" size={20} /></span><div><strong>{document.title}</strong><small title={document.original_filename}>{document.original_filename}</small></div></div></td>
                  <td data-label="Loại"><span className={`admin-file-type admin-file-type--${document.file_type.toLowerCase()}`}>{document.file_type}</span></td>
                  <td data-label="Dung lượng">{formatAdminDocumentSize(document.file_size)}</td>
                  <td data-label="Chủ sở hữu"><span className="admin-owner">@{document.owner.username}</span></td>
                  <td data-label="Xử lý"><StatusBadge presentation={getDocumentStatusPresentation(document.status)} /></td>
                  <td data-label="Hỏi đáp AI"><StatusBadge presentation={getRagStatusPresentation(document.rag_status)} /></td>
                  <td data-label="Ngày tải"><time dateTime={document.created_at}>{formatAdminDocumentDate(document.created_at)}</time></td>
                  <td data-label="Thao tác"><div className="admin-row-actions"><button type="button" onClick={() => openDetail(document)}><Icon name="eye" size={15} />Chi tiết</button></div></td>
                </tr>
              ))}</tbody>
            </table>
          </div>
          <div className="admin-pagination" aria-label="Phân trang tài liệu"><span>Hiển thị {pageInfo.firstItem}–{pageInfo.lastItem} trong {data.total} tài liệu</span><div><button type="button" disabled={!pageInfo.canGoBack || state.status === 'loading'} onClick={() => setOffset(Math.max(0, offset - ADMIN_DOCUMENTS_PAGE_SIZE))}>Trang trước</button><strong>Trang {pageInfo.currentPage}/{pageInfo.pageCount}</strong><button type="button" disabled={!pageInfo.canGoForward || state.status === 'loading'} onClick={() => setOffset(offset + ADMIN_DOCUMENTS_PAGE_SIZE)}>Trang sau</button></div></div>
        </>
      )}

      {detailState && <AdminModal title="Chi tiết tài liệu" eyebrow="Thông tin hệ thống" onClose={closeDetail}>
        {detailState.status === 'loading' && <div className="admin-detail-loading" role="status" aria-busy="true"><span /><span /><span /><p>Đang tải chi tiết tài liệu...</p></div>}
        {detailState.status === 'error' && <div className="admin-detail-error" role="alert"><Icon name="refresh" size={24} /><p>{detailState.error}</p><button type="button" onClick={() => openDetail(detailState.document)}>Thử lại</button></div>}
        {detailState.status === 'ready' && (() => {
          const detail = detailState.detail
          return <><div className="admin-detail-document"><span className={`admin-document-cell__icon admin-document-cell__icon--${detail.file_type.toLowerCase()}`}><Icon name="file" size={25} /></span><div><strong>{detail.title}</strong><span>{detail.original_filename}</span></div></div><dl className="admin-detail-list admin-document-detail-list">
            <DetailRow label="ID tài liệu">#{detail.id}</DetailRow><DetailRow label="Loại file">{detail.file_type}</DetailRow><DetailRow label="Dung lượng">{formatAdminDocumentSize(detail.file_size)}</DetailRow><DetailRow label="Kiểu nội dung">{detail.mime_type}</DetailRow><DetailRow label="Trạng thái xử lý"><StatusBadge presentation={getDocumentStatusPresentation(detail.status)} /></DetailRow><DetailRow label="Trạng thái hỏi đáp AI"><StatusBadge presentation={getRagStatusPresentation(detail.rag_status)} /></DetailRow><DetailRow label="Số trang">{detail.page_count ?? 'Chưa xác định'}</DetailRow><DetailRow label="Số ký tự">{detail.character_count?.toLocaleString('vi-VN') ?? 'Chưa xác định'}</DetailRow><DetailRow label="Chủ sở hữu">@{detail.owner.username} · #{detail.owner.id}</DetailRow><DetailRow label="Họ tên">{detail.owner.full_name}</DetailRow><DetailRow label="Ngày tải">{formatAdminDocumentDate(detail.created_at, true)}</DetailRow><DetailRow label="Cập nhật">{formatAdminDocumentDate(detail.updated_at, true)}</DetailRow><DetailRow label="Xử lý xong">{formatAdminDocumentDate(detail.processed_at, true)}</DetailRow><DetailRow label="Sẵn sàng cho AI">{formatAdminDocumentDate(detail.indexed_at, true)}</DetailRow>
          </dl><p className="admin-detail-note">Trang quản trị chỉ hiển thị thông tin cơ bản. Nội dung tài liệu và dữ liệu hỏi đáp riêng tư không được cung cấp tại đây.</p></>
        })()}
      </AdminModal>}
    </section>
  )
}

export default AdminDocuments
