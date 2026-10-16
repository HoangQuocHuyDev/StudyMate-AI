import { useCallback, useLayoutEffect, useMemo, useState } from 'react'
import { ThemeContext } from './ThemeContext.js'
import {
  applyThemePreference,
  isSupportedTheme,
  persistThemePreference,
  readThemePreference,
} from './themePreference.js'

export function ThemeProvider({ children }) {
  const [theme, setThemeState] = useState(readThemePreference)

  useLayoutEffect(() => {
    applyThemePreference(theme)
    persistThemePreference(theme)
  }, [theme])

  const setTheme = useCallback((nextTheme) => {
    if (!isSupportedTheme(nextTheme)) return false
    setThemeState(nextTheme)
    return true
  }, [])

  const value = useMemo(() => ({ theme, setTheme }), [setTheme, theme])
  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>
}
