import Icon from '../Icons'

const stats = [
  { label: 'Tổng số người dùng', value: '1.284', change: '+8,2% tháng này', icon: 'users', tone: 'blue' },
  { label: 'Tổng số tài liệu', value: '3.856', change: '+126 tài liệu', icon: 'documents', tone: 'cyan' },
  { label: 'Phiên hỏi đáp AI', value: '12.490', change: '+14,7% tháng này', icon: 'chat', tone: 'violet' },
  { label: 'Tài liệu đang xử lý', value: '18', change: 'Dữ liệu minh họa', icon: 'history', tone: 'amber' },
]

const chartData = [
  { day: 'T2', value: 46 },
  { day: 'T3', value: 64 },
  { day: 'T4', value: 55 },
  { day: 'T5', value: 78 },
  { day: 'T6', value: 68 },
  { day: 'T7', value: 92 },
  { day: 'CN', value: 72 },
]

const activities = [
  { icon: 'user', title: 'Tài khoản mới được tạo', detail: 'Nguyễn Hoàng Anh · 8 phút trước', tone: 'blue' },
  { icon: 'documents', title: 'Tài liệu mới được tải lên', detail: 'Giáo trình Mạng máy tính · 24 phút trước', tone: 'cyan' },
  { icon: 'history', title: 'Hoàn tất xử lý tài liệu', detail: 'Bài giảng Đại số tuyến tính · 42 phút trước', tone: 'violet' },
]

function AdminOverview({ onNavigate }) {
  return (
    <div className="admin-overview">
      <section className="admin-stats" aria-label="Thống kê tổng quan">
        {stats.map((stat) => (
          <article className="admin-stat-card" key={stat.label}>
            <div className={`admin-stat-card__icon admin-stat-card__icon--${stat.tone}`}><Icon name={stat.icon} size={22} /></div>
            <div><p>{stat.label}</p><strong>{stat.value}</strong><span>{stat.change}</span></div>
          </article>
        ))}
      </section>

      <div className="admin-overview-grid">
        <section className="admin-panel admin-chart-panel" aria-labelledby="admin-chart-title">
          <div className="admin-panel__heading"><div><p>Hoạt động hệ thống</p><h2 id="admin-chart-title">Phiên hỏi đáp trong 7 ngày</h2></div><span>Dữ liệu minh họa</span></div>
          <div className="admin-chart" role="img" aria-label="Biểu đồ cột số phiên hỏi đáp trong bảy ngày gần đây">
            <div className="admin-chart__axis"><span>100</span><span>75</span><span>50</span><span>25</span><span>0</span></div>
            <div className="admin-chart__plot">
              {chartData.map((item) => <div className="admin-chart__column" key={item.day}><div><span style={{ height: `${item.value}%` }}><i>{item.value}</i></span></div><small>{item.day}</small></div>)}
            </div>
          </div>
        </section>

        <section className="admin-panel admin-activity" aria-labelledby="admin-activity-title">
          <div className="admin-panel__heading"><div><p>Cập nhật gần đây</p><h2 id="admin-activity-title">Hoạt động mới</h2></div></div>
          <div className="admin-activity__list">
            {activities.map((activity) => <article key={activity.title}><div className={`admin-activity__icon admin-activity__icon--${activity.tone}`}><Icon name={activity.icon} size={17} /></div><div><strong>{activity.title}</strong><span>{activity.detail}</span></div></article>)}
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
