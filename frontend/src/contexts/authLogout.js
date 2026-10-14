function validateDependencies({ getSession, clearSession, setPending }) {
  if (
    typeof getSession !== 'function'
    || typeof clearSession !== 'function'
    || typeof setPending !== 'function'
  ) {
    throw new TypeError('Logout controller chưa được cấu hình hợp lệ.')
  }
}

export function createLogoutController(requestLogout) {
  if (typeof requestLogout !== 'function') {
    throw new TypeError('Logout controller chưa được cấu hình hợp lệ.')
  }

  let activeOperation = null

  function cancel() {
    activeOperation = null
  }

  function logout(dependencies) {
    validateDependencies(dependencies)
    const { getSession, clearSession, setPending } = dependencies
    const startedSession = getSession()
    const accessToken = startedSession?.accessToken
    const sessionVersion = startedSession?.version

    if (typeof accessToken !== 'string' || !accessToken) {
      clearSession()
      return Promise.resolve(true)
    }

    if (
      activeOperation
      && activeOperation.accessToken === accessToken
      && activeOperation.sessionVersion === sessionVersion
    ) {
      return activeOperation.promise
    }

    const operation = {
      accessToken,
      sessionVersion,
      promise: null,
    }
    setPending(true)

    operation.promise = (async () => {
      let shouldClear = false
      try {
        await requestLogout(accessToken)
      } catch {
        // Local logout is mandatory even when revocation cannot be confirmed.
      } finally {
        const currentSession = getSession()
        shouldClear = currentSession?.version === sessionVersion
          && currentSession?.accessToken === accessToken

        if (shouldClear) clearSession()

        if (activeOperation === operation) {
          activeOperation = null
          setPending(false)
        }
      }

      return shouldClear
    })()

    activeOperation = operation
    return operation.promise
  }

  return { cancel, logout }
}
