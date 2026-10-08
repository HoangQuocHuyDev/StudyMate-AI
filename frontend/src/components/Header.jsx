import Icon from './Icons'

function Header({ onOpenSidebar, title = 'Tổng quan' }) {
  return (
    <header className="header">
      <div className="header__title-group">
        <button className="icon-button header__menu" type="button" onClick={onOpenSidebar} aria-label="Mở thanh điều hướng"><Icon name="menu" /></button>
        <div><p className="header__eyebrow">Không gian của bạn</p><h1>{title}</h1></div>
      </div>

      <div className="header__actions">
        <label className="search-box">
          <Icon name="search" size={18} />
          <input type="search" placeholder="Tìm kiếm tài liệu..." aria-label="Tìm kiếm tài liệu toàn cục" />
          <kbd>⌘ K</kbd>
        </label>
        <button className="profile-button" type="button" aria-label="Mở menu tài khoản">
          <span className="avatar">MN</span>
          <span className="profile-copy"><strong>Minh Nguyễn</strong><small>Sinh viên</small></span>
          <span className="profile-chevron" aria-hidden="true">⌄</span>
        </button>
      </div>
    </header>
  )
}

export default Header
