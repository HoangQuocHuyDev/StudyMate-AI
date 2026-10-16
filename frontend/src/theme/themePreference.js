export const THEME_STORAGE_KEY = 'studymate-theme'
export const SUPPORTED_THEMES = Object.freeze(['light', 'dark'])

export function isSupportedTheme(value) {
  return SUPPORTED_THEMES.includes(value)
}

export function readThemePreference(storage = globalThis.localStorage) {
  try {
    const savedTheme = storage?.getItem(THEME_STORAGE_KEY)
    if (isSupportedTheme(savedTheme)) return savedTheme
  } catch {
    // A blocked storage API must not prevent the application from rendering.
  }

  return 'light'
}

export function persistThemePreference(theme, storage = globalThis.localStorage) {
  if (!isSupportedTheme(theme)) {
    throw new TypeError('Giao diện không được hỗ trợ.')
  }

  try {
    storage?.setItem(THEME_STORAGE_KEY, theme)
    return true
  } catch {
    return false
  }
}

export function applyThemePreference(theme, root = globalThis.document?.documentElement) {
  if (!isSupportedTheme(theme)) {
    throw new TypeError('Giao diện không được hỗ trợ.')
  }
  if (root) root.dataset.theme = theme
}
