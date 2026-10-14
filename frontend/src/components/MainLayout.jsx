import {
  useCallback,
  useEffect,
  useReducer,
  useRef,
} from 'react'
import wavingHand from '../assets/waving-hand-3d.png'
import { useAuth } from '../contexts/AuthContext'
import { useNavigation } from '../navigation/NavigationContext'
import { getDashboardOverview } from '../services/dashboardService'
import { getDocuments } from '../services/documentService'
import { getDisplayName } from '../utils/userDisplay'
import {
  DASHBOARD_DOCUMENT_LIMIT,
  DASHBOARD_FEATURES,
  DASHBOARD_STATISTICS,
  dashboardDocumentsReducer,
  dashboardOverviewReducer,
  formatDashboardDocumentDate,
  getDashboardDocumentsErrorMessage,
  getDashboardDocumentStatus,
  getDashboardOverviewErrorMessage,
  getDashboardStatisticCards,
  initialDashboardDocumentsState,
  initialDashboardOverviewState,
  isDashboardOverviewEmpty,
  validateDashboardDocumentsResponse,
  validateDashboardOverviewResponse,
} from './dashboardUi'
import Header from './Header'
import Icon from './Icons'
import Sidebar from './Sidebar'

function MainLayout({ isSidebarOpen, onOpenSidebar, onCloseSidebar }) {
  const { accessToken, user, isAuthenticated } = useAuth()
  const { navigate } = useNavigation()
  const displayName = getDisplayName(isAuthenticated ? user : null)
  const [documentsState, dispatchDocuments] = useReducer(
    dashboardDocumentsReducer,
    initialDashboardDocumentsState,
  )
  const [overviewState, dispatchOverview] = useReducer(
    dashboardOverviewReducer,
    initialDashboardOverviewState,
  )
  const documentsRequestRef = useRef({ controller: null, id: 0 })
  const overviewRequestRef = useRef({ controller: null, id: 0 })
  const isMountedRef = useRef(true)

  const loadRecentDocuments = useCallback(async () => {
    const requestId = documentsRequestRef.current.id + 1
    const controller = new AbortController()
    documentsRequestRef.current.controller?.abort()
    documentsRequestRef.current = { controller, id: requestId }
    dispatchDocuments({ type: 'request-started', requestId })

    try {
      const data = validateDashboardDocumentsResponse(await getDocuments({
        accessToken,
        page: 1,
        pageSize: DASHBOARD_DOCUMENT_LIMIT,
        signal: controller.signal,
      }))
      if (!isMountedRef.current || documentsRequestRef.current.id !== requestId) return
      dispatchDocuments({ type: 'request-succeeded', requestId, data })
    } catch (error) {
      if (
        error?.name === 'AbortError'
        || !isMountedRef.current
        || documentsRequestRef.current.id !== requestId
      ) return
      dispatchDocuments({
        type: 'request-failed',
        requestId,
        error: getDashboardDocumentsErrorMessage(error),
      })
    } finally {
      if (documentsRequestRef.current.id === requestId) {
        documentsRequestRef.current.controller = null
      }
    }
  }, [accessToken])

  const loadDashboardOverview = useCallback(async () => {
    const requestId = overviewRequestRef.current.id + 1
    const controller = new AbortController()
    overviewRequestRef.current.controller?.abort()
    overviewRequestRef.current = { controller, id: requestId }
    dispatchOverview({ type: 'request-started', requestId })

    try {
      const data = validateDashboardOverviewResponse(await getDashboardOverview({
        accessToken,
        signal: controller.signal,
      }))
      if (!isMountedRef.current || overviewRequestRef.current.id !== requestId) return
      dispatchOverview({ type: 'request-succeeded', requestId, data })
    } catch (error) {
      if (
        error?.name === 'AbortError'
        || !isMountedRef.current
        || overviewRequestRef.current.id !== requestId
      ) return
      dispatchOverview({
        type: 'request-failed',
        requestId,
        error: getDashboardOverviewErrorMessage(error),
      })
    } finally {
      if (overviewRequestRef.current.id === requestId) {
        overviewRequestRef.current.controller = null
      }
    }
  }, [accessToken])

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
    isMountedRef.current = true
    loadRecentDocuments()
    loadDashboardOverview()
    return () => {
      isMountedRef.current = false
      documentsRequestRef.current.id += 1
      documentsRequestRef.current.controller?.abort()
      documentsRequestRef.current.controller = null
      overviewRequestRef.current.id += 1
      overviewRequestRef.current.controller?.abort()
      overviewRequestRef.current.controller = null
    }
  }, [loadDashboardOverview, loadRecentDocuments])

  const hasDocumentsData = documentsState.data !== null
  const recentDocuments = documentsState.data?.items ?? []
  const hasOverviewData = overviewState.data !== null
  const statisticCards = hasOverviewData
    ? getDashboardStatisticCards(overviewState.data)
    : []

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
              <h2 id="welcome-title">Chào buổi sáng, {displayName}! <img className="welcome__wave" src={wavingHand} alt="" /></h2>
              <p>Sẵn sàng học hiệu quả hơn hôm nay? Hãy bắt đầu với tài liệu của bạn.</p>
            </div>
            <div className="welcome__visual" aria-hidden="true">
              <span className="orbit orbit--one" /><span className="orbit orbit--two" />
              <div className="visual-icon"><Icon name="library" size={34} /></div>
              <span className="visual-spark"><Icon name="sparkle" size={18} /></span>
            </div>
          </section>

          <section className="dashboard-overview" aria-labelledby="dashboard-overview-title">
            <div className="section-heading dashboard-overview__heading">
              <div>
                <p className="section-heading__eyebrow">Tiến độ học tập</p>
                <h2 id="dashboard-overview-title">Tổng quan của bạn</h2>
              </div>
            </div>

            {overviewState.status === 'loading' && !hasOverviewData && (
              <div className="dashboard-stats" aria-label="Đang tải số liệu tổng quan" aria-busy="true">
                {DASHBOARD_STATISTICS.map((statistic) => (
                  <div className="dashboard-stat dashboard-stat--loading" key={statistic.field}>
                    <span className="dashboard-stat__skeleton dashboard-stat__skeleton--icon" />
                    <span className="dashboard-stat__skeleton dashboard-stat__skeleton--value" />
                    <span className="dashboard-stat__skeleton dashboard-stat__skeleton--label" />
                  </div>
                ))}
              </div>
            )}

            {overviewState.status === 'error' && !hasOverviewData && (
              <div className="dashboard-overview__state dashboard-overview__state--error" role="alert">
                <Icon name="refresh" size={24} />
                <p>{overviewState.error}</p>
                <button type="button" onClick={loadDashboardOverview}>Thử lại</button>
              </div>
            )}

            {hasOverviewData && overviewState.status === 'error' && (
              <div className="dashboard-overview__refresh-error" role="alert">
                <span>{overviewState.error} Số liệu đang hiển thị được giữ nguyên.</span>
                <button type="button" onClick={loadDashboardOverview}>Thử lại</button>
              </div>
            )}

            {hasOverviewData && (
              <>
                <div className="dashboard-stats-wrap">
                  {overviewState.status === 'loading' && (
                    <p className="dashboard-overview__refreshing" role="status">Đang cập nhật...</p>
                  )}
                  <div className="dashboard-stats" aria-busy={overviewState.status === 'loading'}>
                    {statisticCards.map((statistic) => (
                      <article className="dashboard-stat" key={statistic.field}>
                        <span className={`dashboard-stat__icon dashboard-stat__icon--${statistic.tone}`}>
                          <Icon name={statistic.icon} size={21} />
                        </span>
                        <strong>{new Intl.NumberFormat('vi-VN').format(statistic.value)}</strong>
                        <h3>{statistic.label}</h3>
                        <p>{statistic.description}</p>
                      </article>
                    ))}
                  </div>
                </div>
                {isDashboardOverviewEmpty(overviewState.data) && (
                  <p className="dashboard-overview__empty" role="status">
                    Chưa có dữ liệu học tập. Hãy tải tài liệu đầu tiên để bắt đầu.
                  </p>
                )}
              </>
            )}
          </section>

          <section className="features" aria-labelledby="features-title">
            <div className="section-heading">
              <div><p className="section-heading__eyebrow">Bắt đầu nhanh</p><h2 id="features-title">Bạn muốn làm gì?</h2></div>
              <p>Những công cụ giúp việc học của bạn nhẹ nhàng hơn.</p>
            </div>
            <div className="feature-grid">
              {DASHBOARD_FEATURES.map((feature) => (
                <article className="feature-card" key={feature.title}>
                  <div className={`feature-card__icon feature-card__icon--${feature.tone}`}><Icon name={feature.icon} size={23} /></div>
                  <h3>{feature.title}</h3>
                  <p>{feature.description}</p>
                  <button type="button" className="feature-card__link" onClick={() => navigate(feature.path)}>{feature.link}<Icon name="arrow" size={17} /></button>
                </article>
              ))}
            </div>
          </section>

          <section className="recent-documents" aria-labelledby="recent-documents-title">
            <div className="section-heading recent-documents__heading">
              <div>
                <p className="section-heading__eyebrow">Thư viện của bạn</p>
                <h2 id="recent-documents-title">Tài liệu gần đây</h2>
              </div>
              {hasDocumentsData && (
                <span className="recent-documents__total">
                  Tổng cộng {new Intl.NumberFormat('vi-VN').format(documentsState.data.total)} tài liệu
                </span>
              )}
            </div>

            {documentsState.status === 'loading' && !hasDocumentsData && (
              <div className="recent-documents__state" role="status" aria-live="polite">
                <span className="recent-documents__spinner" aria-hidden="true" />
                <p>Đang tải tài liệu gần đây...</p>
              </div>
            )}

            {documentsState.status === 'error' && !hasDocumentsData && (
              <div className="recent-documents__state recent-documents__state--error" role="alert">
                <Icon name="refresh" size={24} />
                <p>{documentsState.error}</p>
                <button type="button" onClick={loadRecentDocuments}>Thử lại</button>
              </div>
            )}

            {hasDocumentsData && documentsState.status === 'error' && (
              <div className="recent-documents__refresh-error" role="alert">
                <span>{documentsState.error} Dữ liệu đang hiển thị được giữ nguyên.</span>
                <button type="button" onClick={loadRecentDocuments}>Thử lại</button>
              </div>
            )}

            {hasDocumentsData && recentDocuments.length === 0 && (
              <div className="recent-documents__state recent-documents__state--empty">
                <Icon name="documents" size={30} />
                <h3>Bạn chưa có tài liệu nào</h3>
                <p>Hãy tải lên tài liệu PDF hoặc DOCX đầu tiên để bắt đầu học cùng StudyMate AI.</p>
                <button type="button" onClick={() => navigate('/documents')}>Tải tài liệu</button>
              </div>
            )}

            {recentDocuments.length > 0 && (
              <div className="recent-documents__list" aria-busy={documentsState.status === 'loading'}>
                {documentsState.status === 'loading' && (
                  <p className="recent-documents__refreshing" role="status">Đang cập nhật...</p>
                )}
                {recentDocuments.map((document) => {
                  const status = getDashboardDocumentStatus(document.status)
                  return (
                    <button
                      className="recent-document"
                      type="button"
                      key={document.id}
                      onClick={() => navigate('/documents')}
                      aria-label={`Mở trang tài liệu để xem ${document.title}`}
                    >
                      <span className={`recent-document__file recent-document__file--${document.file_type.toLowerCase()}`}>
                        <Icon name="file" size={22} />
                        <small>{document.file_type}</small>
                      </span>
                      <span className="recent-document__details">
                        <strong title={document.title}>{document.title}</strong>
                        <small>Tải lên {formatDashboardDocumentDate(document.created_at)}</small>
                      </span>
                      <span className={`recent-document__status recent-document__status--${status.className}`}>
                        <i />{status.label}
                      </span>
                      <Icon name="arrow" size={18} className="recent-document__arrow" />
                    </button>
                  )
                })}
              </div>
            )}
          </section>
        </main>
      </div>
    </div>
  )
}

export default MainLayout
