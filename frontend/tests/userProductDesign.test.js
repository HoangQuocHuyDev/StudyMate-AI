import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const source = (path) => new URL(`../src/${path}`, import.meta.url)

test('user product design system is loaded after legacy styles', async () => {
  const app = await readFile(source('App.jsx'), 'utf8')
  const legacyIndex = app.indexOf("import './ui-polish.css'")
  const productIndex = app.indexOf("import './user-product.css'")

  assert.ok(legacyIndex >= 0)
  assert.ok(productIndex > legacyIndex)
})

test('user design tokens cover color, spacing, radius, surface and content width', async () => {
  const css = await readFile(source('user-product.css'), 'utf8')

  for (const token of [
    '--user-blue-600',
    '--user-ink',
    '--user-surface',
    '--user-border',
    '--user-radius-md',
    '--user-space-5',
    '--user-content',
  ]) assert.match(css, new RegExp(token))

  assert.match(css, /\[data-theme='dark'\]/)
  assert.match(css, /:focus-visible/)
  assert.match(css, /prefers-reduced-motion/)
})

test('redesign changes information hierarchy across every user workflow', async () => {
  const css = await readFile(source('user-product.css'), 'utf8')

  for (const selector of [
    '.welcome',
    '.dashboard-stats',
    '.document-upload-panel',
    '.documents-toolbar',
    '.summarize-workspace',
    '.summary-result__content',
    '.chat-workspace',
    '.chat-message--ai',
    '.history-list__items',
    '.settings-grid',
    '.login-shell',
  ]) assert.match(css, new RegExp(selector.replaceAll('.', '\\.')))
})

test('user redesign is isolated from Admin and docx-preview generated content', async () => {
  const css = await readFile(source('user-product.css'), 'utf8')

  assert.doesNotMatch(css, /\.admin-(?:shell|main|header|sidebar|content)/)
  assert.doesNotMatch(css, /\.docx-wrapper|section\.docx/)
  assert.match(css, /\.app-shell/)
  assert.match(css, /\.login-page/)
})

test('responsive rules cover laptop, tablet and mobile layouts', async () => {
  const css = await readFile(source('user-product.css'), 'utf8')

  assert.match(css, /@media \(max-width: 1100px\)/)
  assert.match(css, /@media \(max-width: 960px\)/)
  assert.match(css, /@media \(max-width: 768px\)/)
  assert.match(css, /@media \(max-width: 520px\)/)
})

test('filter selection styles match the existing Documents and History markup', async () => {
  const css = await readFile(source('user-product.css'), 'utf8')

  assert.match(css, /\.document-filter--active/)
  assert.match(css, /\.history-filter--active/)
  assert.doesNotMatch(css, /document-filters button\.active|history-filters button\.active/)
})

test('authentication forms cannot exceed a narrow mobile viewport', async () => {
  const css = await readFile(source('user-product.css'), 'utf8')

  assert.match(css, /\.login-form-wrap,[\s\S]*?\.form-control \{ min-width: 0; max-width: 100%; \}/)
  assert.match(css, /\.login-form-wrap,[\s\S]*?\.form-control \{ width: 100%; \}/)
  assert.match(css, /\.login-panel \{ width: 100%; overflow: hidden; \}/)
})
