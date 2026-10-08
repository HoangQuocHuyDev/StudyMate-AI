import { useEffect, useMemo, useState } from 'react'
import Header from './Header'
import Icon from './Icons'
import Sidebar from './Sidebar'
import './Documents.css'

const documents = [
  { id: 1, name: 'Giáo trình Trí tuệ nhân tạo', type: 'PDF', date: '08/10/2026', status: 'Hoàn tất', pages: '128 trang' },
  { id: 2, name: 'Bài giảng Kinh tế vi mô', type: 'DOCX', date: '06/10/2026', status: 'Hoàn tất', pages: '42 trang' },
  { id: 3, name: 'Ghi chú ôn tập Cấu trúc dữ liệu', type: 'TXT', date: '03/10/2026', status: 'Đang xử lý', pages: '18 KB' },
  { id: 4, name: 'Nhập môn Machine Learning', type: 'PDF', date: '28/09/2026', status: 'Chờ xử lý', pages: '86 trang' },
  { id: 5, name: 'Tổng hợp câu hỏi Pháp luật đại cương', type: 'DOCX', date: '24/09/2026', status: 'Hoàn tất', pages: '31 trang' },
  { id: 6, name: 'Từ vựng tiếng Anh chuyên ngành', type: 'TXT', date: '20/09/2026', status: 'Hoàn tất', pages: '26 KB' },
]

const filters = ['Tất cả', 'PDF', 'DOCX', 'TXT']

function DocumentCard({ document }) {
  const statusClass = document.status === 'Hoàn tất' ? 'complete' : document.status === 'Đang xử lý' ? 'processing' : 'waiting'

  return (
    <article className="document-card">
      <div className={`document-card__file document-card__file--${document.type.toLowerCase()}`}>
        <Icon name="file" size={25} />
        <span>{document.type}</span>
      </div>

      <div className="document-card__body">
        <div className="document-card__heading">
          <div>
            <h3 title={document.name}>{document.name}</h3>
            <p>{document.type} · {document.pages} · Tải lên {document.date}</p>
          </div>
          <span className={`document-status document-status--${statusClass}`}><i />{document.status}</span>
        </div>

        <div className="document-card__actions" aria-label={`Thao tác với ${document.name}`}>
          <button type="button"><Icon name="eye" size={16} />Xem</button>
          <button type="button"><Icon name="summary" size={16} />Tóm tắt</button>
          <button type="button"><Icon name="chat" size={16} />Hỏi đáp AI</button>
          <button className="document-action--delete" type="button" aria-label={`Xóa ${document.name}`}><Icon name="trash" size={16} /><span>Xóa</span></button>
        </div>
      </div>
    </article>
  )
}

function Documents({ isSidebarOpen, onOpenSidebar, onCloseSidebar }) {
  const [query, setQuery] = useState('')
  const [activeFilter, setActiveFilter] = useState('Tất cả')

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

  const filteredDocuments = useMemo(() => {
    const normalizedQuery = query.trim().toLocaleLowerCase('vi')
    return documents.filter((document) => {
      const matchesName = document.name.toLocaleLowerCase('vi').includes(normalizedQuery)
      const matchesType = activeFilter === 'Tất cả' || document.type === activeFilter
      return matchesName && matchesType
    })
  }, [activeFilter, query])

  const resetFilters = () => {
    setQuery('')
    setActiveFilter('Tất cả')
  }

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
            <button className="documents-upload" type="button"><Icon name="upload" size={18} />Tải tài liệu lên</button>
          </section>

          <section className="documents-toolbar" aria-label="Tìm kiếm và lọc tài liệu">
            <label className="documents-search">
              <Icon name="search" size={19} />
              <input type="search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Tìm kiếm theo tên tài liệu..." aria-label="Tìm kiếm theo tên tài liệu" />
              {query && <button type="button" onClick={() => setQuery('')} aria-label="Xóa nội dung tìm kiếm"><Icon name="close" size={16} /></button>}
            </label>
            <div className="document-filters" aria-label="Lọc theo định dạng">
              {filters.map((filter) => (
                <button className={activeFilter === filter ? 'document-filter--active' : ''} type="button" key={filter} onClick={() => setActiveFilter(filter)} aria-pressed={activeFilter === filter}>{filter}</button>
              ))}
            </div>
          </section>

          <section className="documents-list" aria-labelledby="documents-list-title">
            <div className="documents-list__heading">
              <h2 id="documents-list-title">Danh sách tài liệu</h2>
              <span>{filteredDocuments.length} tài liệu</span>
            </div>

            {filteredDocuments.length > 0 ? (
              <div className="documents-grid">
                {filteredDocuments.map((document) => <DocumentCard document={document} key={document.id} />)}
              </div>
            ) : (
              <div className="documents-empty">
                <div className="documents-empty__icon"><Icon name="documents" size={28} /></div>
                <h3>Chưa tìm thấy tài liệu</h3>
                <p>Không có tài liệu phù hợp với từ khóa hoặc bộ lọc bạn đang chọn.</p>
                <div>
                  <button className="documents-empty__reset" type="button" onClick={resetFilters}>Xóa bộ lọc</button>
                  <button className="documents-upload" type="button"><Icon name="upload" size={17} />Tải tài liệu lên</button>
                </div>
              </div>
            )}
          </section>
        </main>
      </div>
    </div>
  )
}

export default Documents
