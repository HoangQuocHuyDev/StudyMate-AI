export function normalizePath(pathname) {
  const normalized = String(pathname || '/').replace(/\/+$/, '')
  return normalized || '/'
}

function normalizeSuffix(value, prefix) {
  if (!value) return ''
  const stringValue = String(value)
  return stringValue.startsWith(prefix) ? stringValue : `${prefix}${stringValue}`
}

export function createLocationSnapshot({ pathname, search, hash }) {
  return {
    pathname: normalizePath(pathname),
    search: normalizeSuffix(search, '?'),
    hash: normalizeSuffix(hash, '#'),
  }
}

export function locationToString(location) {
  return `${location.pathname}${location.search}${location.hash}`
}

export function locationsEqual(left, right) {
  return locationToString(left) === locationToString(right)
}

export function navigateBrowserLocation(browserWindow, destination, { replace = false } = {}) {
  const url = new URL(destination, browserWindow.location.href)
  if (url.origin !== browserWindow.location.origin) {
    throw new TypeError('Điều hướng nội bộ không hỗ trợ URL khác origin.')
  }

  const nextLocation = createLocationSnapshot(url)
  const currentLocation = createLocationSnapshot(browserWindow.location)
  if (locationsEqual(nextLocation, currentLocation)) {
    return { changed: false, location: currentLocation }
  }

  const historyMethod = replace ? 'replaceState' : 'pushState'
  browserWindow.history[historyMethod](null, '', locationToString(nextLocation))
  return { changed: true, location: nextLocation }
}

export function subscribeToBrowserLocation(browserWindow, onChange) {
  const handlePopState = () => onChange(createLocationSnapshot(browserWindow.location))
  browserWindow.addEventListener('popstate', handlePopState)
  return () => browserWindow.removeEventListener('popstate', handlePopState)
}
