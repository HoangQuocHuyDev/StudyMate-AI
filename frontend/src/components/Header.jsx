import { useEffect, useState } from 'react'
import { useAuth } from '../contexts/AuthContext'
import { useNavigation } from '../navigation/NavigationContext'
import {
  getDisplayName,
  getRoleLabel,
  getUserInitials,
} from '../utils/userDisplay'
import {
  buildDocumentSearchUrl,
  getDocumentSearchValidationMessage,
  normalizeDocumentSearchTerm,
  parseDocumentSearch,
} from './documentSearchUrl'
import Icon from './Icons'

function Header({ onOpenSidebar, title = 'Tổng quan' }) {
  const { user, isAuthenticated } = useAuth()
  const {
    currentHash,
    currentPath,
    currentSearch,
    navigate,
  } = useNavigation()
  const [searchValue, setSearchValue] = useState(() => (
    currentPath === '/documents' ? parseDocumentSearch(currentSearch) : ''
  ))
  const [searchError, setSearchError] = useState('')
  const currentUser = isAuthenticated ? user : null
  const displayName = getDisplayName(currentUser)
  const roleLabel = getRoleLabel(currentUser)
  const initials = getUserInitials(currentUser)

  useEffect(() => {
    if (currentPath !== '/documents') return
    // URL changes are an external navigation source (Header, Back/Forward, or reload).
    // oxlint-disable-next-line react/set-state-in-effect
    setSearchValue(parseDocumentSearch(currentSearch))
    setSearchError('')
  }, [currentPath, currentSearch])

  const handleSearchChange = (event) => {
    const value = event.target.value
    setSearchValue(value)
    if (searchError) setSearchError(getDocumentSearchValidationMessage(value))
  }

  const handleSearchSubmit = (event) => {
    event.preventDefault()
    const validationMessage = getDocumentSearchValidationMessage(searchValue)
    if (validationMessage) {
      setSearchError(validationMessage)
      return
    }

    const normalizedValue = normalizeDocumentSearchTerm(searchValue)
    const destination = buildDocumentSearchUrl({
      keyword: normalizedValue,
      currentPath,
      currentSearch,
      currentHash,
    })
    setSearchValue(normalizedValue)
    setSearchError('')
    navigate(destination)
  }

  return (
    <header className="header">
      <div className="header__title-group">
        <button className="icon-button header__menu" type="button" onClick={onOpenSidebar} aria-label="Mở thanh điều hướng"><Icon name="menu" /></button>
        <div><p className="header__eyebrow">Không gian của bạn</p><h1>{title}</h1></div>
      </div>

      <div className="header__actions">
        <form className="header-search" role="search" onSubmit={handleSearchSubmit} noValidate>
          <label className="search-box">
            <Icon name="search" size={18} />
            <input
              type="search"
              value={searchValue}
              onChange={handleSearchChange}
              placeholder="Tìm kiếm tài liệu..."
              aria-label="Tìm kiếm tài liệu toàn cục"
              aria-invalid={Boolean(searchError)}
              aria-describedby={searchError ? 'header-search-error' : undefined}
            />
          </label>
          {searchError && <p id="header-search-error" className="header-search__error" role="alert">{searchError}</p>}
        </form>
        <button className="profile-button" type="button" aria-label={`Mở menu tài khoản của ${displayName}`}>
          <span className="avatar">{initials}</span>
          <span className="profile-copy"><strong>{displayName}</strong><small>{roleLabel}</small></span>
          <span className="profile-chevron" aria-hidden="true">⌄</span>
        </button>
      </div>
    </header>
  )
}

export default Header
