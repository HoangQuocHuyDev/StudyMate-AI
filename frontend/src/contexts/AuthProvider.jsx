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
  registerUnauthorizedHandler,
} from '../services/apiClient'
import {
  getCurrentUser,
  InvalidCurrentUserResponseError,
  logout as requestLogout,
} from '../services/authService'
import { AuthContext, AuthSessionError } from './AuthContext'
import { createLogoutController } from './authLogout'

const emptySession = Object.freeze({ accessToken: null, user: null, version: 0 })

function getSessionErrorMessage(error) {
  if (error instanceof ApiHttpError && error.status === 401) {
    return 'Phiên đăng nhập không hợp lệ hoặc đã hết hạn.'
  }

  if (error instanceof ApiHttpError && error.status === 503) {
    return 'Hệ thống tạm thời không thể xác minh tài khoản. Vui lòng thử lại.'
  }

  if (error instanceof ApiNetworkError) {
    return 'Không thể kết nối đến hệ thống để xác minh tài khoản.'
  }

  if (error instanceof ApiConfigurationError) {
    return 'Ứng dụng chưa được cấu hình đầy đủ. Vui lòng liên hệ quản trị viên.'
  }

  if (error instanceof InvalidCurrentUserResponseError) {
    return 'Không thể xác minh thông tin tài khoản. Vui lòng thử lại.'
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
  const unregisterUnauthorizedRef = useRef(null)
  const isMounted = useRef(true)

  const clearLocalSession = useCallback(() => {
    unregisterUnauthorizedRef.current?.()
    unregisterUnauthorizedRef.current = null
    requestVersion.current += 1
    const clearedSession = {
      ...emptySession,
      version: requestVersion.current,
    }
    sessionRef.current = clearedSession
    setSession(clearedSession)
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
      unregisterUnauthorizedRef.current?.()
      unregisterUnauthorizedRef.current = null
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

  const getSessionIdentity = useCallback(() => ({
    accessToken: sessionRef.current.accessToken,
    generation: sessionRef.current.version,
  }), [])

  const isCurrentSession = useCallback((identity) => Boolean(
    identity
    && identity.accessToken
    && sessionRef.current.accessToken === identity.accessToken
    && sessionRef.current.version === identity.generation
  ), [])

  const logoutCurrentSession = useCallback((identity) => {
    if (!isCurrentSession(identity)) return false
    logoutController.cancel()
    clearLocalSession()
    return true
  }, [clearLocalSession, isCurrentSession, logoutController])

  const updateCurrentUser = useCallback((nextUser, expectedAccessToken) => {
    const currentSession = sessionRef.current
    if (
      !nextUser
      || currentSession.accessToken !== expectedAccessToken
      || currentSession.user?.id !== nextUser.id
    ) return false

    const nextSession = {
      accessToken: currentSession.accessToken,
      user: nextUser,
    }
    sessionRef.current = {
      ...nextSession,
      version: currentSession.version,
    }
    setSession(nextSession)
    return true
  }, [])

  const loginSession = useCallback(async (accessToken) => {
    if (typeof accessToken !== 'string' || !accessToken.trim()) {
      logout()
      const message = 'Không thể xác minh phiên đăng nhập. Vui lòng đăng nhập lại.'
      setError(message)
      throw new AuthSessionError(message)
    }

    const currentRequest = requestVersion.current + 1
    requestVersion.current = currentRequest
    logoutController.cancel()
    unregisterUnauthorizedRef.current?.()
    unregisterUnauthorizedRef.current = null
    sessionRef.current = {
      ...emptySession,
      version: currentRequest,
    }
    setSession({ ...emptySession, version: currentRequest })
    setIsLoggingOut(false)
    setError(null)
    setIsLoading(true)

    try {
      const user = await getCurrentUser(accessToken)

      if (requestVersion.current !== currentRequest) return null

      const nextSession = { accessToken, user, version: currentRequest }
      sessionRef.current = nextSession
      unregisterUnauthorizedRef.current = registerUnauthorizedHandler(
        (rejectedAccessToken) => {
          const currentSession = sessionRef.current
          if (
            currentSession.version !== currentRequest
            || currentSession.accessToken !== rejectedAccessToken
          ) return
          clearLocalSession()
        },
      )
      setSession(nextSession)
      return user
    } catch (requestError) {
      if (requestVersion.current !== currentRequest) return null

      const message = getSessionErrorMessage(requestError)
      const failedSession = {
        ...emptySession,
        version: currentRequest,
      }
      setSession(failedSession)
      sessionRef.current = failedSession
      setError(message)
      throw new AuthSessionError(message, { cause: requestError })
    } finally {
      if (requestVersion.current === currentRequest) {
        setIsLoading(false)
      }
    }
  }, [clearLocalSession, logout, logoutController])

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
    getSessionIdentity,
    isCurrentSession,
    logoutCurrentSession,
    sessionGeneration: session.version,
    updateCurrentUser,
  }), [
    error,
    isLoading,
    isLoggingOut,
    loginSession,
    logout,
    logoutWithRevocation,
    getSessionIdentity,
    isCurrentSession,
    logoutCurrentSession,
    updateCurrentUser,
    session,
  ])

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
