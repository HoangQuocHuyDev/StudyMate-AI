import apiClient from './apiClient.js'

export class InvalidLoginResponseError extends Error {
  constructor() {
    super('Phản hồi đăng nhập từ máy chủ không hợp lệ.')
    this.name = 'InvalidLoginResponseError'
  }
}

export class InvalidCurrentUserResponseError extends Error {
  constructor() {
    super('Phản hồi thông tin người dùng từ máy chủ không hợp lệ.')
    this.name = 'InvalidCurrentUserResponseError'
  }
}

const validRoles = new Set(['USER', 'ADMIN'])

function hasJwtStructure(token) {
  if (typeof token !== 'string') return false

  const segments = token.split('.')
  return segments.length === 3
    && segments.every((segment) => segment.length > 0 && /^[A-Za-z0-9_-]+$/.test(segment))
}

function isValidCurrentUser(user) {
  return Boolean(
    user
    && Number.isSafeInteger(user.id)
    && typeof user.full_name === 'string'
    && user.full_name.length > 0
    && typeof user.username === 'string'
    && user.username.length > 0
    && validRoles.has(user.role)
    && user.is_active === true
    && typeof user.created_at === 'string'
    && user.created_at.length > 0,
  )
}

export function register({ fullName, username, password, confirmPassword }) {
  return apiClient.post('/auth/register', {
    full_name: fullName,
    username,
    password,
    confirm_password: confirmPassword,
  })
}

export async function login({ username, password }) {
  const response = await apiClient.post('/auth/login', { username, password })

  if (
    !response
    || !hasJwtStructure(response.access_token)
    || response.token_type !== 'bearer'
  ) {
    throw new InvalidLoginResponseError()
  }

  return response
}

export async function getCurrentUser(accessToken) {
  if (
    typeof accessToken !== 'string'
    || !accessToken
    || accessToken !== accessToken.trim()
  ) {
    throw new TypeError('Access token không hợp lệ.')
  }

  const user = await apiClient.get('/auth/me', {
    headers: {
      Authorization: `Bearer ${accessToken}`,
    },
  })

  if (!isValidCurrentUser(user)) {
    throw new InvalidCurrentUserResponseError()
  }

  return user
}

export async function logout(accessToken, { signal } = {}) {
  if (
    typeof accessToken !== 'string'
    || !accessToken
    || accessToken !== accessToken.trim()
  ) {
    throw new TypeError('Access token không hợp lệ.')
  }

  await apiClient.post('/auth/logout', undefined, {
    headers: {
      Authorization: `Bearer ${accessToken}`,
    },
    signal,
  })
}
