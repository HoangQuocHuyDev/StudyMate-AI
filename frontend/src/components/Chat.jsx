import { useEffect, useRef, useState } from 'react'
import Header from './Header'
import Icon from './Icons'
import Sidebar from './Sidebar'
import './Chat.css'

const sampleDocuments = [
  {
    id: 'ai-textbook',
    name: 'Giáo trình Trí tuệ nhân tạo',
    type: 'PDF',
    meta: '128 trang',
    uploaded: '08/10/2026',
    pages: 'Trang 34–36',
    answer: 'Theo nội dung minh họa, học máy là một nhánh của trí tuệ nhân tạo cho phép hệ thống nhận ra quy luật từ dữ liệu và cải thiện kết quả mà không cần mô tả trước mọi quy tắc. Quy trình thường gồm chuẩn bị dữ liệu, huấn luyện mô hình và đánh giá trên dữ liệu chưa từng được sử dụng khi học.',
  },
  {
    id: 'microeconomics',
    name: 'Bài giảng Kinh tế vi mô',
    type: 'DOCX',
    meta: '42 trang',
    uploaded: '06/10/2026',
    pages: 'Trang 12–14',
    answer: 'Theo nội dung minh họa, cung và cầu cùng tác động để hình thành mức giá cân bằng trên thị trường. Khi các yếu tố khác không đổi, giá tăng thường làm lượng cầu giảm nhưng khuyến khích lượng cung tăng. Điểm giao nhau giữa hai đường biểu diễn trạng thái cân bằng.',
  },
  {
    id: 'data-structures',
    name: 'Ghi chú ôn tập Cấu trúc dữ liệu',
    type: 'TXT',
    meta: '18 KB',
    uploaded: '03/10/2026',
    pages: null,
    answer: 'Theo nội dung minh họa, việc lựa chọn cấu trúc dữ liệu phụ thuộc vào thao tác được thực hiện thường xuyên nhất. Mảng phù hợp khi cần truy cập nhanh theo chỉ số; danh sách liên kết thuận lợi cho chèn và xóa; bảng băm hữu ích khi cần tra cứu khóa với tốc độ cao.',
  },
  {
    id: 'machine-learning',
    name: 'Nhập môn Machine Learning',
    type: 'PDF',
    meta: '86 trang',
    uploaded: '28/09/2026',
    pages: 'Trang 20–23',
    answer: 'Theo nội dung minh họa, học có giám sát sử dụng các ví dụ đã có nhãn để học mối quan hệ giữa đầu vào và kết quả mong muốn. Hai nhóm bài toán phổ biến là phân loại và hồi quy. Hiệu quả mô hình cần được kiểm tra trên tập dữ liệu độc lập để hạn chế đánh giá quá lạc quan.',
  },
]

const suggestions = [
  'Tóm tắt những ý chính của tài liệu',
  'Giải thích khái niệm quan trọng nhất',
  'Tạo 5 câu hỏi ôn tập từ tài liệu',
]

function DocumentPanel({ selectedId, onSelect }) {
  const selectedDocument = sampleDocuments.find((document) => document.id === selectedId)

  return (
    <aside className="chat-documents" aria-label="Chọn tài liệu hỏi đáp">
      <div className="chat-documents__heading">
        <div className="chat-documents__heading-icon"><Icon name="documents" size={20} /></div>
        <div><h2>Tài liệu tham chiếu</h2><p>AI sẽ trả lời dựa trên tài liệu bạn chọn.</p></div>
      </div>

      <label className="chat-document-select">
        <span>Chọn tài liệu</span>
        <div>
          <select value={selectedId} onChange={(event) => onSelect(event.target.value)}>
            {sampleDocuments.map((document) => <option value={document.id} key={document.id}>{document.name}</option>)}
          </select>
          <Icon name="chevronDown" size={17} />
        </div>
      </label>

      <div className="chat-selected-document">
        <div className={`chat-selected-document__file chat-selected-document__file--${selectedDocument.type.toLowerCase()}`}>
          <Icon name="file" size={28} /><span>{selectedDocument.type}</span>
        </div>
        <h3>{selectedDocument.name}</h3>
        <dl>
          <div><dt>Định dạng</dt><dd>{selectedDocument.type}</dd></div>
          <div><dt>Dung lượng</dt><dd>{selectedDocument.meta}</dd></div>
          <div><dt>Ngày tải lên</dt><dd>{selectedDocument.uploaded}</dd></div>
        </dl>
        <span className="chat-selected-document__status"><i />Sẵn sàng hỏi đáp</span>
      </div>

      <div className="chat-documents__note"><Icon name="sparkle" size={16} /><p>Chức năng truy xuất tài liệu hiện đang được mô phỏng.</p></div>
    </aside>
  )
}

function ChatMessage({ message, onCopy, copied }) {
  if (message.role === 'user') {
    return (
      <div className="chat-message chat-message--user">
        <div className="chat-message__avatar">MN</div>
        <div className="chat-message__bubble"><p>{message.content}</p></div>
      </div>
    )
  }

  return (
    <div className="chat-message chat-message--ai">
      <div className="chat-message__avatar"><Icon name="bot" size={19} /></div>
      <div className="chat-message__body">
        <div className="chat-message__label"><strong>StudyMate AI</strong><span>Nội dung minh họa – chưa kết nối AI</span></div>
        <div className="chat-message__bubble">
          <p>{message.content}</p>
          {message.source && (
            <div className="chat-source">
              <div className="chat-source__title"><Icon name="file" size={15} /><strong>Nguồn tham khảo</strong><span>Minh họa</span></div>
              <p>{message.source.name}</p>
              <small>{message.source.pages ? `${message.source.pages} · ` : ''}Nguồn dữ liệu mẫu, không phải kết quả truy xuất thực tế</small>
            </div>
          )}
        </div>
        <button className="chat-copy" type="button" onClick={() => onCopy(message)}><Icon name={copied ? 'check' : 'copy'} size={15} />{copied ? 'Đã sao chép' : 'Sao chép câu trả lời'}</button>
      </div>
    </div>
  )
}

function TypingIndicator() {
  return (
    <div className="chat-message chat-message--ai" role="status">
      <div className="chat-message__avatar"><Icon name="bot" size={19} /></div>
      <div className="chat-message__body">
        <div className="chat-message__label"><strong>StudyMate AI</strong><span>Đang tìm trong tài liệu...</span></div>
        <div className="chat-typing"><i /><i /><i /></div>
      </div>
    </div>
  )
}

function Chat({ isSidebarOpen, onOpenSidebar, onCloseSidebar }) {
  const [selectedId, setSelectedId] = useState(sampleDocuments[0].id)
  const [question, setQuestion] = useState('')
  const [messages, setMessages] = useState([])
  const [isAnswering, setIsAnswering] = useState(false)
  const [copiedId, setCopiedId] = useState(null)
  const answerTimer = useRef(null)
  const copyTimer = useRef(null)
  const conversationEnd = useRef(null)
  const inputRef = useRef(null)
  const selectedDocument = sampleDocuments.find((document) => document.id === selectedId)

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
    conversationEnd.current?.scrollIntoView({ block: 'end' })
  }, [isAnswering, messages])

  useEffect(() => () => {
    window.clearTimeout(answerTimer.current)
    window.clearTimeout(copyTimer.current)
  }, [])

  const sendQuestion = () => {
    const cleanQuestion = question.trim()
    if (!cleanQuestion || isAnswering) return

    const userMessage = { id: `user-${Date.now()}`, role: 'user', content: cleanQuestion }
    setMessages((current) => [...current, userMessage])
    setQuestion('')
    setIsAnswering(true)

    answerTimer.current = window.setTimeout(() => {
      const aiMessage = {
        id: `ai-${Date.now()}`,
        role: 'ai',
        content: selectedDocument.answer,
        source: { name: selectedDocument.name, pages: selectedDocument.pages },
      }
      setMessages((current) => [...current, aiMessage])
      setIsAnswering(false)
    }, 1300)
  }

  const handleKeyDown = (event) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      sendQuestion()
    }
  }

  const chooseSuggestion = (suggestion) => {
    setQuestion(suggestion)
    inputRef.current?.focus()
  }

  const changeDocument = (id) => {
    window.clearTimeout(answerTimer.current)
    setSelectedId(id)
    setMessages([])
    setQuestion('')
    setIsAnswering(false)
    setCopiedId(null)
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

  return (
    <div className="app-shell">
      <Sidebar isOpen={isSidebarOpen} onClose={onCloseSidebar} />
      <button className={`sidebar-overlay ${isSidebarOpen ? 'sidebar-overlay--visible' : ''}`} type="button" onClick={onCloseSidebar} aria-label="Đóng thanh điều hướng" tabIndex={isSidebarOpen ? 0 : -1} />

      <div className="app-main">
        <Header title="Hỏi đáp AI" onOpenSidebar={onOpenSidebar} />
        <main className="main-content chat-page">
          <div className="chat-page__heading">
            <p>Trò chuyện với tài liệu</p>
            <h1>Hỏi đáp AI</h1>
            <span>Đặt câu hỏi và khám phá kiến thức ngay trong tài liệu học tập của bạn.</span>
          </div>

          <div className="chat-workspace">
            <DocumentPanel selectedId={selectedId} onSelect={changeDocument} />

            <section className="chat-conversation" aria-label="Cuộc trò chuyện với AI">
              <div className="chat-conversation__topbar">
                <div className="chat-ai-mark"><Icon name="bot" size={21} /></div>
                <div><strong>Trợ lý StudyMate</strong><span><i />Sẵn sàng hỗ trợ</span></div>
                <span className="chat-conversation__mode">Chế độ minh họa</span>
              </div>

              <div className={`chat-thread ${messages.length === 0 ? 'chat-thread--empty' : ''}`}>
                {messages.length === 0 ? (
                  <div className="chat-welcome">
                    <div className="chat-welcome__icon"><Icon name="sparkle" size={28} /></div>
                    <h2>Bạn muốn tìm hiểu điều gì từ tài liệu của mình?</h2>
                    <p>Hãy đặt câu hỏi hoặc chọn một gợi ý để bắt đầu cuộc trò chuyện.</p>
                    <div className="chat-suggestions">
                      {suggestions.map((suggestion) => <button type="button" key={suggestion} onClick={() => chooseSuggestion(suggestion)}>{suggestion}<Icon name="arrow" size={15} /></button>)}
                    </div>
                  </div>
                ) : (
                  <div className="chat-messages">
                    {messages.map((message) => <ChatMessage message={message} onCopy={copyAnswer} copied={copiedId === message.id} key={message.id} />)}
                    {isAnswering && <TypingIndicator />}
                    <div ref={conversationEnd} />
                  </div>
                )}
              </div>

              <div className="chat-composer-wrap">
                <div className="chat-composer">
                  <textarea ref={inputRef} value={question} onChange={(event) => setQuestion(event.target.value)} onKeyDown={handleKeyDown} rows="1" placeholder="Nhập câu hỏi về tài liệu..." aria-label="Câu hỏi dành cho AI" disabled={isAnswering} />
                  <button type="button" onClick={sendQuestion} disabled={!question.trim() || isAnswering} aria-label="Gửi câu hỏi"><Icon name="send" size={18} /><span>Gửi</span></button>
                </div>
                <p>Nhấn Enter để gửi · Shift + Enter để xuống dòng · Nội dung trả lời chỉ là minh họa</p>
              </div>
            </section>
          </div>
        </main>
      </div>
    </div>
  )
}

export default Chat
