import { useState } from 'react'
import AdminDashboard from './components/admin/AdminDashboard'
import Chat from './components/Chat'
import Documents from './components/Documents'
import History from './components/History'
import Login from './components/Login'
import MainLayout from './components/MainLayout'
import Register from './components/Register'
import Settings from './components/Settings'
import Summarize from './components/Summarize'
import './App.css'
import './ui-polish.css'

function App() {
  const [isSidebarOpen, setIsSidebarOpen] = useState(false)
  const currentPath = window.location.pathname.replace(/\/$/, '')

  if (currentPath === '/admin') {
    return <AdminDashboard />
  }

  if (currentPath === '/login') {
    return <Login />
  }

  if (currentPath === '/register') {
    return <Register />
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
