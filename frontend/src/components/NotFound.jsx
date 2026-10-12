import { useAuth } from '../contexts/AuthContext'
import { useNavigation } from '../navigation/NavigationContext'
import { getHomeRoute } from '../navigation/routePolicy'
import Icon from './Icons'
import './NotFound.css'

function NotFound() {
  const { isAuthenticated, user } = useAuth()
  const { navigate } = useNavigation()
  const homeRoute = getHomeRoute({ isAuthenticated, role: user?.role })

  return (
    <main className="not-found">
      <section className="not-found__card" aria-labelledby="not-found-title">
        <a className="not-found__brand" href={homeRoute} aria-label="StudyMate AI - Trang chủ">
          <span className="not-found__brand-mark" aria-hidden="true">S<i /></span>
          <span>StudyMate <strong>AI</strong></span>
        </a>

        <div className="not-found__visual" aria-hidden="true">
          <span className="not-found__code">404</span>
          <span className="not-found__icon"><Icon name="search" size={30} /></span>
        </div>

        <h1 id="not-found-title">Không tìm thấy trang</h1>
        <p>Trang bạn đang tìm kiếm không tồn tại hoặc đường dẫn đã thay đổi.</p>
        <button className="not-found__button" type="button" onClick={() => navigate(homeRoute)}>
          <Icon name="arrow" size={18} />
          Về trang chủ
        </button>
      </section>
    </main>
  )
}

export default NotFound
