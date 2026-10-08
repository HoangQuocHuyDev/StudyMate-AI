import { useEffect, useMemo, useState } from 'react'
import Header from './Header'
import Icon from './Icons'
import Sidebar from './Sidebar'
import './History.css'

const initialConversations = [
  {
    id: 1,
    title: 'Khái niệm cơ bản về học máy',
    document: 'Giáo trình Trí tuệ nhân tạo',
    type: 'PDF',
    time: 'Hôm nay, 09:42',
    daysAgo: 0,
    preview: 'Học máy là một nhánh của trí tuệ nhân tạo cho phép hệ thống nhận ra quy luật từ dữ liệu...',
    messages: [
      { role: 'user', content: 'Học máy là gì và khác gì so với lập trình truyền thống?' },
      { role: 'ai', content: 'Theo nội dung minh họa, học máy cho phép hệ thống học quy luật từ dữ liệu thay vì yêu cầu lập trình viên mô tả trước mọi quy tắc. Mô hình được huấn luyện trên các ví dụ và sau đó dùng những quy luật đã học để dự đoán cho dữ liệu mới.' },
      { role: 'user', content: 'Có những nhóm bài toán học máy nào phổ biến?' },
      { role: 'ai', content: 'Ba nhóm thường gặp là học có giám sát, học không giám sát và học tăng cường. Mỗi nhóm khác nhau về loại dữ liệu hướng dẫn và cách mô hình nhận phản hồi trong quá trình học.' },
    ],
  },
  {
    id: 2,
    title: 'Ôn tập cung, cầu và giá cân bằng',
    document: 'Bài giảng Kinh tế vi mô',
    type: 'DOCX',
    time: 'Hôm qua, 20:15',
    daysAgo: 1,
    preview: 'Điểm cân bằng thị trường xuất hiện tại giao điểm của đường cung và đường cầu...',
    messages: [
      { role: 'user', content: 'Giải thích ngắn gọn cơ chế hình thành giá cân bằng.' },
      { role: 'ai', content: 'Theo dữ liệu minh họa, giá cân bằng hình thành tại mức mà lượng người bán sẵn sàng cung cấp bằng lượng người mua mong muốn. Nếu giá lệch khỏi mức này, dư cung hoặc thiếu hụt sẽ tạo áp lực đưa giá trở lại cân bằng.' },
    ],
  },
  {
    id: 3,
    title: 'So sánh mảng và danh sách liên kết',
    document: 'Ghi chú ôn tập Cấu trúc dữ liệu',
    type: 'TXT',
    time: '05/10/2026, 14:30',
    daysAgo: 3,
    preview: 'Mảng hỗ trợ truy cập theo chỉ số nhanh, còn danh sách liên kết linh hoạt hơn khi chèn và xóa...',
    messages: [
      { role: 'user', content: 'Khi nào nên dùng danh sách liên kết thay vì mảng?' },
      { role: 'ai', content: 'Trong ví dụ minh họa, danh sách liên kết phù hợp khi số lượng phần tử thay đổi thường xuyên và ứng dụng cần chèn hoặc xóa ở nhiều vị trí. Mảng phù hợp hơn khi cần truy cập trực tiếp theo chỉ số.' },
    ],
  },
  {
    id: 4,
    title: 'Học có giám sát và không giám sát',
    document: 'Nhập môn Machine Learning',
    type: 'PDF',
    time: '30/09/2026, 10:08',
    daysAgo: 8,
    preview: 'Học có giám sát sử dụng dữ liệu đã gắn nhãn, trong khi học không giám sát tìm cấu trúc ẩn...',
    messages: [
      { role: 'user', content: 'Điểm khác biệt chính giữa hai phương pháp học là gì?' },
      { role: 'ai', content: 'Theo nội dung minh họa, khác biệt chính nằm ở tín hiệu hướng dẫn. Học có giám sát dùng nhãn đúng cho từng ví dụ; học không giám sát không có nhãn và tập trung khám phá các nhóm hoặc cấu trúc tiềm ẩn.' },
    ],
  },
  {
    id: 5,
    title: 'Các nguyên tắc sử dụng AI có trách nhiệm',
    document: 'Giáo trình Trí tuệ nhân tạo',
    type: 'PDF',
    time: '18/09/2026, 16:20',
    daysAgo: 20,
    preview: 'Một hệ thống AI có trách nhiệm cần quan tâm đến tính công bằng, minh bạch và quyền riêng tư...',
    messages: [
      { role: 'user', content: 'Những nguyên tắc nào quan trọng khi phát triển AI?' },
      { role: 'ai', content: 'Nội dung minh họa đề cập đến tính công bằng, minh bạch, khả năng giải thích, bảo vệ quyền riêng tư và cơ chế chịu trách nhiệm khi hệ thống gây ra kết quả ngoài mong muốn.' },
    ],
  },
  {
    id: 6,
    title: 'Bài tập hồi quy tuyến tính',
    document: 'Nhập môn Machine Learning',
    type: 'PDF',
    time: '27/08/2026, 08:55',
    daysAgo: 42,
    preview: 'Hồi quy tuyến tính mô hình hóa mối quan hệ giữa biến đầu vào và giá trị cần dự đoán...',
    messages: [
      { role: 'user', content: 'Mục tiêu của hồi quy tuyến tính là gì?' },
      { role: 'ai', content: 'Theo dữ liệu minh họa, hồi quy tuyến tính tìm một hàm tuyến tính mô tả tốt nhất mối quan hệ giữa đầu vào và đầu ra liên tục, thường bằng cách giảm sai số bình phương giữa dự đoán và giá trị thực.' },
    ],
  },
]

const timeFilters = [
  { id: 'all', label: 'Tất cả' },
  { id: 'today', label: 'Hôm nay', maxDays: 0 },
  { id: 'week', label: '7 ngày qua', maxDays: 7 },
  { id: 'month', label: '30 ngày qua', maxDays: 30 },
]

function ConversationItem({ conversation, onView, onDelete }) {
  return (
    <article className="history-item">
      <div className="history-item__icon"><Icon name="chat" size={21} /></div>
      <div className="history-item__content">
        <div className="history-item__heading">
          <h3>{conversation.title}</h3>
          <time>{conversation.time}</time>
        </div>
        <div className="history-item__document"><Icon name="file" size={13} /><span>{conversation.document}</span><i>{conversation.type}</i></div>
        <p>{conversation.preview}</p>
      </div>
      <div className="history-item__actions">
        <button className="history-view" type="button" onClick={() => onView(conversation)}><Icon name="eye" size={16} />Xem lại</button>
        <button className="history-delete" type="button" onClick={() => onDelete(conversation)} aria-label={`Xóa cuộc trò chuyện ${conversation.title}`}><Icon name="trash" size={16} /><span>Xóa</span></button>
      </div>
    </article>
  )
}

function ConversationDialog({ conversation, onClose }) {
  return (
    <div className="history-modal" role="presentation" onMouseDown={onClose}>
      <section className="history-dialog history-dialog--conversation" role="dialog" aria-modal="true" aria-labelledby="conversation-dialog-title" onMouseDown={(event) => event.stopPropagation()}>
        <header className="history-dialog__header">
          <div className="history-dialog__mark"><Icon name="chat" size={20} /></div>
          <div><p>Cuộc trò chuyện mẫu</p><h2 id="conversation-dialog-title">{conversation.title}</h2><span>{conversation.document} · {conversation.time}</span></div>
          <button type="button" onClick={onClose} aria-label="Đóng chi tiết cuộc trò chuyện"><Icon name="close" size={19} /></button>
        </header>
        <div className="history-dialog__notice"><Icon name="sparkle" size={15} />Dữ liệu minh họa — chưa được lưu trong Database và không phải phản hồi AI thực tế.</div>
        <div className="history-dialog__messages">
          {conversation.messages.map((message, index) => (
            <div className={`history-dialog__message history-dialog__message--${message.role}`} key={`${message.role}-${index}`}>
              <span>{message.role === 'user' ? 'MN' : <Icon name="bot" size={17} />}</span>
              <div><strong>{message.role === 'user' ? 'Bạn' : 'StudyMate AI'}</strong><p>{message.content}</p></div>
            </div>
          ))}
        </div>
        <footer><button type="button" onClick={onClose}>Đóng</button></footer>
      </section>
    </div>
  )
}

function DeleteDialog({ conversation, onCancel, onConfirm }) {
  return (
    <div className="history-modal" role="presentation" onMouseDown={onCancel}>
      <section className="history-dialog history-dialog--confirm" role="alertdialog" aria-modal="true" aria-labelledby="delete-dialog-title" aria-describedby="delete-dialog-description" onMouseDown={(event) => event.stopPropagation()}>
        <div className="history-confirm__icon"><Icon name="trash" size={22} /></div>
        <h2 id="delete-dialog-title">Xóa cuộc trò chuyện?</h2>
        <p id="delete-dialog-description">“{conversation.title}” sẽ bị xóa khỏi danh sách dữ liệu mẫu trên trang này.</p>
        <div className="history-confirm__actions">
          <button type="button" onClick={onCancel}>Hủy</button>
          <button className="history-confirm__delete" type="button" onClick={onConfirm}>Xóa cuộc trò chuyện</button>
        </div>
      </section>
    </div>
  )
}

function History({ isSidebarOpen, onOpenSidebar, onCloseSidebar }) {
  const [conversations, setConversations] = useState(initialConversations)
  const [query, setQuery] = useState('')
  const [activeFilter, setActiveFilter] = useState('all')
  const [selectedConversation, setSelectedConversation] = useState(null)
  const [deleteTarget, setDeleteTarget] = useState(null)

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
    if (!selectedConversation && !deleteTarget) return undefined
    const closeDialog = (event) => {
      if (event.key === 'Escape') {
        setSelectedConversation(null)
        setDeleteTarget(null)
      }
    }
    document.addEventListener('keydown', closeDialog)
    document.body.classList.add('history-modal-visible')
    return () => {
      document.removeEventListener('keydown', closeDialog)
      document.body.classList.remove('history-modal-visible')
    }
  }, [deleteTarget, selectedConversation])

  const filteredConversations = useMemo(() => {
    const normalizedQuery = query.trim().toLocaleLowerCase('vi')
    const selectedFilter = timeFilters.find((filter) => filter.id === activeFilter)
    return conversations.filter((conversation) => {
      const matchesTitle = conversation.title.toLocaleLowerCase('vi').includes(normalizedQuery)
      const matchesTime = selectedFilter.id === 'all' || conversation.daysAgo <= selectedFilter.maxDays
      return matchesTitle && matchesTime
    })
  }, [activeFilter, conversations, query])

  const confirmDelete = () => {
    setConversations((current) => current.filter((conversation) => conversation.id !== deleteTarget.id))
    setDeleteTarget(null)
  }

  const resetFilters = () => {
    setQuery('')
    setActiveFilter('all')
  }

  return (
    <div className="app-shell">
      <Sidebar isOpen={isSidebarOpen} onClose={onCloseSidebar} />
      <button className={`sidebar-overlay ${isSidebarOpen ? 'sidebar-overlay--visible' : ''}`} type="button" onClick={onCloseSidebar} aria-label="Đóng thanh điều hướng" tabIndex={isSidebarOpen ? 0 : -1} />

      <div className="app-main">
        <Header title="Lịch sử trò chuyện" onOpenSidebar={onOpenSidebar} />
        <main className="main-content history-page">
          <section className="history-hero" aria-labelledby="history-title">
            <p>Kho kiến thức đã khám phá</p>
            <h1 id="history-title">Lịch sử trò chuyện</h1>
            <span>Xem lại những cuộc trò chuyện và kiến thức bạn đã khám phá cùng AI</span>
          </section>

          <section className="history-toolbar" aria-label="Tìm kiếm và lọc lịch sử">
            <label className="history-search">
              <Icon name="search" size={19} />
              <input type="search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Tìm kiếm theo tiêu đề cuộc trò chuyện..." aria-label="Tìm kiếm cuộc trò chuyện theo tiêu đề" />
              {query && <button type="button" onClick={() => setQuery('')} aria-label="Xóa nội dung tìm kiếm"><Icon name="close" size={16} /></button>}
            </label>
            <div className="history-filters" aria-label="Lọc theo thời gian">
              {timeFilters.map((filter) => <button className={activeFilter === filter.id ? 'history-filter--active' : ''} type="button" key={filter.id} onClick={() => setActiveFilter(filter.id)} aria-pressed={activeFilter === filter.id}>{filter.label}</button>)}
            </div>
          </section>

          <section className="history-list" aria-labelledby="history-list-title">
            <div className="history-list__heading"><h2 id="history-list-title">Các cuộc trò chuyện</h2><span>{filteredConversations.length} phiên</span></div>
            {filteredConversations.length ? (
              <div className="history-list__items">
                {filteredConversations.map((conversation) => <ConversationItem conversation={conversation} onView={setSelectedConversation} onDelete={setDeleteTarget} key={conversation.id} />)}
              </div>
            ) : (
              <div className="history-empty">
                <div><Icon name="history" size={29} /></div>
                <h3>Chưa có cuộc trò chuyện phù hợp</h3>
                <p>Thử thay đổi từ khóa, bộ lọc hoặc bắt đầu một cuộc trò chuyện mới với tài liệu.</p>
                <div className="history-empty__actions">
                  {(query || activeFilter !== 'all') && <button type="button" onClick={resetFilters}>Xóa bộ lọc</button>}
                  <a href="/chat"><Icon name="chat" size={17} />Bắt đầu trò chuyện</a>
                </div>
              </div>
            )}
          </section>
        </main>
      </div>

      {selectedConversation && <ConversationDialog conversation={selectedConversation} onClose={() => setSelectedConversation(null)} />}
      {deleteTarget && <DeleteDialog conversation={deleteTarget} onCancel={() => setDeleteTarget(null)} onConfirm={confirmDelete} />}
    </div>
  )
}

export default History
