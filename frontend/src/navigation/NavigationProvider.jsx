import { useCallback, useEffect, useMemo, useState } from 'react'
import { NavigationContext } from './NavigationContext'
import {
  createLocationSnapshot,
  navigateBrowserLocation,
  subscribeToBrowserLocation,
} from './location'

function readBrowserLocation() {
  return createLocationSnapshot(window.location)
}

export function NavigationProvider({ children }) {
  const [location, setLocation] = useState(readBrowserLocation)

  const navigate = useCallback((destination, { replace = false } = {}) => {
    const result = navigateBrowserLocation(window, destination, { replace })
    if (result.changed) setLocation(result.location)
  }, [])

  useEffect(() => subscribeToBrowserLocation(window, setLocation), [])

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

  const value = useMemo(() => ({
    currentPath: location.pathname,
    currentSearch: location.search,
    currentHash: location.hash,
    location,
    navigate,
  }), [location, navigate])

  return (
    <NavigationContext.Provider value={value}>
      {children}
    </NavigationContext.Provider>
  )
}
