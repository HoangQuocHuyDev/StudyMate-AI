function readBearerToken(headers) {
  if (!(headers instanceof Headers)) return null

  const authorization = headers.get('Authorization')
  if (typeof authorization !== 'string') return null

  const match = /^Bearer ([^\s]+)$/.exec(authorization.trim())
  return match?.[1] ?? null
}

export function createUnauthorizedResponseController() {
  let activeRegistration = null
  let nextRegistrationId = 0

  const register = (handler) => {
    if (typeof handler !== 'function') {
      throw new TypeError('Handler xử lý phiên hết hạn phải là một hàm.')
    }

    const registration = {
      handler,
      id: nextRegistrationId + 1,
    }
    nextRegistrationId = registration.id
    activeRegistration = registration

    return () => {
      if (activeRegistration === registration) activeRegistration = null
    }
  }

  const capture = (headers) => {
    const accessToken = readBearerToken(headers)
    if (!accessToken || !activeRegistration) return null

    return {
      accessToken,
      registration: activeRegistration,
    }
  }

  const handle = (snapshot, status) => {
    if (
      status !== 401
      || !snapshot
      || snapshot.registration !== activeRegistration
    ) return false

    snapshot.registration.handler(snapshot.accessToken)
    return true
  }

  return { capture, handle, register }
}

