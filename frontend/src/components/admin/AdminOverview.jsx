import {
  useCallback,
  useEffect,
  useReducer,
  useRef,
} from 'react'
import { useAuth } from '../../contexts/AuthContext'
import {
  getAdminDashboardActivity,
  getAdminDashboardOverview,
  getAdminRecentActivities,
} from '../../services/adminDashboardService'
import Icon from '../Icons'
import {
  ADMIN_ACTIVITY_SERIES,
  ADMIN_STATISTICS,
  adminDashboardReducer,
  getAdminActivityChart,
  getAdminDashboardErrorMessage,
  getAdminRecentActivityPresentation,
  getAdminStatisticCards,
  initialAdminDashboardState,
  validateAdminActivityResponse,
  validateAdminOverviewResponse,
  validateAdminRecentActivitiesResponse,
} from './adminDashboardUi'


const SECTION_CONFIG = Object.freeze({
  overview: {
    load: getAdminDashboardOverview,
    validate: validateAdminOverviewResponse,
  },
  activity: {
    load: getAdminDashboardActivity,
    validate: validateAdminActivityResponse,
  },
  recent: {
    load: (options) => getAdminRecentActivities({ ...options, limit: 10 }),
    validate: validateAdminRecentActivitiesResponse,
  },
})

function SectionError({ message, onRetry }) {
  return (
    <div className="admin-data-state admin-data-state--error" role="alert">
      <span><Icon name="refresh" size={24} /></span>
      <h3>Chưa thể tải dữ liệu</h3>
      <p>{message}</p>
      <button type="button" onClick={onRetry}>Thử lại</button>
    </div>
  )
}

function RefreshError({ message, onRetry }) {
  return (
    <div className="admin-refresh-error" role="alert">
      <span>{message} Dữ liệu trước đó vẫn được giữ nguyên.</span>
      <button type="button" onClick={onRetry}>Thử lại</button>
    </div>
  )
}

function AdminOverview({ displayName, onNavigate }) {
  const { accessToken } = useAuth()
  const [state, dispatch] = useReducer(
    adminDashboardReducer,
    initialAdminDashboardState,
  )
  const requestsRef = useRef({
    overview: { controller: null, id: 0 },
    activity: { controller: null, id: 0 },
    recent: { controller: null, id: 0 },
  })
  const isMountedRef = useRef(true)

  const loadSection = useCallback(async (section) => {
    const config = SECTION_CONFIG[section]
    const previous = requestsRef.current[section]
    const requestId = previous.id + 1
    const controller = new AbortController()
    previous.controller?.abort()
    requestsRef.current[section] = { controller, id: requestId }
    dispatch({ type: 'request-started', section, requestId })

    try {
      const response = await config.load({
        accessToken,
        signal: controller.signal,
      })
      const data = config.validate(response)
      if (!isMountedRef.current || requestsRef.current[section].id !== requestId) return
      dispatch({ type: 'request-succeeded', section, requestId, data })
    } catch (error) {
      if (error?.name === 'AbortError' || !isMountedRef.current
        || requestsRef.current[section].id !== requestId) return
      dispatch({
        type: 'request-failed',
        section,
        requestId,
        error: getAdminDashboardErrorMessage(error),
      })
    } finally {
      if (requestsRef.current[section].id === requestId) {
        requestsRef.current[section].controller = null
      }
    }
  }, [accessToken])

  useEffect(() => {
    isMountedRef.current = true
    const activeRequests = requestsRef.current
    for (const section of Object.keys(SECTION_CONFIG)) loadSection(section)
    return () => {
      isMountedRef.current = false
      for (const request of Object.values(activeRequests)) {
        request.id += 1
        request.controller?.abort()
        request.controller = null
      }
    }
  }, [loadSection])

  const overviewData = state.overview.data
  const statisticCards = overviewData ? getAdminStatisticCards(overviewData) : []
  const activityChart = state.activity.data
    ? getAdminActivityChart(state.activity.data)
    : null
  const recentActivities = state.recent.data?.items ?? []

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
        <div><p>Tổng quan hệ thống</p><h2>Chỉ số quản trị</h2><span>Số liệu được cập nhật từ hệ thống và không bao gồm tài liệu đang xóa.</span></div>
        <strong>{overviewData ? 'Đã cập nhật' : 'Đang cập nhật'}</strong>
      </div>

      {state.overview.status === 'loading' && !overviewData && (
        <section className="admin-stats" aria-label="Đang tải số liệu quản trị" aria-busy="true">
          {ADMIN_STATISTICS.map((statistic) => (
            <article className="admin-stat-card admin-stat-card--loading" key={statistic.key}>
              <span className="admin-skeleton admin-skeleton--icon" />
              <span className="admin-skeleton admin-skeleton--value" />
              <span className="admin-skeleton admin-skeleton--label" />
            </article>
          ))}
        </section>
      )}

      {state.overview.status === 'error' && !overviewData && (
        <SectionError message={state.overview.error} onRetry={() => loadSection('overview')} />
      )}

      {overviewData && (
        <>
          {state.overview.status === 'error' && (
            <RefreshError message={state.overview.error} onRetry={() => loadSection('overview')} />
          )}
          <section className="admin-stats" aria-label="Thống kê tổng quan" aria-busy={state.overview.status === 'loading'}>
            {statisticCards.map((statistic) => (
              <article className="admin-stat-card" key={statistic.key}>
                <div className={`admin-stat-card__icon admin-stat-card__icon--${statistic.tone}`}><Icon name={statistic.icon} size={22} /></div>
                <strong>{new Intl.NumberFormat('vi-VN').format(statistic.value)}</strong>
                <h3>{statistic.label}</h3>
                <p>{statistic.description}</p>
              </article>
            ))}
          </section>
        </>
      )}

      <div className="admin-overview-grid">
        <section className="admin-panel admin-chart-panel" aria-labelledby="admin-chart-title">
          <div className="admin-panel__heading">
            <div><p>Hoạt động hệ thống</p><h2 id="admin-chart-title">7 ngày gần nhất</h2></div>
            <span>Giờ UTC</span>
          </div>

          {state.activity.status === 'loading' && !activityChart && (
            <div className="admin-panel-skeleton" aria-label="Đang tải biểu đồ" aria-busy="true"><span /><span /><span /><span /></div>
          )}
          {state.activity.status === 'error' && !activityChart && (
            <SectionError message={state.activity.error} onRetry={() => loadSection('activity')} />
          )}
          {activityChart && (
            <>
              {state.activity.status === 'error' && (
                <RefreshError message={state.activity.error} onRetry={() => loadSection('activity')} />
              )}
              <div className="admin-chart-legend" aria-label="Chú giải biểu đồ">
                {ADMIN_ACTIVITY_SERIES.map((series) => <span key={series.key}><i className={`admin-chart-tone--${series.tone}`} />{series.label}</span>)}
              </div>
              <div className="admin-chart-scroll">
                <div className="admin-chart" aria-label="Biểu đồ hoạt động bảy ngày">
                  <div className="admin-chart__axis" aria-hidden="true">
                    <span>{activityChart.maximum}</span>
                    <span>{Math.ceil(activityChart.maximum / 2)}</span>
                    <span>0</span>
                  </div>
                  <div className="admin-chart__plot">
                    {activityChart.items.map((day) => (
                      <div className="admin-chart__column" key={day.date}>
                        <div className="admin-chart__bars">
                          {day.series.map((series) => (
                            <span
                              className={`admin-chart__bar admin-chart__bar--${series.tone} ${series.value === 0 ? 'admin-chart__bar--zero' : ''}`}
                              key={series.key}
                              style={{ '--admin-bar-height': `${series.height}%` }}
                              title={`${series.label}: ${series.value}`}
                              aria-label={`${day.label}, ${series.label}: ${series.value}`}
                            />
                          ))}
                        </div>
                        <small>{day.label}</small>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
              {activityChart.maximum === 0 && <p className="admin-chart__zero-note" role="status">Chưa ghi nhận hoạt động trong 7 ngày này.</p>}
            </>
          )}
        </section>

        <section className="admin-panel admin-activity" aria-labelledby="admin-activity-title">
          <div className="admin-panel__heading">
            <div><p>Cập nhật gần đây</p><h2 id="admin-activity-title">Hoạt động mới</h2></div>
            <span>10 mục gần nhất</span>
          </div>

          {state.recent.status === 'loading' && !state.recent.data && (
            <div className="admin-activity-skeleton" aria-label="Đang tải hoạt động" aria-busy="true"><span /><span /><span /></div>
          )}
          {state.recent.status === 'error' && !state.recent.data && (
            <SectionError message={state.recent.error} onRetry={() => loadSection('recent')} />
          )}
          {state.recent.data && (
            <>
              {state.recent.status === 'error' && (
                <RefreshError message={state.recent.error} onRetry={() => loadSection('recent')} />
              )}
              {recentActivities.length === 0 ? (
                <div className="admin-activity-empty" role="status">
                  <span><Icon name="history" size={25} /></span>
                  <h3>Chưa có hoạt động để hiển thị</h3>
                  <p>Các hoạt động mới sẽ xuất hiện tại đây khi hệ thống có dữ liệu.</p>
                </div>
              ) : (
                <div className="admin-activity__list">
                  {recentActivities.map((activity) => {
                    const presentation = getAdminRecentActivityPresentation(activity)
                    return (
                      <article key={`${activity.activity_type}:${activity.resource_id}`}>
                        <span className={`admin-activity__icon admin-activity__icon--${presentation.tone}`}><Icon name={presentation.icon} size={18} /></span>
                        <div><strong>{presentation.title}</strong><span>{presentation.detail}</span><time>{presentation.time}</time></div>
                      </article>
                    )
                  })}
                </div>
              )}
              <p className="admin-activity__disclaimer">Hoạt động được tổng hợp từ dữ liệu hiện có và không thay thế lịch sử theo dõi đầy đủ.</p>
            </>
          )}

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
