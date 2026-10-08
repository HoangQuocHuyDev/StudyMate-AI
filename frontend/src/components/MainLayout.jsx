import { useEffect } from 'react'
import wavingHand from '../assets/waving-hand-3d.png'
import Header from './Header'
import Icon from './Icons'
import Sidebar from './Sidebar'

const features = [
  { icon: 'upload', title: 'Tải lên tài liệu', description: 'Lưu trữ và quản lý tài liệu học tập của bạn ở một nơi.', link: 'Thêm tài liệu', tone: 'blue' },
  { icon: 'sparkle', title: 'Tóm tắt thông minh', description: 'Nắm bắt nội dung chính từ tài liệu dài chỉ trong vài phút.', link: 'Bắt đầu tóm tắt', tone: 'violet' },
  { icon: 'chat', title: 'Hỏi đáp cùng AI', description: 'Đặt câu hỏi và nhận câu trả lời dựa trên chính tài liệu của bạn.', link: 'Đặt câu hỏi', tone: 'cyan' },
]

function MainLayout({ isSidebarOpen, onOpenSidebar, onCloseSidebar }) {
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

  return (
    <div className="app-shell">
      <Sidebar isOpen={isSidebarOpen} onClose={onCloseSidebar} />
      <button className={`sidebar-overlay ${isSidebarOpen ? 'sidebar-overlay--visible' : ''}`} type="button" onClick={onCloseSidebar} aria-label="Đóng thanh điều hướng" tabIndex={isSidebarOpen ? 0 : -1} />

      <div className="app-main">
        <Header onOpenSidebar={onOpenSidebar} />
        <main className="main-content">
          <section className="welcome" aria-labelledby="welcome-title">
            <div className="welcome__copy">
              <span className="welcome__badge"><Icon name="sparkle" size={15} /> Trợ lý học tập AI</span>
              <h2 id="welcome-title">Chào buổi sáng, Minh! <img className="welcome__wave" src={wavingHand} alt="" /></h2>
              <p>Sẵn sàng học hiệu quả hơn hôm nay? Hãy bắt đầu với tài liệu của bạn.</p>
            </div>
            <div className="welcome__visual" aria-hidden="true">
              <span className="orbit orbit--one" /><span className="orbit orbit--two" />
              <div className="visual-icon"><Icon name="library" size={34} /></div>
              <span className="visual-spark"><Icon name="sparkle" size={18} /></span>
            </div>
          </section>

          <section className="features" aria-labelledby="features-title">
            <div className="section-heading">
              <div><p className="section-heading__eyebrow">Bắt đầu nhanh</p><h2 id="features-title">Bạn muốn làm gì?</h2></div>
              <p>Những công cụ giúp việc học của bạn nhẹ nhàng hơn.</p>
            </div>
            <div className="feature-grid">
              {features.map((feature) => (
                <article className="feature-card" key={feature.title}>
                  <div className={`feature-card__icon feature-card__icon--${feature.tone}`}><Icon name={feature.icon} size={23} /></div>
                  <h3>{feature.title}</h3>
                  <p>{feature.description}</p>
                  <button type="button" className="feature-card__link">{feature.link}<Icon name="arrow" size={17} /></button>
                </article>
              ))}
            </div>
          </section>
        </main>
      </div>
    </div>
  )
}

export default MainLayout
