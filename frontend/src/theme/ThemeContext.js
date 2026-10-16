import { createContext, useContext } from 'react'

export const ThemeContext = createContext(undefined)

export function useTheme() {
  const context = useContext(ThemeContext)
  if (context === undefined) {
    throw new Error('useTheme phải được sử dụng bên trong ThemeProvider.')
  }
  return context
}
