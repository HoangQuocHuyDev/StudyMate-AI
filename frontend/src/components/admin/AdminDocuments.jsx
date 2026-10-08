import { useMemo, useState } from 'react'
import Icon from '../Icons'
import AdminModal from './AdminModal'

function AdminDocuments({ documents, onDelete }) {
  const [query, setQuery] = useState('')
  const [typeFilter, setTypeFilter] = useState('all')
  const [statusFilter, setStatusFilter] = useState('all')
  const [detailDocument, setDetailDocument] = useState(null)
  const [deleteTarget, setDeleteTarget] = useState(null)

  const filteredDocuments = useMemo(() => {
    const normalizedQuery = query.trim().toLocaleLowerCase('vi')
    return documents.filter((document) => {
      const matchesQuery = `${document.name} ${document.owner}`.toLocaleLowerCase('vi').includes(normalizedQuery)
      const matchesType = typeFilter === 'all' || document.type === typeFilter
      const matchesStatus = statusFilter === 'all' || document.status === statusFilter
      return matchesQuery && matchesType && matchesStatus
    })
  }, [documents, query, statusFilter, typeFilter])

  const statusLabel = (status) => status === 'complete' ? 'Hoàn tất' : status === 'processing' ? 'Đang xử lý' : 'Lỗi xử lý'

  const confirmDelete = () => {
    onDelete(deleteTarget.id)
    setDeleteTarget(null)
  }

  return (
    <section className="admin-management" aria-labelledby="admin-documents-title">
      <div className="admin-section-heading"><div><p>Kho tài liệu hệ thống</p><h2 id="admin-documents-title">Danh sách tài liệu</h2><span>Theo dõi trạng thái và quản lý tài liệu mẫu đã được tải lên.</span></div><strong>{documents.length} tài liệu</strong></div>
      <div className="admin-toolbar">
        <label className="admin-search"><Icon name="search" size={18} /><input type="search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Tìm theo tên tài liệu hoặc người tải..." aria-label="Tìm kiếm tài liệu quản trị" />{query && <button type="button" onClick={() => setQuery('')} aria-label="Xóa tìm kiếm"><Icon name="close" size={15} /></button>}</label>
        <label className="admin-filter"><span>Định dạng</span><select value={typeFilter} onChange={(event) => setTypeFilter(event.target.value)}><option value="all">Tất cả</option><option value="PDF">PDF</option><option value="DOCX">DOCX</option><option value="TXT">TXT</option></select><Icon name="chevronDown" size={15} /></label>
        <label className="admin-filter"><span>Trạng thái</span><select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}><option value="all">Tất cả</option><option value="complete">Hoàn tất</option><option value="processing">Đang xử lý</option><option value="error">Lỗi xử lý</option></select><Icon name="chevronDown" size={15} /></label>
      </div>

      {filteredDocuments.length ? (
        <div className="admin-table-wrap">
          <table className="admin-table admin-documents-table">
            <thead><tr><th>Tài liệu</th><th>Người tải</th><th>Ngày tải lên</th><th>Trạng thái</th><th><span className="sr-only">Thao tác</span></th></tr></thead>
            <tbody>
              {filteredDocuments.map((document) => (
                <tr key={document.id}>
                  <td data-label="Tài liệu"><div className="admin-document-cell"><span className={`admin-document-cell__icon admin-document-cell__icon--${document.type.toLowerCase()}`}><Icon name="file" size={19} /></span><div><strong>{document.name}</strong><small>{document.type} · {document.size}</small></div></div></td>
                  <td data-label="Người tải"><span className="admin-owner">{document.owner}</span></td>
                  <td data-label="Ngày tải lên"><time>{document.uploadedAt}</time></td>
                  <td data-label="Trạng thái"><span className={`admin-status admin-status--${document.status}`}><i />{statusLabel(document.status)}</span></td>
                  <td><div className="admin-row-actions"><button type="button" onClick={() => setDetailDocument(document)}><Icon name="eye" size={16} />Xem</button><button className="admin-action--delete" type="button" onClick={() => setDeleteTarget(document)}><Icon name="trash" size={16} />Xóa</button></div></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="admin-empty"><div><Icon name="documents" size={27} /></div><h3>Không tìm thấy tài liệu</h3><p>Hãy thử thay đổi từ khóa hoặc bộ lọc hiện tại.</p><button type="button" onClick={() => { setQuery(''); setTypeFilter('all'); setStatusFilter('all') }}>Xóa bộ lọc</button></div>
      )}

      {detailDocument && (
        <AdminModal title={detailDocument.name} eyebrow="Thông tin tài liệu mẫu" onClose={() => setDetailDocument(null)}>
          <div className="admin-detail-document"><div className={`admin-document-cell__icon admin-document-cell__icon--${detailDocument.type.toLowerCase()}`}><Icon name="file" size={25} /></div><div><strong>{detailDocument.name}</strong><span>{detailDocument.type} · {detailDocument.size}</span></div></div>
          <dl className="admin-detail-list"><div><dt>Người tải lên</dt><dd>{detailDocument.owner}</dd></div><div><dt>Ngày tải lên</dt><dd>{detailDocument.uploadedAt}</dd></div><div><dt>Định dạng</dt><dd>{detailDocument.type}</dd></div><div><dt>Trạng thái xử lý</dt><dd>{statusLabel(detailDocument.status)}</dd></div></dl>
          <p className="admin-detail-note">Thông tin trên là dữ liệu minh họa, không lấy từ tài liệu thật trong hệ thống.</p>
        </AdminModal>
      )}

      {deleteTarget && (
        <AdminModal confirm onClose={() => setDeleteTarget(null)}>
          <div className="admin-confirm__icon"><Icon name="trash" size={23} /></div>
          <h2 id="admin-dialog-title">Xóa tài liệu?</h2>
          <p>“{deleteTarget.name}” sẽ bị xóa khỏi danh sách dữ liệu mẫu trên trang quản trị.</p>
          <div className="admin-confirm__actions"><button type="button" onClick={() => setDeleteTarget(null)}>Hủy</button><button className="admin-confirm__primary admin-confirm__primary--danger" type="button" onClick={confirmDelete}>Xóa tài liệu</button></div>
        </AdminModal>
      )}
    </section>
  )
}

export default AdminDocuments
