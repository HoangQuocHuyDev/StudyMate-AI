import { useState } from 'react'
import './Login.css'

const usernamePattern = /^[A-Za-z0-9_]+$/

function Brand() {
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

function Login() {
  const [form, setForm] = useState({ username: '', password: '', remember: false })
  const [errors, setErrors] = useState({})
  const [showPassword, setShowPassword] = useState(false)
  const [notice, setNotice] = useState('')

  const validateField = (name, value) => {
    if (!value.trim()) return name === 'username' ? 'Vui lòng nhập tên đăng nhập.' : 'Vui lòng nhập mật khẩu.'
    if (name === 'username' && (value.length < 3 || value.length > 30)) return 'Tên đăng nhập phải dài từ 3 đến 30 ký tự.'
    if (name === 'username' && !usernamePattern.test(value)) return 'Tên đăng nhập chỉ được chứa chữ cái không dấu, số và dấu gạch dưới.'
    if (name === 'password' && value.length < 8) return 'Mật khẩu phải có ít nhất 8 ký tự.'
    return ''
  }

  const handleChange = (event) => {
    const { name, value, checked, type } = event.target
    setForm((current) => ({ ...current, [name]: type === 'checkbox' ? checked : value }))
    if (errors[name]) setErrors((current) => ({ ...current, [name]: '' }))
    if (notice) setNotice('')
  }

  const handleBlur = (event) => {
    const { name, value } = event.target
    setErrors((current) => ({ ...current, [name]: validateField(name, value) }))
  }

  const handleSubmit = (event) => {
    event.preventDefault()
    const nextErrors = {
      username: validateField('username', form.username),
      password: validateField('password', form.password),
    }
    setErrors(nextErrors)

    if (nextErrors.username || nextErrors.password) {
      setNotice('')
      return
    }

    setNotice('Thông tin hợp lệ. Chức năng xác thực hiện chưa được kết nối.')
  }

  return (
    <main className="login-page">
      <div className="login-page__glow login-page__glow--top" aria-hidden="true" />
      <div className="login-page__glow login-page__glow--bottom" aria-hidden="true" />

      <section className="login-shell" aria-labelledby="login-title">
        <div className="login-intro">
          <Brand />
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

        <div className="login-panel">
          <div className="login-panel__mobile-brand"><Brand /></div>
          <div className="login-form-wrap">
            <div className="login-heading">
              <span className="login-heading__accent" aria-hidden="true" />
              <h1 id="login-title">Chào mừng trở lại</h1>
              <p>Đăng nhập để tiếp tục hành trình học tập của bạn</p>
            </div>

            <form className="login-form" onSubmit={handleSubmit} noValidate>
              <div className="form-field">
                <label htmlFor="username">Tên đăng nhập</label>
                <div className={`form-control ${errors.username ? 'form-control--error' : ''}`}>
                  <svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                    <circle cx="12" cy="8" r="4" /><path d="M4.5 21a7.5 7.5 0 0 1 15 0" />
                  </svg>
                  <input id="username" name="username" type="text" value={form.username} onChange={handleChange} onBlur={handleBlur} placeholder="Nhập tên đăng nhập" autoComplete="username" minLength="3" maxLength="30" required aria-invalid={Boolean(errors.username)} aria-describedby={errors.username ? 'username-error' : undefined} />
                </div>
                {errors.username && <p className="form-field__error" id="username-error">{errors.username}</p>}
              </div>

              <div className="form-field">
                <label htmlFor="password">Mật khẩu</label>
                <div className={`form-control ${errors.password ? 'form-control--error' : ''}`}>
                  <svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                    <rect x="4" y="10" width="16" height="11" rx="3" /><path d="M8 10V7a4 4 0 0 1 8 0v3M12 14v3" />
                  </svg>
                  <input id="password" name="password" type={showPassword ? 'text' : 'password'} value={form.password} onChange={handleChange} onBlur={handleBlur} placeholder="Nhập mật khẩu" autoComplete="current-password" minLength="8" required aria-invalid={Boolean(errors.password)} aria-describedby={errors.password ? 'password-error' : undefined} />
                  <button className="password-toggle" type="button" onClick={() => setShowPassword((visible) => !visible)} aria-label={showPassword ? 'Ẩn mật khẩu' : 'Hiện mật khẩu'} aria-pressed={showPassword}>
                    <EyeIcon hidden={showPassword} />
                  </button>
                </div>
                {errors.password && <p className="form-field__error" id="password-error">{errors.password}</p>}
              </div>

              <label className="remember-option">
                <input name="remember" type="checkbox" checked={form.remember} onChange={handleChange} />
                <span aria-hidden="true">
                  <svg width="13" height="13" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"><path d="m3.5 8 3 3 6-6" /></svg>
                </span>
                Ghi nhớ đăng nhập
              </label>

              <button className="login-submit" type="submit">
                Đăng nhập
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M5 12h14M13 6l6 6-6 6" /></svg>
              </button>

              {notice && <p className="login-notice" role="status">{notice}</p>}
            </form>

            <p className="signup-prompt">Chưa có tài khoản? <a href="/register">Đăng ký ngay</a></p>
          </div>
        </div>
      </section>
    </main>
  )
}

export default Login
