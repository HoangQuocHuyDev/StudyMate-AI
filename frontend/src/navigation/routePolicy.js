export const publicRoutes = new Set(['/login', '/register'])
export const userRoutes = new Set([
  '/',
  '/documents',
  '/summarize',
  '/chat',
  '/history',
  '/settings',
])
export const adminRoutes = new Set(['/admin'])
export const knownRoutes = new Set([
  ...publicRoutes,
  ...userRoutes,
  ...adminRoutes,
])

export function buildLoginRedirect({
  currentPath,
  currentSearch = '',
  currentHash = '',
}) {
  const returnTo = `${currentPath}${currentSearch}${currentHash}`
  const params = new URLSearchParams({ return_to: returnTo })
  return `/login?${params.toString()}`
}

export function getPostLoginRoute({ currentSearch = '', role }) {
  const fallback = role === 'ADMIN' ? '/admin' : '/'
  const returnTo = new URLSearchParams(currentSearch).get('return_to')
  if (
    !returnTo
    || !returnTo.startsWith('/')
    || returnTo.startsWith('//')
    || returnTo.includes('\\')
  ) return fallback

  const url = new URL(returnTo, 'https://studymate.local')
  if (url.origin !== 'https://studymate.local') return fallback
  if (!knownRoutes.has(url.pathname) || publicRoutes.has(url.pathname)) return fallback
  if (adminRoutes.has(url.pathname) && role !== 'ADMIN') return fallback

  return `${url.pathname}${url.search}${url.hash}`
}

export function getHomeRoute({ isAuthenticated, role }) {
  if (!isAuthenticated) return '/login'
  return role === 'ADMIN' ? '/admin' : '/'
}

export function getRouteRedirect({
  currentPath,
  currentSearch = '',
  currentHash = '',
  isAuthenticated,
  isLoading,
  role,
}) {
  if (isLoading) return null
  if (!knownRoutes.has(currentPath)) return null

  const isPublicRoute = publicRoutes.has(currentPath)

  if (isPublicRoute && isAuthenticated) {
    return getPostLoginRoute({ currentSearch, role })
  }

  if (!isPublicRoute && !isAuthenticated) {
    return buildLoginRedirect({ currentPath, currentSearch, currentHash })
  }

  if (adminRoutes.has(currentPath) && role !== 'ADMIN') {
    return '/'
  }

  return null
}
