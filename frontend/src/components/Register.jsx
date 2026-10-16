import { useState } from 'react'
import {
  ApiConfigurationError,
  ApiHttpError,
  ApiNetworkError,
} from '../services/apiClient'
import { register } from '../services/authService'
import './Login.css'
import './Register.css'

const usernamePattern = /^[A-Za-z0-9_]+$/

function RegisterBrand() {
  return (
    <a className="login-brand" href="/" aria-label="StudyMate AI - Trang chủ">
      <span className="login-brand__mark" aria-hidden="true"><strong>S</strong><i /></span>
      <span className="login-brand__name"><strong>StudyMate</strong><small>AI</small></span>
    </a>
  )
}

function EyeIcon({ hidden }) {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      {hidden ? (
        <>
          <path d="M3 3l18 18" />
          <path d="M10.6 10.7a2 2 0 0 0 2.7 2.7M9.9 4.2A10.8 10.8 0 0 1 12 4c5.5 0 9 6 9 6a16.5 16.5 0 0 1-2.1 2.9M6.6 6.6C4.2 8.1 3 10 3 10s3.5 6 9 6c1 0 2-.2 2.8-.5" />
        </>
      ) : (
        <><path d="M2.5 12s3.5-6 9.5-6 9.5 6 9.5 6-3.5 6-9.5 6-9.5-6-9.5-6Z" /><circle cx="12" cy="12" r="2.5" /></>
      )}
    </svg>
  )
}

function FieldIcon({ type }) {
  if (type === 'user') {
    return (
      <svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <circle cx="12" cy="8" r="4" /><path d="M4.5 21a7.5 7.5 0 0 1 15 0" />
      </svg>
    )
  }

  if (type === 'username') {
    return (
      <svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <circle cx="12" cy="12" r="9" /><path d="M15.5 9.5v4a2 2 0 0 0 4 0V12a7.5 7.5 0 1 0-2.2 5.3M15.5 12a3.5 3.5 0 1 1-7 0 3.5 3.5 0 0 1 7 0Z" />
      </svg>
    )
  }

  return (
    <svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <rect x="4" y="10" width="16" height="11" rx="3" /><path d="M8 10V7a4 4 0 0 1 8 0v3M12 14v3" />
    </svg>
  )
}

const initialForm = { fullName: '', username: '', password: '', confirmPassword: '' }
const backendFieldNames = {
  full_name: 'fullName',
  username: 'username',
  password: 'password',
  confirm_password: 'confirmPassword',
}

function getBackendValidationErrors(detail) {
  if (!Array.isArray(detail)) return {}

  return detail.reduce((fieldErrors, validationError) => {
    const backendField = Array.isArray(validationError?.loc)
      ? validationError.loc.at(-1)
      : null
    const fieldName = backendFieldNames[backendField]

    if (fieldName && typeof validationError?.msg === 'string') {
      fieldErrors[fieldName] = validationError.msg.replace(/^Value error,\s*/i, '')
    }

    return fieldErrors
  }, {})
}

function Register() {
  const [form, setForm] = useState(initialForm)
  const [errors, setErrors] = useState({})
  const [touched, setTouched] = useState({})
  const [showPassword, setShowPassword] = useState(false)
  const [showConfirmPassword, setShowConfirmPassword] = useState(false)
  const [notice, setNotice] = useState(null)
  const [isSubmitting, setIsSubmitting] = useState(false)

  const validateField = (name, value, currentForm = form) => {
    if (!value.trim()) {
      const labels = { fullName: 'họ và tên', username: 'tên đăng nhập', password: 'mật khẩu', confirmPassword: 'xác nhận mật khẩu' }
      return `Vui lòng nhập ${labels[name]}.`
    }
    if (name === 'username' && (value.length < 3 || value.length > 30)) return 'Tên đăng nhập phải dài từ 3 đến 30 ký tự.'
    if (name === 'username' && !usernamePattern.test(value)) return 'Tên đăng nhập chỉ được chứa chữ cái không dấu, số và dấu gạch dưới.'
    if (name === 'password' && value.length < 8) return 'Mật khẩu phải có ít nhất 8 ký tự.'
    if (name === 'confirmPassword' && value !== currentForm.password) return 'Mật khẩu xác nhận không trùng khớp.'
    return ''
  }

  const handleChange = (event) => {
    const { name, value } = event.target
    const nextForm = { ...form, [name]: value }
    setForm(nextForm)
    setNotice(null)

    if (touched[name]) {
      setErrors((current) => ({ ...current, [name]: validateField(name, value, nextForm) }))
    }
    if (name === 'password' && touched.confirmPassword) {
      setErrors((current) => ({ ...current, confirmPassword: validateField('confirmPassword', nextForm.confirmPassword, nextForm) }))
    }
  }

  const handleBlur = (event) => {
    const { name, value } = event.target
    setTouched((current) => ({ ...current, [name]: true }))
    setErrors((current) => ({ ...current, [name]: validateField(name, value) }))
  }

  const handleSubmit = async (event) => {
    event.preventDefault()
    if (isSubmitting) return

    const nextErrors = Object.keys(initialForm).reduce((result, name) => {
      result[name] = validateField(name, form[name])
      return result
    }, {})

    setTouched({ fullName: true, username: true, password: true, confirmPassword: true })
    setErrors(nextErrors)

    if (Object.values(nextErrors).some(Boolean)) {
      setNotice(null)
      return
    }

    setIsSubmitting(true)
    setNotice(null)

    try {
      await register(form)
      setForm(initialForm)
      setErrors({})
      setTouched({})
      setShowPassword(false)
      setShowConfirmPassword(false)
      setNotice({
        type: 'success',
        message: 'Đăng ký thành công. Bạn có thể đăng nhập bằng tài khoản vừa tạo.',
      })
    } catch (error) {
      if (error instanceof ApiHttpError && error.status === 409) {
        setErrors((current) => ({
          ...current,
          username: 'Tên đăng nhập đã tồn tại. Vui lòng chọn tên khác.',
        }))
        setTouched((current) => ({ ...current, username: true }))
        setNotice({ type: 'error', message: 'Không thể đăng ký với tên đăng nhập này.' })
      } else if (error instanceof ApiHttpError && error.status === 422) {
        const backendErrors = getBackendValidationErrors(error.data?.detail)
        setErrors((current) => ({ ...current, ...backendErrors }))
        setTouched((current) => ({
          ...current,
          ...Object.fromEntries(Object.keys(backendErrors).map((name) => [name, true])),
        }))
        setNotice({
          type: 'error',
          message: error.message || 'Dữ liệu đăng ký chưa hợp lệ.',
        })
      } else if (error instanceof ApiNetworkError) {
        setNotice({
          type: 'error',
          message: 'Không thể kết nối đến hệ thống. Vui lòng kiểm tra mạng và thử lại.',
        })
      } else if (error instanceof ApiConfigurationError) {
        setNotice({
          type: 'error',
          message: 'Ứng dụng chưa được cấu hình đầy đủ. Vui lòng liên hệ quản trị viên.',
        })
      } else if (error instanceof ApiHttpError) {
        setNotice({
          type: 'error',
          message: error.message || 'Không thể đăng ký lúc này. Vui lòng thử lại.',
        })
      } else {
        setNotice({
          type: 'error',
          message: 'Đã xảy ra lỗi không mong muốn. Vui lòng thử lại.',
        })
      }
    } finally {
      setIsSubmitting(false)
    }
  }

  const renderPasswordToggle = (visible, setter, label) => (
    <button className="password-toggle" type="button" onClick={() => setter((current) => !current)} aria-label={visible ? `Ẩn ${label}` : `Hiện ${label}`} aria-pressed={visible}>
      <EyeIcon hidden={visible} />
    </button>
  )

  return (
    <main className="login-page register-page">
      <div className="login-page__glow login-page__glow--top" aria-hidden="true" />
      <div className="login-page__glow login-page__glow--bottom" aria-hidden="true" />

      <section className="login-shell register-shell" aria-labelledby="register-title">
        <div className="login-intro">
          <RegisterBrand />
          <div className="login-intro__content">
            <span className="login-intro__eyebrow">Học tập thông minh hơn</span>
            <h2>Mọi tài liệu.<br />Một trợ lý học tập.</h2>
            <p>Tóm tắt, tra cứu và khám phá kiến thức trong không gian học tập của riêng bạn.</p>
          </div>
          <div className="login-intro__art" aria-hidden="true">
            <span className="login-intro__orbit login-intro__orbit--one" />
            <span className="login-intro__orbit login-intro__orbit--two" />
            <div className="login-intro__book">
              <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20" /><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2Z" /><path d="m11 8 1 2.1L14.2 11 12 12l-1 2-1-2-2.1-1L10 10.1Z" />
              </svg>
            </div>
          </div>
          <p className="login-intro__footer">© 2026 StudyMate AI</p>
        </div>

        <div className="login-panel register-panel">
          <div className="login-panel__mobile-brand"><RegisterBrand /></div>
          <div className="login-form-wrap">
            <div className="login-heading register-heading">
              <span className="login-heading__accent" aria-hidden="true" />
              <h1 id="register-title">Tạo tài khoản</h1>
              <p>Bắt đầu hành trình học tập thông minh cùng StudyMate AI</p>
            </div>

            <form className="login-form register-form" onSubmit={handleSubmit} noValidate>
              <div className="form-field">
                <label htmlFor="fullName">Họ và tên</label>
                <div className={`form-control ${errors.fullName ? 'form-control--error' : ''}`}>
                  <FieldIcon type="user" />
                  <input id="fullName" name="fullName" type="text" value={form.fullName} onChange={handleChange} onBlur={handleBlur} placeholder="Nhập họ và tên" autoComplete="name" required aria-invalid={Boolean(errors.fullName)} aria-describedby={errors.fullName ? 'full-name-error' : undefined} />
                </div>
                {errors.fullName && <p className="form-field__error" id="full-name-error">{errors.fullName}</p>}
              </div>

              <div className="form-field">
                <label htmlFor="register-username">Tên đăng nhập</label>
                <div className={`form-control ${errors.username ? 'form-control--error' : ''}`}>
                  <FieldIcon type="username" />
                  <input id="register-username" name="username" type="text" value={form.username} onChange={handleChange} onBlur={handleBlur} placeholder="Nhập tên đăng nhập" autoComplete="username" minLength="3" maxLength="30" required aria-invalid={Boolean(errors.username)} aria-describedby={errors.username ? 'register-username-error' : undefined} />
                </div>
                {errors.username && <p className="form-field__error" id="register-username-error">{errors.username}</p>}
              </div>

              <div className="form-field">
                <label htmlFor="register-password">Mật khẩu</label>
                <div className={`form-control ${errors.password ? 'form-control--error' : ''}`}>
                  <FieldIcon type="password" />
                  <input id="register-password" name="password" type={showPassword ? 'text' : 'password'} value={form.password} onChange={handleChange} onBlur={handleBlur} placeholder="Tối thiểu 8 ký tự" autoComplete="new-password" minLength="8" required aria-invalid={Boolean(errors.password)} aria-describedby={errors.password ? 'register-password-error' : undefined} />
                  {renderPasswordToggle(showPassword, setShowPassword, 'mật khẩu')}
                </div>
                {errors.password && <p className="form-field__error" id="register-password-error">{errors.password}</p>}
              </div>

              <div className="form-field">
                <label htmlFor="confirm-password">Xác nhận mật khẩu</label>
                <div className={`form-control ${errors.confirmPassword ? 'form-control--error' : ''}`}>
                  <FieldIcon type="password" />
                  <input id="confirm-password" name="confirmPassword" type={showConfirmPassword ? 'text' : 'password'} value={form.confirmPassword} onChange={handleChange} onBlur={handleBlur} placeholder="Nhập lại mật khẩu" autoComplete="new-password" minLength="8" required aria-invalid={Boolean(errors.confirmPassword)} aria-describedby={errors.confirmPassword ? 'confirm-password-error' : undefined} />
                  {renderPasswordToggle(showConfirmPassword, setShowConfirmPassword, 'mật khẩu xác nhận')}
                </div>
                {errors.confirmPassword && <p className="form-field__error" id="confirm-password-error">{errors.confirmPassword}</p>}
              </div>

              <button className="login-submit" type="submit" disabled={isSubmitting} aria-busy={isSubmitting}>
                {isSubmitting ? 'Đang đăng ký...' : 'Đăng ký'}
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M5 12h14M13 6l6 6-6 6" /></svg>
              </button>
              {notice && (
                <p
                  className={`login-notice ${notice.type === 'error' ? 'login-notice--error' : ''}`}
                  role={notice.type === 'error' ? 'alert' : 'status'}
                >
                  {notice.message}
                </p>
              )}
            </form>

            <p className="signup-prompt">Đã có tài khoản? <a href="/login">Đăng nhập ngay</a></p>
          </div>
        </div>
      </section>
    </main>
  )
}

export default Register
