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

export function getHomeRoute({ isAuthenticated, role }) {
  if (!isAuthenticated) return '/login'
  return role === 'ADMIN' ? '/admin' : '/'
}

export function getRouteRedirect({
  currentPath,
  isAuthenticated,
  isLoading,
  role,
}) {
  if (isLoading) return null
  if (!knownRoutes.has(currentPath)) return null

  const isPublicRoute = publicRoutes.has(currentPath)

  if (isPublicRoute && isAuthenticated) {
    return getHomeRoute({ isAuthenticated, role })
  }

  if (!isPublicRoute && !isAuthenticated) {
    return '/login'
  }

  if (adminRoutes.has(currentPath) && role !== 'ADMIN') {
    return '/'
  }

  return null
}
