import { useEffect, useState } from 'react'
import AdminDashboard from './components/admin/AdminDashboard'
import Chat from './components/Chat'
import Documents from './components/Documents'
import History from './components/History'
import Login from './components/Login'
import MainLayout from './components/MainLayout'
import NotFound from './components/NotFound'
import Register from './components/Register'
import Settings from './components/Settings'
import Summarize from './components/Summarize'
import { useAuth } from './contexts/AuthContext'
import { useNavigation } from './navigation/NavigationContext'
import {
  adminRoutes,
  getRouteRedirect,
  knownRoutes,
  publicRoutes,
} from './navigation/routePolicy'
import './App.css'
import './ui-polish.css'
import './user-product.css'

function App() {
  const [isSidebarOpen, setIsSidebarOpen] = useState(false)
  const { isAuthenticated, isLoading, user } = useAuth()
  const {
    currentHash,
    currentPath,
    currentSearch,
    navigate,
  } = useNavigation()
  const isKnownRoute = knownRoutes.has(currentPath)
  const isPublicRoute = publicRoutes.has(currentPath)
  const isAdminRoute = adminRoutes.has(currentPath)

  useEffect(() => {
    const redirectPath = getRouteRedirect({
      currentPath,
      currentSearch,
      currentHash,
      isAuthenticated,
      isLoading,
      role: user?.role,
    })

    if (redirectPath && redirectPath !== currentPath) {
      navigate(redirectPath, { replace: true })
    }
  }, [
    currentPath,
    currentSearch,
    currentHash,
    isAuthenticated,
    isLoading,
    navigate,
    user,
  ])

  if (!isKnownRoute) return <NotFound />

  if (isPublicRoute) {
    if (isAuthenticated && !isLoading) return null
    return currentPath === '/login' ? <Login /> : <Register />
  }

  if (isLoading || !isAuthenticated) return null
  if (isAdminRoute && user?.role !== 'ADMIN') return null

  if (currentPath === '/admin') {
    return <AdminDashboard />
  }

  if (currentPath === '/documents') {
    return (
      <Documents
        isSidebarOpen={isSidebarOpen}
        onOpenSidebar={() => setIsSidebarOpen(true)}
        onCloseSidebar={() => setIsSidebarOpen(false)}
      />
    )
  }

  if (currentPath === '/summarize') {
    return (
      <Summarize
        isSidebarOpen={isSidebarOpen}
        onOpenSidebar={() => setIsSidebarOpen(true)}
        onCloseSidebar={() => setIsSidebarOpen(false)}
      />
    )
  }

  if (currentPath === '/chat') {
    return (
      <Chat
        isSidebarOpen={isSidebarOpen}
        onOpenSidebar={() => setIsSidebarOpen(true)}
        onCloseSidebar={() => setIsSidebarOpen(false)}
      />
    )
  }

  if (currentPath === '/history') {
    return (
      <History
        isSidebarOpen={isSidebarOpen}
        onOpenSidebar={() => setIsSidebarOpen(true)}
        onCloseSidebar={() => setIsSidebarOpen(false)}
      />
    )
  }

  if (currentPath === '/settings') {
    return (
      <Settings
        isSidebarOpen={isSidebarOpen}
        onOpenSidebar={() => setIsSidebarOpen(true)}
        onCloseSidebar={() => setIsSidebarOpen(false)}
      />
    )
  }

  return (
    <MainLayout
      isSidebarOpen={isSidebarOpen}
      onOpenSidebar={() => setIsSidebarOpen(true)}
      onCloseSidebar={() => setIsSidebarOpen(false)}
    />
  )
}

export default App
