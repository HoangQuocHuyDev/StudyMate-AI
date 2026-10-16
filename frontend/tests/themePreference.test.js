import assert from 'node:assert/strict'
import test from 'node:test'

import {
  applyThemePreference,
  persistThemePreference,
  readThemePreference,
  THEME_STORAGE_KEY,
} from '../src/theme/themePreference.js'

function memoryStorage(initialValue = null) {
  const values = new Map()
  if (initialValue !== null) values.set(THEME_STORAGE_KEY, initialValue)
  return {
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, value),
    value: () => values.get(THEME_STORAGE_KEY),
  }
}

test('theme preference restores only supported values and defaults safely', () => {
  assert.equal(readThemePreference(memoryStorage('dark')), 'dark')
  assert.equal(readThemePreference(memoryStorage('light')), 'light')
  assert.equal(readThemePreference(memoryStorage('system')), 'light')
  assert.equal(readThemePreference({ getItem() { throw new Error('blocked') } }), 'light')
})

test('theme preference persists only non-sensitive light/dark selection', () => {
  const storage = memoryStorage()
  assert.equal(persistThemePreference('dark', storage), true)
  assert.equal(storage.value(), 'dark')
  assert.throws(() => persistThemePreference('header.payload.signature', storage), TypeError)
  assert.equal(storage.value(), 'dark')
})

test('theme preference applies to the document root and handles blocked storage', () => {
  const root = { dataset: {} }
  applyThemePreference('dark', root)
  assert.equal(root.dataset.theme, 'dark')
  assert.equal(persistThemePreference('light', { setItem() { throw new Error('blocked') } }), false)
})
