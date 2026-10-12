import { createContext, useContext } from 'react'

export const AuthContext = createContext(undefined)

export class AuthSessionError extends Error {
  constructor(message, options) {
    super(message, options)
    this.name = 'AuthSessionError'
  }
}

export function useAuth() {
  const context = useContext(AuthContext)

  if (context === undefined) {
    throw new Error('useAuth phải được sử dụng bên trong AuthProvider.')
  }

  return context
}
