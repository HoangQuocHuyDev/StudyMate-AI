import { useCallback, useEffect, useMemo, useState } from 'react'
import { NavigationContext } from './NavigationContext'

function normalizePath(pathname) {
  const normalized = pathname.replace(/\/+$/, '')
  return normalized || '/'
}

export function NavigationProvider({ children }) {
  const [currentPath, setCurrentPath] = useState(() => (
    normalizePath(window.location.pathname)
  ))

  const navigate = useCallback((destination, { replace = false } = {}) => {
    const url = new URL(destination, window.location.href)

    if (url.origin !== window.location.origin) {
      throw new TypeError('Điều hướng nội bộ không hỗ trợ URL khác origin.')
    }

    const nextLocation = `${url.pathname}${url.search}${url.hash}`
    const historyMethod = replace ? 'replaceState' : 'pushState'
    window.history[historyMethod](null, '', nextLocation)
    setCurrentPath(normalizePath(url.pathname))
  }, [])

  useEffect(() => {
    const handlePopState = () => {
      setCurrentPath(normalizePath(window.location.pathname))
    }

    window.addEventListener('popstate', handlePopState)
    return () => window.removeEventListener('popstate', handlePopState)
  }, [])

  useEffect(() => {
    const handleInternalLink = (event) => {
      if (
        event.defaultPrevented
        || event.button !== 0
        || event.metaKey
        || event.ctrlKey
        || event.shiftKey
        || event.altKey
      ) return

      if (!(event.target instanceof Element)) return

      const link = event.target.closest('a[href]')
      if (
        !link
        || (link.target && link.target !== '_self')
        || link.hasAttribute('download')
      ) return

      const url = new URL(link.href, window.location.href)
      if (url.origin !== window.location.origin) return

      event.preventDefault()
      navigate(`${url.pathname}${url.search}${url.hash}`)
    }

    document.addEventListener('click', handleInternalLink)
    return () => document.removeEventListener('click', handleInternalLink)
  }, [navigate])

  const value = useMemo(() => ({ currentPath, navigate }), [currentPath, navigate])

  return (
    <NavigationContext.Provider value={value}>
      {children}
    </NavigationContext.Provider>
  )
}
