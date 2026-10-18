import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const adminCssUrl = new URL('../src/components/admin/Admin.css', import.meta.url)
const uiPolishUrl = new URL('../src/ui-polish.css', import.meta.url)
const adminDocumentsUrl = new URL('../src/components/admin/AdminDocuments.jsx', import.meta.url)
const adminUsersUrl = new URL('../src/components/admin/AdminUsers.jsx', import.meta.url)

test('wide admin tables scroll inside their own region instead of being clipped', async () => {
  const css = await readFile(adminCssUrl, 'utf8')

  assert.match(css, /\.admin-table-wrap\s*\{[^}]*max-width:\s*100%;[^}]*overflow-x:\s*auto;/s)
  assert.match(css, /\.admin-documents-table\s*\{\s*min-width:\s*1180px;/)
  assert.match(css, /\.admin-table th:last-child,[\s\S]*position:\s*sticky;[\s\S]*right:\s*0;/)
  assert.match(css, /@media \(max-width:\s*720px\)[\s\S]*\.admin-table th:last-child,[\s\S]*position:\s*static;/)
})

test('admin table regions remain keyboard accessible and long document names expose a title', async () => {
  const [documents, users] = await Promise.all([
    readFile(adminDocumentsUrl, 'utf8'),
    readFile(adminUsersUrl, 'utf8'),
  ])

  for (const source of [documents, users]) {
    assert.match(source, /className="admin-table-wrap" role="region" tabIndex="0"/)
    assert.match(source, /có thể cuộn ngang/)
  }
  assert.match(documents, /<strong title=\{document\.title\}>/)
})

test('filters, pagination, modal and dark mobile cards keep responsive safeguards', async () => {
  const [css, polish] = await Promise.all([
    readFile(adminCssUrl, 'utf8'),
    readFile(uiPolishUrl, 'utf8'),
  ])

  assert.match(css, /\.admin-documents-toolbar\s*\{\s*flex-wrap:\s*wrap;/)
  assert.match(css, /\.admin-pagination\s*\{[\s\S]*flex-direction:\s*column;/)
  assert.match(css, /\.admin-dialog\s*\{[^}]*max-height:\s*calc\(100dvh - 48px\);/s)
  assert.match(css, /\.admin-dialog__body\s*\{[^}]*overflow-y:\s*auto;/s)
  assert.match(polish, /\[data-theme='dark'\] \.admin-table tr/)
  assert.match(polish, /\[data-theme='dark'\] \.admin-documents-skeleton/)
})
