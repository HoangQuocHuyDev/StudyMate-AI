import { useEffect, useRef, useState } from 'react'
import { useAuth } from '../contexts/AuthContext'
import { useNavigation } from '../navigation/NavigationContext'
import {
  ApiConfigurationError,
  ApiHttpError,
  ApiNetworkError,
} from '../services/apiClient'
import { changePassword, updateProfile } from '../services/authService'
import { useTheme } from '../theme/ThemeContext.js'
import {
  getDisplayName,
  getDisplayUsername,
  getUserInitials,
} from '../utils/userDisplay'
import Header from './Header'
import Icon from './Icons'
import { createPasswordChangeResponseGuard } from './settingsPasswordFlow.js'
import Sidebar from './Sidebar'
import './Settings.css'

function SectionHeading({ id, icon, title, description }) {
  return (
    <div className="settings-card__heading">
      <div><Icon name={icon} size={20} /></div>
      <span><h2 id={id}>{title}</h2><p>{description}</p></span>
    </div>
  )
}

function getRequestErrorMessage(error, fallback) {
  if (error instanceof ApiNetworkError) {
    return 'Không thể kết nối đến hệ thống. Vui lòng kiểm tra mạng và thử lại.'
  }
  if (error instanceof ApiConfigurationError) {
    return 'Ứng dụng chưa được cấu hình đầy đủ. Vui lòng liên hệ quản trị viên.'
  }
  if (error instanceof ApiHttpError && error.status === 400) return error.message
  if (error instanceof ApiHttpError && error.status === 422) {
    return 'Thông tin gửi lên chưa hợp lệ. Vui lòng kiểm tra lại.'
  }
  if (error instanceof ApiHttpError && error.status >= 500) {
    return 'Hệ thống chưa thể xử lý yêu cầu lúc này. Vui lòng thử lại sau.'
  }
  if (error instanceof ApiHttpError && error.status !== 401) return fallback
  return fallback
}

function ProfileSettings() {
  const {
    accessToken,
    user,
    isAuthenticated,
    updateCurrentUser,
  } = useAuth()
  const currentUser = isAuthenticated ? user : null
  const displayName = getDisplayName(currentUser)
  const username = getDisplayUsername(currentUser)
  const initials = getUserInitials(currentUser)
  const [fullName, setFullName] = useState(() => (
    typeof currentUser?.full_name === 'string' ? currentUser.full_name.trim() : ''
  ))
  const [error, setError] = useState('')
  const [notice, setNotice] = useState(null)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const submissionRef = useRef(false)

  const handleSubmit = async (event) => {
    event.preventDefault()
    if (submissionRef.current) return
    const normalizedName = fullName.trim()
    if (normalizedName.length < 2 || normalizedName.length > 100) {
      setError('Họ và tên phải có từ 2 đến 100 ký tự.')
      setNotice(null)
      return
    }
    setError('')
    setNotice(null)
    setIsSubmitting(true)
    submissionRef.current = true
    const submittedToken = accessToken
    try {
      const updatedUser = await updateProfile(normalizedName, {
        accessToken: submittedToken,
      })
      if (!updateCurrentUser(updatedUser, submittedToken)) return
      setFullName(updatedUser.full_name)
      setNotice({ type: 'success', message: 'Đã cập nhật thông tin tài khoản.' })
    } catch (requestError) {
      if (requestError instanceof ApiHttpError && requestError.status === 401) return
      setNotice({
        type: 'error',
        message: getRequestErrorMessage(
          requestError,
          'Không thể cập nhật thông tin tài khoản lúc này.',
        ),
      })
    } finally {
      submissionRef.current = false
      setIsSubmitting(false)
    }
  }

  return (
    <section className="settings-card" aria-labelledby="profile-settings-title">
      <SectionHeading id="profile-settings-title" icon="user" title="Thông tin cá nhân" description="Quản lý thông tin hiển thị của tài khoản." />
      <div className="settings-profile">
        <div className="settings-avatar" aria-label={`Ảnh đại diện của ${displayName}`}>{initials}</div>
        <div><strong>Ảnh đại diện</strong><p>Ảnh đại diện mẫu của tài khoản.</p></div>
      </div>
      <form className="settings-form" onSubmit={handleSubmit} noValidate>
        <label className="settings-field">
          <span>Họ và tên</span>
          <div className={error ? 'settings-control settings-control--error' : 'settings-control'}><Icon name="user" size={18} /><input type="text" value={fullName} onChange={(event) => { setFullName(event.target.value); setError(''); setNotice(null) }} autoComplete="name" minLength={2} maxLength={100} disabled={isSubmitting} aria-invalid={Boolean(error)} aria-describedby={error ? 'settings-name-error' : undefined} /></div>
          {error && <small id="settings-name-error">{error}</small>}
        </label>
        <label className="settings-field">
          <span>Tên đăng nhập</span>
          <div className="settings-control settings-control--readonly"><span className="settings-at">@</span><input type="text" value={username} placeholder="Chưa có tên đăng nhập" readOnly aria-readonly="true" /></div>
          <small>Tên đăng nhập hiện chưa thể thay đổi.</small>
        </label>
        <button className="settings-primary-button" type="submit" disabled={isSubmitting} aria-busy={isSubmitting}><Icon name="check" size={17} />{isSubmitting ? 'Đang lưu...' : 'Lưu thay đổi'}</button>
        {notice && <p className={`settings-notice settings-notice--${notice.type}`} role={notice.type === 'error' ? 'alert' : 'status'}>{notice.message}</p>}
      </form>
    </section>
  )
}

function PasswordSettings() {
  const {
    getSessionIdentity,
    isCurrentSession,
    logoutCurrentSession,
  } = useAuth()
  const { navigate } = useNavigation()
  const [passwords, setPasswords] = useState({ current: '', next: '', confirm: '' })
  const [errors, setErrors] = useState({})
  const [notice, setNotice] = useState(null)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const submissionRef = useRef(false)
  const requestControllerRef = useRef(null)
  const [responseGuard] = useState(() => createPasswordChangeResponseGuard({
    getSessionIdentity,
    isCurrentSession,
    logoutCurrentSession,
  }))

  useEffect(() => () => {
    requestControllerRef.current?.abort()
    requestControllerRef.current = null
    responseGuard.unmount()
  }, [responseGuard])

  const validate = (name, value, form = passwords) => {
    if (!value) return name === 'current' ? 'Vui lòng nhập mật khẩu hiện tại.' : name === 'next' ? 'Vui lòng nhập mật khẩu mới.' : 'Vui lòng xác nhận mật khẩu mới.'
    if (name === 'next' && (value.length < 8 || value.length > 128)) return 'Mật khẩu mới phải có từ 8 đến 128 ký tự.'
    if (name === 'next' && (!Array.from(value).some((character) => /\p{L}/u.test(character)) || !/[0-9]/.test(value))) return 'Mật khẩu mới phải chứa ít nhất một chữ cái và một chữ số.'
    if (name === 'next' && value === form.current) return 'Mật khẩu mới phải khác mật khẩu hiện tại.'
    if (name === 'confirm' && value !== form.next) return 'Mật khẩu xác nhận không trùng khớp.'
    return ''
  }

  const handleChange = (event) => {
    const { name, value } = event.target
    const nextPasswords = { ...passwords, [name]: value }
    setPasswords(nextPasswords)
    setErrors((current) => ({ ...current, [name]: '', ...(name === 'next' && current.confirm ? { confirm: validate('confirm', nextPasswords.confirm, nextPasswords) } : {}) }))
    setNotice(null)
  }

  const handleSubmit = async (event) => {
    event.preventDefault()
    if (submissionRef.current) return
    const nextErrors = {
      current: validate('current', passwords.current),
      next: validate('next', passwords.next),
      confirm: validate('confirm', passwords.confirm),
    }
    setErrors(nextErrors)
    if (Object.values(nextErrors).some(Boolean)) {
      setNotice(null)
      return
    }
    submissionRef.current = true
    setIsSubmitting(true)
    setNotice(null)
    const request = responseGuard.begin()
    const controller = new AbortController()
    requestControllerRef.current = controller
    try {
      await changePassword({
        currentPassword: passwords.current,
        newPassword: passwords.next,
        confirmNewPassword: passwords.confirm,
      }, {
        accessToken: request.sessionIdentity.accessToken,
        signal: controller.signal,
      })
      if (!responseGuard.complete(request)) return
      navigate('/login?password_changed=1', { replace: true })
    } catch (requestError) {
      if (
        requestError?.name === 'AbortError'
        || !responseGuard.canHandleResponse(request)
        || (requestError instanceof ApiHttpError && requestError.status === 401)
      ) return
      setNotice({
        type: 'error',
        message: getRequestErrorMessage(
          requestError,
          'Không thể đổi mật khẩu lúc này.',
        ),
      })
    } finally {
      if (responseGuard.canHandleResponse(request)) {
        requestControllerRef.current = null
        submissionRef.current = false
        setIsSubmitting(false)
      }
    }
  }

  const fields = [
    { name: 'current', label: 'Mật khẩu hiện tại', placeholder: 'Nhập mật khẩu hiện tại', autoComplete: 'current-password' },
    { name: 'next', label: 'Mật khẩu mới', placeholder: 'Tối thiểu 8 ký tự', autoComplete: 'new-password' },
    { name: 'confirm', label: 'Xác nhận mật khẩu mới', placeholder: 'Nhập lại mật khẩu mới', autoComplete: 'new-password' },
  ]

  return (
    <section className="settings-card" aria-labelledby="password-settings-title">
      <SectionHeading id="password-settings-title" icon="lock" title="Đổi mật khẩu" description="Sử dụng mật khẩu có ít nhất 8 ký tự để bảo vệ tài khoản." />
      <form className="settings-form settings-password-form" onSubmit={handleSubmit} noValidate>
        {fields.map((field) => (
          <label className="settings-field" key={field.name}>
            <span>{field.label}</span>
            <div className={errors[field.name] ? 'settings-control settings-control--error' : 'settings-control'}><Icon name="lock" size={18} /><input name={field.name} type="password" value={passwords[field.name]} onChange={handleChange} placeholder={field.placeholder} autoComplete={field.autoComplete} minLength={field.name === 'current' ? undefined : 8} maxLength={128} disabled={isSubmitting} aria-invalid={Boolean(errors[field.name])} aria-describedby={errors[field.name] ? `${field.name}-password-error` : undefined} /></div>
            {errors[field.name] && <small id={`${field.name}-password-error`}>{errors[field.name]}</small>}
          </label>
        ))}
        <button className="settings-primary-button" type="submit" disabled={isSubmitting} aria-busy={isSubmitting}><Icon name="lock" size={17} />{isSubmitting ? 'Đang đổi mật khẩu...' : 'Đổi mật khẩu'}</button>
        {notice && <p className={`settings-notice settings-notice--${notice.type}`} role="alert">{notice.message}</p>}
      </form>
    </section>
  )
}

function AppearanceSettings({ theme, onChange }) {
  return (
    <section className="settings-card settings-card--appearance" aria-labelledby="appearance-settings-title">
      <SectionHeading id="appearance-settings-title" icon="sun" title="Tùy chỉnh giao diện" description="Chọn giao diện phù hợp với môi trường học tập của bạn." />
      <div className="settings-theme-options" role="radiogroup" aria-label="Chọn giao diện">
        <button className={theme === 'light' ? 'settings-theme-option settings-theme-option--active' : 'settings-theme-option'} type="button" role="radio" aria-checked={theme === 'light'} onClick={() => onChange('light')}>
          <span className="settings-theme-preview settings-theme-preview--light"><i /><i /><i /></span>
          <span className="settings-theme-option__copy"><Icon name="sun" size={18} /><span><strong>Sáng</strong><small>Giao diện sáng, rõ ràng và quen thuộc.</small></span></span>
          <i className="settings-theme-radio" aria-hidden="true" />
        </button>
        <button className={theme === 'dark' ? 'settings-theme-option settings-theme-option--active' : 'settings-theme-option'} type="button" role="radio" aria-checked={theme === 'dark'} onClick={() => onChange('dark')}>
          <span className="settings-theme-preview settings-theme-preview--dark"><i /><i /><i /></span>
          <span className="settings-theme-option__copy"><Icon name="moon" size={18} /><span><strong>Tối</strong><small>Giảm độ sáng khi học tập vào ban đêm.</small></span></span>
          <i className="settings-theme-radio" aria-hidden="true" />
        </button>
      </div>
      <p className="settings-theme-note">Lựa chọn được áp dụng trên toàn bộ website và lưu trên trình duyệt này.</p>
    </section>
  )
}

function Settings({ isSidebarOpen, onOpenSidebar, onCloseSidebar }) {
  const { theme, setTheme } = useTheme()
  const { sessionGeneration } = useAuth()

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
    <div className="app-shell settings-shell">
      <Sidebar isOpen={isSidebarOpen} onClose={onCloseSidebar} />
      <button className={`sidebar-overlay ${isSidebarOpen ? 'sidebar-overlay--visible' : ''}`} type="button" onClick={onCloseSidebar} aria-label="Đóng thanh điều hướng" tabIndex={isSidebarOpen ? 0 : -1} />

      <div className="app-main">
        <Header title="Cài đặt" onOpenSidebar={onOpenSidebar} />
        <main className="main-content settings-page">
          <section className="settings-hero" aria-labelledby="settings-title">
            <p>Thiết lập tài khoản</p>
            <h1 id="settings-title">Cài đặt</h1>
            <span>Quản lý thông tin cá nhân, bảo mật và giao diện StudyMate AI.</span>
          </section>
          <div className="settings-grid">
            <ProfileSettings />
            <PasswordSettings key={sessionGeneration} />
            <AppearanceSettings theme={theme} onChange={setTheme} />
          </div>
        </main>
      </div>
    </div>
  )
}

export default Settings
