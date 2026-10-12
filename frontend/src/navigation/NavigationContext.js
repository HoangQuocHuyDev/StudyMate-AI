import { createContext, useContext } from 'react'

export const NavigationContext = createContext(undefined)

export function useNavigation() {
  const context = useContext(NavigationContext)

  if (context === undefined) {
    throw new Error('useNavigation phải được sử dụng bên trong NavigationProvider.')
  }

  return context
}
