import Icon from '../Icons'
import { getAdminStatisticCards } from './adminDashboardUi'

function AdminOverview({ displayName, onNavigate }) {
  const statistics = getAdminStatisticCards()

  return (
    <div className="admin-overview">
      <section className="admin-welcome" aria-labelledby="admin-welcome-title">
        <div>
          <span className="admin-welcome__badge"><Icon name="shield" size={15} /> Không gian quản trị</span>
          <h2 id="admin-welcome-title">Xin chào, {displayName}</h2>
          <p>Theo dõi tình trạng hệ thống và truy cập nhanh các khu vực quản lý của StudyMate AI.</p>
        </div>
        <div className="admin-welcome__visual" aria-hidden="true"><Icon name="overview" size={34} /></div>
      </section>

      <div className="admin-section-heading admin-overview__heading">
        <div><p>Tổng quan hệ thống</p><h2>Chỉ số quản trị</h2><span>Số liệu sẽ xuất hiện khi Backend cung cấp Admin API đã xác thực.</span></div>
        <strong>Chưa kết nối dữ liệu</strong>
      </div>

      <section className="admin-stats" aria-label="Thống kê tổng quan">
        {statistics.map((statistic) => (
          <article className="admin-stat-card" key={statistic.key}>
            <div className={`admin-stat-card__icon admin-stat-card__icon--${statistic.tone}`}><Icon name={statistic.icon} size={22} /></div>
            <strong aria-label={`${statistic.label}: chưa có dữ liệu`}>—</strong>
            <h3>{statistic.label}</h3>
            <p>{statistic.description}</p>
          </article>
        ))}
      </section>

      <div className="admin-overview-grid">
        <section className="admin-panel admin-chart-panel" aria-labelledby="admin-chart-title">
          <div className="admin-panel__heading"><div><p>Hoạt động hệ thống</p><h2 id="admin-chart-title">Biểu đồ hoạt động</h2></div><span>Đang chờ dữ liệu</span></div>
          <div className="admin-chart-empty" role="status">
            <span><Icon name="overview" size={28} /></span>
            <h3>Chưa có dữ liệu biểu đồ</h3>
            <p>Cần Admin API để hiển thị hoạt động hệ thống chính xác theo thời gian.</p>
          </div>
        </section>

        <section className="admin-panel admin-activity" aria-labelledby="admin-activity-title">
          <div className="admin-panel__heading"><div><p>Cập nhật gần đây</p><h2 id="admin-activity-title">Hoạt động mới</h2></div><span>Trống</span></div>
          <div className="admin-activity-empty" role="status">
            <span><Icon name="history" size={25} /></span>
            <h3>Chưa có hoạt động để hiển thị</h3>
            <p>Nhật ký thực sẽ được hiển thị khi có API quản trị tương ứng.</p>
          </div>
          <div className="admin-quick-actions">
            <button type="button" onClick={() => onNavigate('users')}><Icon name="users" size={17} />Quản lý người dùng<Icon name="arrow" size={15} /></button>
            <button type="button" onClick={() => onNavigate('documents')}><Icon name="documents" size={17} />Quản lý tài liệu<Icon name="arrow" size={15} /></button>
          </div>
        </section>
      </div>
    </div>
  )
}

export default AdminOverview
