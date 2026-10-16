import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.jsx'
import { AuthProvider } from './contexts/AuthProvider.jsx'
import { NavigationProvider } from './navigation/NavigationProvider.jsx'
import { ThemeProvider } from './theme/ThemeProvider.jsx'

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <ThemeProvider>
      <AuthProvider>
        <NavigationProvider>
          <App />
        </NavigationProvider>
      </AuthProvider>
    </ThemeProvider>
  </StrictMode>,
)
