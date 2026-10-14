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
  logout as requestLogout,
} from '../services/authService'
import { AuthContext, AuthSessionError } from './AuthContext'
import { createLogoutController } from './authLogout'

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
  const [isLoggingOut, setIsLoggingOut] = useState(false)
  const [error, setError] = useState(null)
  const requestVersion = useRef(0)
  const sessionRef = useRef({ ...emptySession, version: 0 })
  const isMounted = useRef(true)

  const clearLocalSession = useCallback(() => {
    requestVersion.current += 1
    sessionRef.current = {
      ...emptySession,
      version: requestVersion.current,
    }
    setSession(emptySession)
    setIsLoading(false)
    setIsLoggingOut(false)
    setError(null)
  }, [])

  const [logoutController] = useState(() => createLogoutController(requestLogout))

  const logoutWithRevocation = useCallback(
    () => logoutController.logout({
      getSession: () => sessionRef.current,
      clearSession: clearLocalSession,
      setPending: (pending) => {
        if (isMounted.current) setIsLoggingOut(pending)
      },
    }),
    [clearLocalSession, logoutController],
  )

  useEffect(() => {
    isMounted.current = true
    return () => {
      isMounted.current = false
      requestVersion.current += 1
      sessionRef.current = {
        ...emptySession,
        version: requestVersion.current,
      }
      logoutController.cancel()
    }
  }, [logoutController])

  const logout = useCallback(() => {
    logoutController.cancel()
    clearLocalSession()
  }, [clearLocalSession, logoutController])

  const loginSession = useCallback(async (accessToken) => {
    if (typeof accessToken !== 'string' || !accessToken.trim()) {
      logout()
      const message = 'Không thể xác minh phiên đăng nhập vì token không hợp lệ.'
      setError(message)
      throw new AuthSessionError(message)
    }

    const currentRequest = requestVersion.current + 1
    requestVersion.current = currentRequest
    logoutController.cancel()
    sessionRef.current = {
      ...emptySession,
      version: currentRequest,
    }
    setSession(emptySession)
    setIsLoggingOut(false)
    setError(null)
    setIsLoading(true)

    try {
      const user = await getCurrentUser(accessToken)

      if (requestVersion.current !== currentRequest) return null

      const nextSession = { accessToken, user }
      sessionRef.current = { ...nextSession, version: currentRequest }
      setSession(nextSession)
      return user
    } catch (requestError) {
      if (requestVersion.current !== currentRequest) return null

      const message = getSessionErrorMessage(requestError)
      setSession(emptySession)
      sessionRef.current = {
        ...emptySession,
        version: currentRequest,
      }
      setError(message)
      throw new AuthSessionError(message, { cause: requestError })
    } finally {
      if (requestVersion.current === currentRequest) {
        setIsLoading(false)
      }
    }
  }, [logout, logoutController])

  const value = useMemo(() => ({
    accessToken: session.accessToken,
    user: session.user,
    isAuthenticated: Boolean(session.accessToken && session.user),
    isLoading,
    isLoggingOut,
    error,
    loginSession,
    logout,
    logoutWithRevocation,
  }), [
    error,
    isLoading,
    isLoggingOut,
    loginSession,
    logout,
    logoutWithRevocation,
    session,
  ])

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
