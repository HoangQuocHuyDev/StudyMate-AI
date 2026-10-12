import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react'
import {
  ApiConfigurationError,
  ApiHttpError,
  ApiNetworkError,
} from '../services/apiClient'
import {
  getCurrentUser,
  InvalidCurrentUserResponseError,
} from '../services/authService'
import { AuthContext, AuthSessionError } from './AuthContext'

const emptySession = Object.freeze({ accessToken: null, user: null })

function getSessionErrorMessage(error) {
  if (error instanceof ApiHttpError && error.status === 401) {
    return 'Phiên đăng nhập không hợp lệ hoặc đã hết hạn.'
  }

  if (error instanceof ApiHttpError && error.status === 503) {
    return 'Máy chủ tạm thời không thể xác minh tài khoản. Vui lòng thử lại.'
  }

  if (error instanceof ApiNetworkError) {
    return 'Không thể kết nối đến máy chủ để xác minh tài khoản.'
  }

  if (error instanceof ApiConfigurationError) {
    return 'Frontend chưa được cấu hình địa chỉ API hợp lệ.'
  }

  if (error instanceof InvalidCurrentUserResponseError) {
    return 'Không thể xác minh thông tin người dùng từ phản hồi máy chủ.'
  }

  return 'Không thể xác minh phiên đăng nhập lúc này.'
}

export function AuthProvider({ children }) {
  const [session, setSession] = useState(emptySession)
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState(null)
  const requestVersion = useRef(0)

  useEffect(() => () => {
    requestVersion.current += 1
  }, [])

  const logout = useCallback(() => {
    requestVersion.current += 1
    setSession(emptySession)
    setIsLoading(false)
    setError(null)
  }, [])

  const loginSession = useCallback(async (accessToken) => {
    if (typeof accessToken !== 'string' || !accessToken.trim()) {
      logout()
      const message = 'Không thể xác minh phiên đăng nhập vì token không hợp lệ.'
      setError(message)
      throw new AuthSessionError(message)
    }

    const currentRequest = requestVersion.current + 1
    requestVersion.current = currentRequest
    setSession(emptySession)
    setError(null)
    setIsLoading(true)

    try {
      const user = await getCurrentUser(accessToken)

      if (requestVersion.current !== currentRequest) return null

      setSession({ accessToken, user })
      return user
    } catch (requestError) {
      if (requestVersion.current !== currentRequest) return null

      const message = getSessionErrorMessage(requestError)
      setSession(emptySession)
      setError(message)
      throw new AuthSessionError(message, { cause: requestError })
    } finally {
      if (requestVersion.current === currentRequest) {
        setIsLoading(false)
      }
    }
  }, [logout])

  const value = useMemo(() => ({
    accessToken: session.accessToken,
    user: session.user,
    isAuthenticated: Boolean(session.accessToken && session.user),
    isLoading,
    error,
    loginSession,
    logout,
  }), [error, isLoading, loginSession, logout, session])

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
