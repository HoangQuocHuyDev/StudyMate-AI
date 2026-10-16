export function createPasswordChangeResponseGuard({
  getSessionIdentity,
  isCurrentSession,
  logoutCurrentSession,
}) {
  if (
    typeof getSessionIdentity !== 'function'
    || typeof isCurrentSession !== 'function'
    || typeof logoutCurrentSession !== 'function'
  ) {
    throw new TypeError('Cấu hình bảo vệ phiên đổi mật khẩu không hợp lệ.')
  }

  let isMounted = true
  let requestGeneration = 0

  const begin = () => ({
    requestGeneration: ++requestGeneration,
    sessionIdentity: getSessionIdentity(),
  })

  const isActive = (request) => Boolean(
    isMounted
    && request?.requestGeneration === requestGeneration
    && isCurrentSession(request.sessionIdentity),
  )

  return {
    begin,
    canHandleResponse: isActive,
    complete(request) {
      if (!isActive(request)) return false
      const loggedOut = logoutCurrentSession(request.sessionIdentity)
      if (loggedOut) requestGeneration += 1
      return loggedOut
    },
    invalidate() {
      requestGeneration += 1
    },
    unmount() {
      isMounted = false
      requestGeneration += 1
    },
  }
}
