import { useEffect, useRef, useState } from 'react'
import Header from './Header'
import Icon from './Icons'
import Sidebar from './Sidebar'
import './Summarize.css'

const sampleDocuments = [
  { id: 'ai-textbook', name: 'Giáo trình Trí tuệ nhân tạo', type: 'PDF', meta: '128 trang' },
  { id: 'microeconomics', name: 'Bài giảng Kinh tế vi mô', type: 'DOCX', meta: '42 trang' },
  { id: 'data-structures', name: 'Ghi chú ôn tập Cấu trúc dữ liệu', type: 'TXT', meta: '18 KB' },
  { id: 'machine-learning', name: 'Nhập môn Machine Learning', type: 'PDF', meta: '86 trang' },
]

const lengthOptions = [
  { id: 'short', label: 'Ngắn gọn', description: 'Các ý chính quan trọng nhất', estimate: 'Khoảng 1–2 phút đọc' },
  { id: 'standard', label: 'Tiêu chuẩn', description: 'Cân bằng giữa độ dài và chi tiết', estimate: 'Khoảng 3–5 phút đọc' },
  { id: 'detailed', label: 'Chi tiết', description: 'Đầy đủ luận điểm và giải thích', estimate: 'Khoảng 7–10 phút đọc' },
]

const summaryByLength = {
  short: {
    overview: 'Tài liệu giới thiệu các nền tảng cốt lõi của trí tuệ nhân tạo, từ cách máy tính biểu diễn tri thức đến những phương pháp giúp hệ thống học và đưa ra quyết định.',
    points: ['AI mô phỏng một số khả năng tư duy và giải quyết vấn đề của con người.', 'Học máy giúp hệ thống cải thiện hiệu quả dựa trên dữ liệu.', 'Chất lượng dữ liệu và cách đánh giá mô hình quyết định độ tin cậy của kết quả.'],
  },
  standard: {
    overview: 'Tài liệu cung cấp cái nhìn tổng quan về trí tuệ nhân tạo và những thành phần quan trọng trong quá trình xây dựng một hệ thống thông minh. Nội dung đi từ biểu diễn tri thức, tìm kiếm lời giải đến học máy và đánh giá mô hình.',
    points: ['Trí tuệ nhân tạo tập trung xây dựng hệ thống có khả năng nhận biết, suy luận và hỗ trợ ra quyết định.', 'Các thuật toán tìm kiếm khám phá không gian trạng thái để lựa chọn lời giải phù hợp với mục tiêu.', 'Học máy cho phép mô hình nhận ra quy luật từ dữ liệu thay vì chỉ dựa trên quy tắc được lập trình sẵn.', 'Việc chuẩn hóa dữ liệu, lựa chọn đặc trưng và đánh giá khách quan có vai trò thiết yếu.', 'AI cần được phát triển có trách nhiệm, chú trọng tính minh bạch, công bằng và quyền riêng tư.'],
  },
  detailed: {
    overview: 'Tài liệu hệ thống hóa những kiến thức nền tảng của trí tuệ nhân tạo, giải thích mối liên hệ giữa biểu diễn tri thức, thuật toán tìm kiếm, học máy và quy trình đánh giá. Trọng tâm là cách chuyển một vấn đề thực tế thành mô hình có thể xử lý bằng máy tính, sau đó kiểm chứng chất lượng kết quả bằng dữ liệu phù hợp.',
    points: ['Biểu diễn tri thức giúp máy tính mô hình hóa đối tượng, quan hệ và quy tắc trong một miền bài toán cụ thể.', 'Tìm kiếm và suy luận là hai cơ chế quan trọng để hệ thống khám phá phương án, so sánh chi phí và lựa chọn lời giải.', 'Học có giám sát sử dụng dữ liệu đã gắn nhãn, trong khi học không giám sát tìm cấu trúc ẩn trong dữ liệu.', 'Quy trình xây dựng mô hình gồm thu thập dữ liệu, tiền xử lý, huấn luyện, đánh giá và cải tiến lặp lại.', 'Các thước đo phải được lựa chọn theo mục tiêu thực tế; độ chính xác cao chưa chắc phản ánh đầy đủ chất lượng mô hình.', 'Rủi ro về thiên lệch, quyền riêng tư và khả năng giải thích cần được xem xét xuyên suốt vòng đời hệ thống AI.'],
  },
}

function DocumentSelector({ selectedId, onChange }) {
  const selectedDocument = sampleDocuments.find((document) => document.id === selectedId)

  return (
    <div className="summary-control-group">
      <div className="summary-control-heading">
        <span>01</span>
        <div><h3>Chọn tài liệu</h3><p>Chọn một tài liệu đã tải lên để bắt đầu.</p></div>
      </div>
      <label className="summary-select">
        <Icon name="documents" size={20} />
        <select value={selectedId} onChange={(event) => onChange(event.target.value)} aria-label="Chọn tài liệu cần tóm tắt">
          <option value="">Chọn tài liệu từ thư viện</option>
          {sampleDocuments.map((document) => <option value={document.id} key={document.id}>{document.name}</option>)}
        </select>
        <Icon name="chevronDown" size={18} />
      </label>

      {selectedDocument && (
        <div className="selected-document">
          <div className={`selected-document__icon selected-document__icon--${selectedDocument.type.toLowerCase()}`}><Icon name="file" size={22} /></div>
          <div><strong>{selectedDocument.name}</strong><span>{selectedDocument.type} · {selectedDocument.meta}</span></div>
          <span className="selected-document__ready"><i />Sẵn sàng</span>
        </div>
      )}
    </div>
  )
}

function LengthSelector({ value, onChange }) {
  return (
    <div className="summary-control-group">
      <div className="summary-control-heading">
        <span>02</span>
        <div><h3>Độ dài bản tóm tắt</h3><p>Lựa chọn mức độ chi tiết phù hợp với nhu cầu.</p></div>
      </div>
      <div className="summary-length-options">
        {lengthOptions.map((option) => (
          <label className={value === option.id ? 'summary-length--active' : ''} key={option.id}>
            <input type="radio" name="summaryLength" value={option.id} checked={value === option.id} onChange={() => onChange(option.id)} />
            <span className="summary-length__radio" aria-hidden="true"><i /></span>
            <span className="summary-length__copy"><strong>{option.label}</strong><small>{option.description}</small><em>{option.estimate}</em></span>
          </label>
        ))}
      </div>
    </div>
  )
}

function SummaryResult({ state, result, documentName, onGenerate, onCopy, copied }) {
  if (state === 'processing') {
    return (
      <div className="summary-placeholder summary-placeholder--loading" role="status">
        <div className="summary-loader"><span /><span /><span /></div>
        <h3>Đang tạo bản tóm tắt...</h3>
        <p>StudyMate AI đang phân tích cấu trúc và những ý chính trong tài liệu.</p>
        <div className="summary-progress"><span /></div>
      </div>
    )
  }

  if (!result) {
    return (
      <div className="summary-placeholder">
        <div className="summary-placeholder__icon"><Icon name="sparkle" size={29} /></div>
        <h3>Chưa có bản tóm tắt</h3>
        <p>Chọn tài liệu và độ dài mong muốn, sau đó nhấn “Tạo bản tóm tắt” để xem kết quả minh họa.</p>
      </div>
    )
  }

  return (
    <div className="summary-result">
      <div className="summary-result__notice"><Icon name="sparkle" size={16} /><span><strong>Dữ liệu minh họa</strong> — Đây không phải kết quả do AI tạo thực tế.</span></div>
      <div className="summary-result__header">
        <div><p>Bản tóm tắt</p><h3>{documentName}</h3></div>
        <span>{result.lengthLabel}</span>
      </div>
      <div className="summary-result__content">
        <h4>Tổng quan</h4>
        <p>{result.overview}</p>
        <h4>Những ý chính</h4>
        <ul>{result.points.map((point) => <li key={point}>{point}</li>)}</ul>
      </div>
      <div className="summary-result__actions">
        <button type="button" onClick={onCopy}><Icon name="copy" size={17} />{copied ? 'Đã sao chép' : 'Sao chép'}</button>
        <button className="summary-regenerate" type="button" onClick={onGenerate}><Icon name="refresh" size={17} />Tóm tắt lại</button>
      </div>
    </div>
  )
}

function Summarize({ isSidebarOpen, onOpenSidebar, onCloseSidebar }) {
  const [selectedId, setSelectedId] = useState('')
  const [summaryLength, setSummaryLength] = useState('standard')
  const [status, setStatus] = useState('idle')
  const [result, setResult] = useState(null)
  const [copied, setCopied] = useState(false)
  const processTimer = useRef(null)
  const copyTimer = useRef(null)
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

  useEffect(() => () => {
    window.clearTimeout(processTimer.current)
    window.clearTimeout(copyTimer.current)
  }, [])

  const generateSummary = () => {
    if (!selectedDocument) return
    window.clearTimeout(processTimer.current)
    setStatus('processing')
    setCopied(false)
    processTimer.current = window.setTimeout(() => {
      const content = summaryByLength[summaryLength]
      const lengthLabel = lengthOptions.find((option) => option.id === summaryLength).label
      setResult({ ...content, lengthLabel })
      setStatus('complete')
    }, 1400)
  }

  const copySummary = async () => {
    if (!result) return
    const text = `BẢN TÓM TẮT MINH HỌA — ${selectedDocument.name}\n\nTổng quan\n${result.overview}\n\nNhững ý chính\n${result.points.map((point) => `• ${point}`).join('\n')}`

    try {
      await navigator.clipboard.writeText(text)
    } catch {
      const textArea = document.createElement('textarea')
      textArea.value = text
      textArea.style.position = 'fixed'
      textArea.style.opacity = '0'
      document.body.appendChild(textArea)
      textArea.select()
      document.execCommand('copy')
      textArea.remove()
    }

    setCopied(true)
    window.clearTimeout(copyTimer.current)
    copyTimer.current = window.setTimeout(() => setCopied(false), 1800)
  }

  const changeDocument = (id) => {
    setSelectedId(id)
    setResult(null)
    setStatus('idle')
    setCopied(false)
    window.clearTimeout(processTimer.current)
  }

  return (
    <div className="app-shell">
      <Sidebar isOpen={isSidebarOpen} onClose={onCloseSidebar} />
      <button className={`sidebar-overlay ${isSidebarOpen ? 'sidebar-overlay--visible' : ''}`} type="button" onClick={onCloseSidebar} aria-label="Đóng thanh điều hướng" tabIndex={isSidebarOpen ? 0 : -1} />

      <div className="app-main">
        <Header title="Tóm tắt tài liệu" onOpenSidebar={onOpenSidebar} />
        <main className="main-content summarize-page">
          <section className="summarize-hero" aria-labelledby="summarize-title">
            <p>Trợ lý tóm tắt AI</p>
            <h2 id="summarize-title">Tóm tắt tài liệu</h2>
            <span>Biến tài liệu dài thành những kiến thức ngắn gọn, dễ hiểu với AI</span>
          </section>

          <div className="summarize-workspace">
            <section className="summary-settings" aria-label="Thiết lập bản tóm tắt">
              <DocumentSelector selectedId={selectedId} onChange={changeDocument} />
              <LengthSelector value={summaryLength} onChange={setSummaryLength} />
              <button className="summary-generate" type="button" onClick={generateSummary} disabled={!selectedDocument || status === 'processing'}>
                <Icon name="sparkle" size={19} />
                {status === 'processing' ? 'Đang xử lý...' : 'Tạo bản tóm tắt'}
              </button>
              <p className="summary-settings__note">Kết quả trên trang này chỉ dùng để minh họa giao diện.</p>
            </section>

            <section className="summary-output" aria-label="Kết quả tóm tắt">
              <SummaryResult state={status} result={result} documentName={selectedDocument?.name} onGenerate={generateSummary} onCopy={copySummary} copied={copied} />
            </section>
          </div>
        </main>
      </div>
    </div>
  )
}

export default Summarize
